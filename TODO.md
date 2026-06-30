# TODO

## bus.py — concurrent write safety

**File:** `bus.py` lines 36–37  
**Issue:** The append-mode write has no file locking. Simultaneous writes from multiple processes can interleave mid-line, corrupting tab-separated records on the channel file.  
**Fix:** Wrap the write with `fcntl.flock(fh, fcntl.LOCK_EX)` before writing and `fcntl.LOCK_UN` after, or use an atomic write pattern.  
**Priority:** Low if single-writer by design; High if any concurrency is introduced.

## bus.py `tail()` — unclosed file handle on touch (line 48)

**File:** `bus.py` line 48  
**Issue:** `open(target, "a", encoding="utf-8").close()` — the handle is opened and closed inline without a `with` block. As written it works, but relies on CPython's reference counting for immediate cleanup. Not portable to other runtimes and not idiomatic.  
**Fix:** Replace with `with open(target, "a", encoding="utf-8"): pass`  
**Priority:** Low.

## bus.py `tail()` — no exit condition; introduce session modes

**File:** `bus.py` `tail()` loop  
**Issue:** `tail()` loops forever with no stop signal. Callers have no built-in way to terminate it cleanly.  
**Proposal:** Introduce two explicit session modes for the bus:

- **Infinite mode** — current behavior; loop runs until the process is killed externally.
- **Timed mode** — caller passes a deadline or duration; `tail()` exits cleanly when time is up.

**Timed session termination must also stop all dependent scripts** (`bashInput.sh`, `bashOutput.sh`, and any other consumers). Implementation options:
- Write a sentinel message to a dedicated `control` channel that all scripts monitor; on receipt they exit.
- Use a PID file written at startup; the timed session sends `SIGTERM` to all registered PIDs on expiry.
- Use a shared `temp/stop` flag file; scripts poll for its existence and exit when found.

**Priority:** Medium — required before any unattended or scheduled use.

## beater.py `main()` — no argv validation (line 32)

**File:** `beater.py` line 32  
**Issue:** `float(argv[1])` is called without validation. Three failure cases:
- Non-numeric string → uncaught `ValueError`, unformatted crash.
- Zero → `time.sleep(0)` becomes a busy loop, pegging the CPU.
- Negative value → `time.sleep(-1)` raises `ValueError` in Python 3.  
**Fix:** Parse inside a `try/except ValueError`, reject values `<= 0` with a clear error message and `sys.exit(2)`.  
**Priority:** Low for manual use; Medium if called from automated scripts.

## chat.sh lines 37–41 — deprecate terminal emulator launch

**File:** `chat.sh` lines 37–41  
**Decision:** This section (spawning `bashInput.sh` / `bashOutput.sh` in a terminal emulator) is to be deprecated.  
**Reason:** `-e` flag is xterm-specific; other emulators behave inconsistently. Failures are silent.  
**Action:** Remove the block. External shell windows should be launched manually or managed by a dedicated launcher/session script.  
**Priority:** Scheduled for removal.

## layerAssigner.py — rename to free "layer" term

**File:** `layerAssigner.py`  
**Decision:** Rename this module. The name implies it belongs to a "layer" abstraction, but the module is the pipeline hub — it watches channels, timestamps, tokenizes, and routes to the database. The term "layer" should be reserved for future use in a dedicated layer architecture.  
**Action:** Rename to something that reflects its actual role, e.g. `pipelineHub.py`, `dispatcher.py`, or `hub.py`. Update all imports and references accordingly.  
**Priority:** Before "layer" terminology is introduced elsewhere.

## run.sh `start()` — verify successful service startup (repo policy)

**File:** `run.sh` line 47–48  
**Issue:** `"$@" &` followed by `$!` records the PID unconditionally. A command that doesn't exist or crashes immediately is silently tracked as a live service. Cleanup suppresses the resulting kill errors, so a failed launch produces no visible feedback.  
**Policy:** All services launched via `start()` must be verified as alive within a short window (e.g. 500 ms) after launch. If a service is dead by then, `run.sh` should abort and report which service failed.  
**Implementation:** After `local pid=$!`, add a `sleep 0.2; kill -0 "$pid" 2>/dev/null || { echo "run.sh: $name failed to start" >&2; exit 1; }` check, or equivalent.  
**Priority:** Medium — apply as standard policy before adding new services.

## run.sh lines 104–108 — simultaneous service death reporting edge case

**File:** `run.sh` lines 104–108  
**Issue:** The dead-service detection loop finds and reports only the first dead PID. If two or more services die simultaneously, the log names only one — the others are silently cleaned up with no attribution.  
**Note:** `wait -n` unblocks on the first exit; the second death may occur within the same instant (e.g. cascading fault). The current loop breaks on first match.  
**Fix:** Remove the `break` and collect all dead PIDs before logging, or log all unnamed exits in `cleanup`.  
**Priority:** Low — edge case under normal operation.

## writerToDatabase.py — full file rewrite on every message (scalability)

**File:** `writerToDatabase.py` `record()`  
**Issue:** Every incoming message triggers `_load()` + `_write()` — a full read and rewrite of `chatLog`. Cost is O(n) in file size per message; will degrade as the log grows.  
**Brainstorm — alternatives to consider:**

- **Append-only log + separate weight index.** Append new records without rewriting old ones. Maintain a separate `weights` file (token → total) updated incrementally. Trade-off: old records in the log carry stale inline weights; weight truth lives in the index, not inline.
- **SQLite.** Replace the flat file with a SQLite database. Atomic updates, indexed lookups, no full-file rewrites. Trade-off: adds a dependency, loses human-readable plain-text format.
- **Periodic rewrite (lazy normalization).** Append new records inline with initial weights; defer full normalization to a background process or on-demand. Trade-off: inline weights are stale between normalizations — callers must query the index for current totals.
- **Compact on threshold.** Keep current scheme but trigger full rewrite only when record count or file size crosses a threshold; otherwise append. Trade-off: inline weights diverge between compactions.

**Priority:** Medium — address before sustained use produces a large chatLog.

## writerToDatabase.py — audit weight type consistency

**File:** `writerToDatabase.py`, `layerAssigner.py`, `inputThinker.py`  
**Issue:** `_parse_pairs` casts weights to `int` (line 33). A non-integer weight in the file (e.g. float written by a future thinker) raises an uncaught `ValueError`. It is not confirmed that all code paths producing weights guarantee integer output.  
**Action:** Audit every site that produces or writes a weight value — `inputThinker.weight()`, `_assign()` in `layerAssigner.py`, and `record()` in `writerToDatabase.py` — and enforce `int` explicitly at the point of write. Add a guard in `_parse_pairs` that catches `ValueError` and logs a clear error rather than crashing.  
**Priority:** Medium — a single malformed line makes the entire chatLog unreadable.
