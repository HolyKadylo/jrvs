#!/bin/bash
# run.sh -- launch the jrvs pipeline headless for testing.
#
#   ./run.sh           # beater in QA mode (one response per input)
#   ./run.sh timed 3   # beater in timedWithParameter mode, every 3 seconds
#
# Starts layerAssigner (chatLog writer), outputThinker (responder) and beater.
# Feed input with bashInput.sh / chat.sh / pythonInput.py, or by appending a line
# to bus/input.events directly. Ctrl-C stops everything.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
mkdir -p bus

pids=()
python3 layerAssigner.py & pids+=($!)
python3 outputThinker.py & pids+=($!)
if [ "${1:-}" = "timed" ]; then
    python3 beater.py timedWithParameter "${2:-3}" & pids+=($!)
else
    python3 beater.py QA & pids+=($!)
fi

trap 'kill "${pids[@]}" 2>/dev/null' EXIT INT TERM
echo "pipeline running (pids: ${pids[*]}); Ctrl-C to stop"
wait
