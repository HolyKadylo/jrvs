# jrvs

A small multi-process NLP text processor. Input arrives from a **bash** channel
(terminal windows) and a **Python** channel (a Tkinter window); every message is
timestamped, tokenized, weight-tagged, and appended to a single `chatLog`. Repeated
word-forms accumulate weight over time. A *beater* drives a *thinker* that responds
back to the user.

Target runtime: **WSL / Linux** (real bash shells, `xterm`/`$TERMINAL`, Tkinter).

## Components

| File | Role |
|---|---|
| `chat.sh` | Main bash-channel controller. Forwards what you type to the input channel; shows program responses in **green**. Pops the input/output windows if a terminal emulator is available. |
| `bashInput.sh` | Reads lines in a bash shell → publishes to `bus/input.events`. |
| `bashOutput.sh` | The bash output window: follows `bus/output.events`. |
| `pythonInput.py` | Tkinter window: big text box + **Send** button → `bus/input.events`. |
| `pythonOutput.py` | TODO stub (intended python-channel output window). |
| `beater.py` | Emits beats: `QA` (one per input) or `timedWithParameter <secs>`. |
| `outputThinker.py` | Composes a response per beat → `bus/output.events`. |
| `inputThinker.py` | Weight-assignment policy that directs `layerAssigner` (default 1). |
| `layerAssigner.py` | Pipeline hub: timestamp + tokenize + weight, then write chatLog. |
| `timeStamper.py` | System time in epoch seconds. |
| `writerToDatabase.py` | Persists chatLog and accumulates inline word weights. |
| `bus.py` | Shared file-based message bus helper. |
| `run.sh` | Launches the pipeline headless for testing. |

## Data contracts

**Message bus** — append-only files under `bus/`, one TAB-separated message per line:

| Channel | Message |
|---|---|
| `bus/input.events` | `<media>\t<text>` |
| `bus/output.events` | `<media>\t<text>` |
| `bus/beat.signals` | `<source>\t<epoch>` |

`<media>` describes the channel and login state, e.g. `bash anonymous` or
`python anonymous` (no auth yet, so login state defaults to `anonymous`).

**chatLog** — one message per line:

```
<direction>\t<media pairs>\t<timestamp pairs>\t<word pairs>
```

`<direction>` is `input` or `output` and has no weight. Each other field is a
space-separated *positional* sequence: even index = token, odd index = weight.
When a token form is recorded again, its weight is added to the running total and
**every** occurrence of that form in `chatLog` is rewritten to the new total.

## Running it

```sh
./run.sh            # start layerAssigner + outputThinker + beater (QA mode)
./chat.sh           # type here; responses come back in green
python3 pythonInput.py   # or send text from the Tkinter window
```

Inspect the accumulated weights at any time:

```sh
python3 writerToDatabase.py   # token totals, heaviest first
cat chatLog
```
