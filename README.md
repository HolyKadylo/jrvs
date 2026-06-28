# jrvs

A small multi-process NLP text processor. Input arrives from a **bash** channel
(terminal windows) and a **Python** channel (a Tkinter window); every message is
timestamped, tokenized, weight-tagged, and appended to a single persistent
`memory/chatLog`. Repeated word-forms accumulate weight over time. A *beater*
drives a *thinker* that responds back to the user.

Target runtime: **WSL / Linux** (real bash shells, `xterm`/`$TERMINAL`, Tkinter).

## Storage layout

- **`temp/`** — runtime-created message-bus channel files only. Safe to delete at
  any time; every script recreates it (and its files) automatically at startup.
- **`memory/`** — persistent data. Currently just `chatLog`, which is never
  auto-deleted; the directory is recreated automatically if missing.

## Components

| File | Role |
|---|---|
| `chat.sh` | Main bash-channel controller. Prompts as `<linux-username>> `; forwards what you type to the input channel. Shows program responses in **green**, prefixed `<project-folder>> `. Pops the input/output windows if a terminal emulator is available. |
| `bashInput.sh` | Reads lines in a bash shell → publishes to `temp/input.events`. |
| `bashOutput.sh` | The bash output window: follows `temp/output.events`, printed as `<project-folder>> <response>`. |
| `pythonInput.py` | Tkinter window: big text box + **Send** button → `temp/input.events`. |
| `pythonOutput.py` | TODO stub (intended python-channel output window). |
| `beater.py` | Emits beats: `QA` (one per input) or `timedWithParameter <secs>`. |
| `outputThinker.py` | Composes a response per beat → `temp/output.events`. |
| `inputThinker.py` | Weight-assignment policy that directs `layerAssigner` (default 1). |
| `layerAssigner.py` | Pipeline hub: timestamp + tokenize + weight, then write chatLog. |
| `timeStamper.py` | System time in epoch seconds. |
| `writerToDatabase.py` | Persists `memory/chatLog` and accumulates inline word weights. |
| `bus.py` | Shared file-based message bus helper (backs onto `temp/`). |
| `run.sh` | Launches the pipeline headless for testing. |

The folder name used for the `<project-folder>>` output prefix, and the Linux
username used for the chat prompt, are both picked once at script startup.

## Data contracts

**Message bus** — append-only files under `temp/`, one TAB-separated message per line:

| Channel | Message |
|---|---|
| `temp/input.events` | `<media>\t<text>` |
| `temp/output.events` | `<media>\t<text>` |
| `temp/beat.signals` | `<source>\t<epoch>` |

`<media>` describes the channel and login state, e.g. `bash anonymous` or
`python anonymous` (no auth yet, so login state defaults to `anonymous`).

**`memory/chatLog`** — one message per line:

```
<direction>\t<media pairs>\t<timestamp pairs>\t<word pairs>
```

`<direction>` is `input` or `output` and has no weight. Each other field is a
space-separated *positional* sequence: even index = token, odd index = weight.
When a token form is recorded again, its weight is added to the running total and
**every** occurrence of that form in `memory/chatLog` is rewritten to the new total.

## Running it

```sh
./run.sh            # start layerAssigner + outputThinker + beater (QA mode)
./chat.sh           # type here; responses come back in green
python3 pythonInput.py   # or send text from the Tkinter window
```

Inspect the accumulated weights at any time:

```sh
python3 writerToDatabase.py   # token totals, heaviest first
cat memory/chatLog
```
