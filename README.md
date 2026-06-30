# jrvs

A small multi-process NLP text processor. Input arrives from a **bash** channel
(terminal windows) and a **Python** channel (a Tkinter window); every message is
timestamped, tokenized, weight-tagged, and appended to a single persistent
`memory/chatLog`. Repeated word-forms accumulate weight over time. A *beater*
drives a *thinker* that responds back to the user.

Target runtime: **WSL / Linux** (real bash shells, `xterm`/`$TERMINAL`, Tkinter,
`python3`). All inter-process communication goes through a small file-based
message bus under `temp/` — no sockets, no FIFOs.

## Folder structure

```
jrvs/
├── README.md
├── .gitignore
├── chat.sh                  main bash-channel controller
├── bashInput.sh              dedicated bash-channel input window
├── bashOutput.sh             dedicated bash-channel output window
├── pythonInput.py            Tkinter input window
├── pythonOutput.py           Tkinter output window -- TODO, not implemented
├── beater.py                 beat scheduler (QA / timedWithParameter)
├── outputThinker.py          composes a response per beat
├── inputThinker.py           word/punctuation weight policy
├── hub.py                    pipeline hub: timestamp + tokenize + weight + log
├── layerAssigner.py          compatibility shim → hub.py (deprecated)
├── timeStamper.py            epoch-seconds helper
├── db.py                     SQLite backend: volumes, weights, record()
├── writerToDatabase.py       facade over db.py (public interface unchanged)
├── wordOccurrenceCounter.py   stub -- not implemented
├── bus.py                    shared file-based message bus helper
├── run.sh                    starts/supervises the three backend services
├── docs/                     empty, reserved for future docs
├── temp/                     runtime only -- created automatically, safe to delete
│   ├── input.events
│   ├── output.events
│   └── beat.signals
├── tools/
│   ├── exportChatlog.py      converter: SQLite → legacy chatLog text format
│   └── dbMaintain.py         maintenance: integrity, rebuild-weights, vacuum, backup, stats, prune
└── memory/                   persistent data -- created automatically
    ├── weights.db            global token weights + volume manifest
    └── volumes/
        └── chatLog.NNNN.db   per-volume messages and occurrences (≤ 1 GB each)
```

`temp/` and `memory/` don't need to exist beforehand: every script that touches
them creates them on first use, so deleting either folder is always safe —
`temp/` is pure runtime state and comes back empty; `memory/` holds the SQLite
databases and comes back as an empty store, but since it's meant to be durable,
only delete it intentionally (e.g. to reset accumulated weights).

## File purposes

| File | Purpose |
|---|---|
| `chat.sh` | Main bash-channel controller. Prompts as `<linux-username>> `, forwards typed lines to `temp/input.events` labelled `bash <username>`. Echoes program responses in **green**, prefixed `<project-folder>> `. Optionally pops `bashInput.sh`/`bashOutput.sh` in their own terminal windows if one is available. |
| `bashInput.sh` | Standalone input window: reads lines, publishes each to `temp/input.events` labelled `bash <username>`. |
| `bashOutput.sh` | Standalone output window: follows `temp/output.events`, prints each response as `<project-folder>> <response>`. |
| `pythonInput.py` | Tkinter window: multi-line text box + **Send** button, publishes to `temp/input.events` labelled `python anonymous`. |
| `pythonOutput.py` | **Not implemented.** TODO stub describing the intended Tkinter output window for the python channel. |
| `beater.py` | Emits beats on `temp/beat.signals`. Two modes: `QA` (one beat per input event) or `timedWithParameter <seconds>` (one beat every N seconds). Selected via `run.sh -b`. |
| `outputThinker.py` | Watches beats, composes a response, publishes it to `temp/output.events` labelled `program <project-folder>`. Currently a temporary fixed placeholder — see [Known limitations](#known-limitations). |
| `inputThinker.py` | Assigns the initial weight for each input token (word/punctuation/media/timestamp). Currently always returns `1` — a policy hook for future logic. |
| `hub.py` | The pipeline hub (renamed from `layerAssigner.py`). Watches both `input.events` and `output.events`; for each message it timestamps it, tokenizes the text, assigns weights (via `inputThinker` for input, default `1` for output), and hands the structured line to `writerToDatabase`. |
| `layerAssigner.py` | Compatibility shim — re-exports `hub.py`. Deprecated; use `hub.py` directly. |
| `timeStamper.py` | Returns the current system time as integer epoch seconds. |
| `db.py` | SQLite backend. Implements the volume architecture (`memory/weights.db` + `memory/volumes/chatLog.NNNN.db`), the `record()` write path, and the global token-weight cache. Write cost is O(k log N) per message. |
| `writerToDatabase.py` | Thin facade over `db.py`. Preserves the `record()` / `main()` interface for existing callers. Run standalone to print accumulated weights per token, heaviest first. |
| `tools/exportChatlog.py` | Converter: reads the SQLite store and emits the legacy TAB-separated `chatLog` text format to stdout or a file. Supports range, direction, token filter, format, and `--follow` options. |
| `tools/dbMaintain.py` | Maintenance utility: `integrity`, `rebuild-weights`, `vacuum`, `backup`, `stats`, `prune` subcommands. |
| `wordOccurrenceCounter.py` | **Not implemented.** Empty stub. |
| `bus.py` | Shared helper backing the file-based message bus: `publish(channel, *fields)` appends a TAB-separated line; `tail(channel)` is a polling generator that yields new lines as they appear. Backs onto `temp/`. |
| `run.sh` | Starts `layerAssigner.py`, `outputThinker.py`, and `beater.py` together and supervises them (see [Stopping](#stopping)). |
| `docs/` | Empty; reserved for future documentation. |

## Database format

Persistent memory lives in two SQLite files under `memory/`:

**`memory/weights.db`** — global tables:
- `token_weights(form, total_weight)` — one row per unique token form; `total_weight` is the sum of all initial weights contributed by that form across all history.
- `volume_manifest(volume_n, seq_min, seq_max, epoch_min, epoch_max, status, byte_size)` — one row per volume file; `status` is `active` or `sealed`.
- `meta(key, value)` — `schema_version`, `created_at`, `next_seq`.

**`memory/volumes/chatLog.NNNN.db`** — per-volume tables (one file per ≤ 1 GB slice):
- `messages(id, seq, direction, created_epoch)` — one row per message; `seq` is globally monotonic.
- `occurrences(id, message_id, field, position, form, initial_weight)` — one row per token occurrence; `field`: 0 = media, 1 = timestamp, 2 = words; `initial_weight` is the per-occurrence delta, not the display total.

**Weight accumulation rule**: every time a token *form* is recorded, its `initial_weight` is added to `token_weights.total_weight` for that form. The display weight for any occurrence is always the current `total_weight` — identical to the legacy "all occurrences of a form share one total" invariant, achieved here without rewriting history. Write cost is O(k log N) for a message of k tokens (down from O(file size) in the flat-file implementation).

**Legacy text format**: `tools/exportChatlog.py` reproduces the original TAB-separated format on demand:

```
<direction>\t<media pairs>\t<timestamp pairs>\t<word pairs>
```

Each pair field is a space-separated positional sequence (even index = token, odd index = current total weight). Example:

```
input	bash 1 illya 1	1782648544 2	hello 1 world 1
output	program 1 jrvs 1	1782648544 2	беззмістовно 1
```

## Starting

```sh
./run.sh              # starts layerAssigner + outputThinker + beater (QA mode:
                       # one response per input)
./run.sh -b 5         # same, but beater fires a beat every 5 seconds instead
                       # (timedWithParameter mode) regardless of input
```

Then, in another terminal, feed it input through any one (or more) of:

```sh
./chat.sh                  # main transcript: type, see responses in green
./bashInput.sh              # standalone input-only window
python3 pythonInput.py     # Tkinter window with a Send button
```

`chat.sh` will also try to pop `bashInput.sh`/`bashOutput.sh` as separate
terminal windows automatically if a terminal emulator (`$TERMINAL`, default
`xterm`) is available; otherwise everything just works headless in one terminal.

You can also bypass the UI entirely for testing, by appending directly:

```sh
echo -e "bash anonymous\thello there" >> temp/input.events
```

## Stopping

- **`run.sh`**: Ctrl-C, or `kill -TERM`/`kill -INT` on its process. It stops all
  three services it started (SIGTERM first, escalating to SIGKILL after a ~3s
  grace period if one doesn't exit) and exits. If a service dies on its own
  mid-run, `run.sh` notices immediately, stops the remaining ones, and exits with
  status `1` instead of hanging.
- **`chat.sh`**: Ctrl-C, or Ctrl-D to end the read loop.
- **`bashInput.sh` / `bashOutput.sh`**: Ctrl-C, or close the window.
- **`pythonInput.py`**: close the Tkinter window (or Ctrl-C if run in foreground).

Inspect accumulated weights at any time, even while everything is running:

```sh
python3 writerToDatabase.py        # token totals, heaviest first
python3 tools/exportChatlog.py     # full history in legacy TAB-separated format
python3 tools/dbMaintain.py stats  # database size, row counts, volume listing
```

## Known limitations

- `outputThinker.py`'s response policy is a temporary placeholder: it always
  replies `беззмістовно`, ignoring the actual input/beat content.
- `inputThinker.py`'s weighting policy always returns `1` — no real per-token
  weighting logic yet.
- `pythonOutput.py` and `wordOccurrenceCounter.py` are unimplemented stubs.
- `docs/` is empty.
