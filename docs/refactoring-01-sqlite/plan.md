# Plan — Refactoring 01: Move persistent memory to SQLite

Execute the phases in order. Each task lists files, steps, and an acceptance
check. Do not start a task before the previous one passes its check. Rationale
and data model are in `purpose.md`.

## Phase 0 — Baseline and decisions

1. Freeze the data model from `purpose.md`: `messages`, `occurrences`,
   `token_weights`, `meta`.
2. Confirm cutover policy: existing `memory/chatLog` is dropped; no migration.
3. Fix file layout: Phases 1–4 use one active database `memory/chatLog.db`;
   Phase 5 generalises it to volumes.

Acceptance: `purpose.md` committed; schema fixed in writing.

## Phase 1 — SQLite storage module (drop-in for `writerToDatabase`)

Goal: replace the flat-file internals while keeping `record()`'s public
signature so `layerAssigner` is unchanged.

1. Add `db.py`: `open_connection(path)`, `init_schema()` (CREATE TABLE IF NOT
   EXISTS + indices; `PRAGMA journal_mode=WAL`, `foreign_keys=ON`), seed `meta`
   (`schema_version=1`).
2. Implement `record(direction, media_pairs, ts_pairs, word_pairs)` in one
   transaction: insert the `messages` row (`seq` = next; `created_epoch` from the
   timestamp token); for each field/position/token insert an `occurrences` row
   with `initial_weight=w` and upsert `token_weights` with
   `total_weight = total_weight + w`; read back current totals and return the
   line in the same `[direction, media, ts, words]` shape with weights = totals
   (matching the legacy return value).
3. Reimplement the standalone view (legacy `main()`): `SELECT form, total_weight
   FROM token_weights ORDER BY total_weight DESC, form`.
4. Repoint `writerToDatabase.py` to delegate to `db.py` (keep the `record` and
   `main` names) so `layerAssigner`'s import stays valid.
5. Enforce integer weights at the point of write and guard parsing against a
   non-integer weight, auditing every producer (`inputThinker.weight`,
   `layerAssigner._assign`, the store). Carried from TODO: a single malformed
   weight previously made the whole flat `chatLog` unreadable.

Acceptance: a scripted sequence of `record()` calls yields `token_weights` equal
to the legacy accumulation for the same inputs; `main()` prints identical
token/total ordering; prior rows are not rewritten (verify by row counts).

## Phase 2 — Cutover (drop memory, switch writer)

1. Stop services (`run.sh`).
2. Delete `memory/chatLog` and `memory/chatLog.tmp`. Update `.gitignore`: replace
   the `memory/chatLog*` entries with `memory/*.db`, `memory/*.db-wal`,
   `memory/*.db-shm`.
3. Point persistence at `memory/chatLog.db`; `init_schema` on first use
   (`mkdir -p memory`).
4. Update the README "chatLog format" section to describe the database and name
   the converter (Phase 3) as the way to obtain the legacy text format.
5. Rename `layerAssigner.py` to reflect its role (e.g. `hub.py` / `dispatcher.py`)
   and update all imports and references (`run.sh`, README). Carried from TODO:
   free the "layer" term before it is reused for a real layer architecture. This
   cutover already edits those references.

Acceptance: `./run.sh` plus a few input events produces rows in
`memory/chatLog.db`; no flat `chatLog` file is recreated; `PRAGMA
integrity_check` is `ok`.

## Phase 3 — Converter utility: SQLite → legacy `chatLog` format

Goal: reproduce the exact legacy line format on demand. Build v1 now; the later
versions are the planned growth of this tool.

1. **v1 — exact reproduction** (`tools/exportChatlog.py`): for each message in
   `seq` order, join `occurrences` → `token_weights` and emit
   `<direction>\t<media pairs>\t<ts pairs>\t<word pairs>` using current totals, to
   stdout or a file. Output must match the README format byte-for-byte for an
   equivalent history.
2. **v2 — range/selection**: `--from`/`--to` by `seq` or epoch; `--direction
   input|output`.
3. **v3 — volume-aware**: read across volume files in order (depends on Phase 5).
4. **v4 — filter/projection**: `--token FORM`, `--limit`, ordering options.
5. **v5 — formats and follow**: `--format chatlog|jsonl|csv` (default `chatlog`);
   `--follow` to stream new records; optional reverse import (chatlog → DB) for
   round-trip testing.

Acceptance (v1): export of a known database equals a hand-verified expected
`chatLog`; re-parsing the export with the legacy `_parse_pairs` succeeds.

## Phase 4 — Maintenance utilities (`tools/dbMaintain.py`)

1. `integrity` — `PRAGMA quick_check` / `integrity_check`.
2. `rebuild-weights` — recompute `token_weights` from `SUM(occurrences.initial_
   weight) GROUP BY form`; compare to the cache; repair and report drift.
3. `vacuum` — `VACUUM` (needs up to 2× file size free) and/or set `auto_vacuum`;
   `--into PATH` for a compacted `VACUUM INTO` copy.
4. `backup` — consistent snapshot via `VACUUM INTO` (or the backup API).
5. `stats` — database size, row counts, heaviest tokens, volume listing.
6. `prune` — retention by message age or by volume; document the
   weight-consistency decision (pruned occurrences keep their weight contribution
   as all-time totals unless `rebuild-weights` is run after pruning).

Acceptance: each subcommand runs on a populated database; `integrity` passes;
`rebuild-weights` reports zero drift on a clean database.

## Phase 5 — Log volumes (1 GB rotation)

1. Introduce `memory/volumes/chatLog.NNNN.db` for message/occurrence data and
   `memory/weights.db` for the global `token_weights`; the writer `ATTACH`-es
   `weights.db`.
2. Add a volume manifest (table or `memory/volumes/manifest`): volume id, `seq`
   range, epoch range, status (`active`/`sealed`), byte size.
3. On each commit (or every N commits) check the active volume's size; at ≥ 1 GB
   seal it (mark `sealed`/read-only) and open the next volume; weights continue
   in the global `weights.db`.
4. Make the converter (3.3) and maintenance (4.x) iterate volumes in order;
   `VACUUM`/backup operate per sealed volume plus `weights.db`.

Acceptance: with a lowered test threshold, sustained writes roll to a second
volume; converter output is continuous across volumes; `token_weights` is
identical whether the history is in one volume or many.

## Phase 6 — (Optional, future) Multi-host engine

1. Define a `Store` interface (`record`, `totals`, iterate messages,
   `seal`/rotate, maintenance) with SQLite as the default implementation; isolate
   SQLite-only code (`PRAGMA`, `ATTACH`, `VACUUM`, volumes, `_lock`).
2. Provide a PostgreSQL implementation for concurrent multi-host writers;
   server-side concurrency removes the in-process writer lock and file-volume
   rotation.
3. Keep SQL portable; document the switch criteria (more than one writing host,
   write concurrency beyond one writer, content nearing the TB range).

Acceptance: the interface is defined and exercised by the SQLite backend; the
Postgres path is documented; the default SQLite behaviour is unchanged.

## Phase 7 — Verification

1. End-to-end: run the pipeline, feed inputs, export via the converter, diff
   against the expected legacy format.
2. `integrity` passes and `rebuild-weights` drift = 0.
3. Volume rollover test (Phase 5).
4. Write-cost check: per-message time stays roughly constant as the database
   grows, in contrast to the legacy O(file size) rewrite.

Acceptance: all checks pass; README updated.

## Carried-over items from TODO.md

Consolidated here when `TODO.md` was removed.

Addressed by this refactor:

- **writerToDatabase — full-file rewrite on every message (scalability).** The
  reason for this refactor; resolved by Phases 1 and 5. Priority: Medium.
- **writerToDatabase — weight-type consistency.** Enforce `int` at write, guard
  parsing. Scheduled in Phase 1, task 5. Priority: Medium.
- **layerAssigner.py — rename to free the "layer" term** (e.g. `hub.py` /
  `dispatcher.py`); update imports/`run.sh`/README. Scheduled in Phase 2, task 5.

Out of scope for this refactor — preserved for later:

- **bus.py — concurrent write safety** (lines 36–37): the append write has no
  file locking; simultaneous multi-process writes can interleave mid-line and
  corrupt TAB records. Fix: wrap with `fcntl.flock(LOCK_EX/LOCK_UN)` or an atomic
  write. Priority: Low if single-writer; High if concurrency is introduced —
  relevant before Phase 6 (multi-host).
- **bus.py — `tail()` unclosed handle** (line 48): `open(target, "a").close()`
  relies on CPython refcounting. Fix: `with open(target, "a"): pass`.
  Priority: Low.
- **bus.py — `tail()` no exit condition; session modes:** add Infinite vs Timed
  modes; timed termination must also stop dependent scripts (sentinel `control`
  channel, PID file + SIGTERM, or a `temp/stop` flag file). Priority: Medium —
  before any unattended or scheduled use.
- **beater.py — argv validation** (line 32): `float(argv[1])` is unvalidated —
  non-numeric crashes, `0` busy-loops, negative raises. Fix: try/except, reject
  `<= 0`, `sys.exit(2)`. Priority: Low manual / Medium automated.
- **chat.sh — terminal-emulator launch** (lines 37–41): deprecate; `-e` is
  xterm-specific with silent failures. Action: remove the block; launch external
  windows manually or via a dedicated launcher. Priority: scheduled for removal.
- **run.sh — `start()` startup verification** (lines 47–48): the PID is recorded
  unconditionally, so a service that dies on launch is tracked as live. Fix:
  after `local pid=$!` add `sleep 0.2; kill -0 "$pid" 2>/dev/null || { echo
  "run.sh: $name failed to start" >&2; exit 1; }`. Priority: Medium.
- **run.sh — simultaneous death reporting** (lines 104–108): only the first dead
  PID is reported. Fix: drop the `break`, collect all dead PIDs before logging.
  Priority: Low.

## References

- C:\Users\ptigo\jrvs\writerToDatabase.py, writerToDatabase.py (record/_load/_totals/_write), n.d., jrvs project (local)
- C:\Users\ptigo\jrvs\layerAssigner.py, layerAssigner.py (process/_lock), n.d., jrvs project (local)
- C:\Users\ptigo\jrvs\README.md, README.md (chatLog format), n.d., jrvs project (local)
- https://www.sqlite.org/whentouse.html, Appropriate Uses For SQLite, 2025, SQLite Development Team (Hipp, D.R. et al.)
- https://www.sqlite.org/limits.html, Implementation Limits For SQLite, 2026, SQLite Development Team (Hipp, D.R. et al.)
- https://www.sqlite.org/lang_vacuum.html, VACUUM, 2025, SQLite Development Team (Hipp, D.R. et al.)
