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
├── layerAssigner.py          pipeline hub: timestamp + tokenize + weight + log
├── timeStamper.py            epoch-seconds helper
├── writerToDatabase.py       persists chatLog, accumulates inline weights
├── wordOccurrenceCounter.py   stub -- not implemented
├── bus.py                    shared file-based message bus helper
├── run.sh                    starts/supervises the three backend services
├── docs/                     empty, reserved for future docs
├── temp/                     runtime only -- created automatically, safe to delete
│   ├── input.events
│   ├── output.events
│   └── beat.signals
└── memory/                   persistent data -- created automatically
    └── chatLog
```

`temp/` and `memory/` don't need to exist beforehand: every script that touches
them creates them (and the files inside) on first use via `mkdir -p`/equivalent,
so deleting either folder is always safe — `temp/` is pure runtime state and
comes back empty; `memory/chatLog` comes back empty too, but since it's meant to
be durable, only delete it intentionally (e.g. to reset accumulated weights).

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
| `layerAssigner.py` | The pipeline hub. Watches both `input.events` and `output.events`; for each message it timestamps it, tokenizes the text, assigns weights (via `inputThinker` for input, default `1` for output), and hands the structured line to `writerToDatabase`. |
| `timeStamper.py` | Returns the current system time as integer epoch seconds. |
| `writerToDatabase.py` | Persists `memory/chatLog` and implements the weight-accumulation rule (see [chatLog format](#chatlog-format)). Run standalone to print accumulated weights per token, heaviest first. |
| `wordOccurrenceCounter.py` | **Not implemented.** Empty stub. |
| `bus.py` | Shared helper backing the file-based message bus: `publish(channel, *fields)` appends a TAB-separated line; `tail(channel)` is a polling generator that yields new lines as they appear. Backs onto `temp/`. |
| `run.sh` | Starts `layerAssigner.py`, `outputThinker.py`, and `beater.py` together and supervises them (see [Stopping](#stopping)). |
| `docs/` | Empty; reserved for future documentation. |

## chatLog format

`memory/chatLog` is plain text, one message per line, TAB-separated fields:

```
<direction>\t<media pairs>\t<timestamp pairs>\t<word pairs>
```

- **`<direction>`** — `input` or `output`. Plain tag, no weight.
- **`<media pairs>`**, **`<timestamp pairs>`**, **`<word pairs>`** — each is a
  space-separated *positional* sequence: even index = token, odd index = that
  token's weight (e.g. `bash illya 1 2` = tokens `bash`/`illya`, weights `1`/`2`).
  Positional pairs are used instead of a `token:weight` delimiter because a token
  can itself be punctuation or a number (the epoch timestamp), so no single
  separator character is guaranteed safe to embed.

Example, after `illya` types `hello world` and the program responds (both within
the same second, so the timestamp token itself accumulates to weight `2`):

```
input	bash 1 illya 1	1782648544 2	hello 1 world 1
output	program 1 jrvs 1	1782648544 2	беззмістовно 1
```

**Weight accumulation rule**: every time a token *form* (exact text match) is
recorded again anywhere in chatLog — as a word, as part of the media field, or as
part of the timestamp — its initial weight is added to that form's running total,
and **every** existing occurrence of that form in the file is rewritten to the new
total. So if `illya` appears 5 times across the whole log, all 5 occurrences show
the same (current) total weight, not their individual original weights. This is
implemented in `writerToDatabase.record()`.

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
python3 writerToDatabase.py   # token totals, heaviest first
cat memory/chatLog
```

## Known limitations

- `outputThinker.py`'s response policy is a temporary placeholder: it always
  replies `беззмістовно`, ignoring the actual input/beat content.
- `inputThinker.py`'s weighting policy always returns `1` — no real per-token
  weighting logic yet.
- `pythonOutput.py` and `wordOccurrenceCounter.py` are unimplemented stubs.
- `docs/` is empty.
