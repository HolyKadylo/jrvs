#!/bin/bash
# run.sh -- start all backend services and supervise them.
#
#   ./run.sh           # beater in QA mode (one response per input)
#   ./run.sh -b 3      # beater in timedWithParameter mode, every 3 seconds
#
# Starts hub (chatLog writer), outputThinker (responder) and beater,
# then blocks. Ctrl-C / kill -TERM / kill -INT on this script stops every
# service it started (SIGTERM, escalating to SIGKILL after a grace period) and
# exits. If a service dies on its own, the rest are stopped too and run.sh exits
# non-zero instead of hanging in wait.
#
# Feed input with bashInput.sh / chat.sh / pythonInput.py, or by appending a line
# to temp/input.events directly. temp/ holds only runtime-created files and is
# safe to delete; it's recreated automatically.
set -u

usage() {
    echo "usage: run.sh [-b SECONDS]" >&2
    echo "  -b SECONDS   run beater in timedWithParameter mode with this period" >&2
    echo "               (default: QA mode, one response per input)" >&2
}

BEATER_PERIOD=""
while getopts ":b:" opt; do
    case "$opt" in
        b) BEATER_PERIOD="$OPTARG" ;;
        :) echo "run.sh: -b requires a value (seconds)" >&2; usage; exit 2 ;;
        \?) echo "run.sh: unknown option -$OPTARG" >&2; usage; exit 2 ;;
    esac
done
if [ -n "$BEATER_PERIOD" ] && ! [[ "$BEATER_PERIOD" =~ ^[0-9]+$ ]]; then
    echo "run.sh: -b expects an integer number of seconds, got '$BEATER_PERIOD'" >&2
    exit 2
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
mkdir -p temp

pids=()
declare -A NAMES=()
cleaned_up=0

start() {
    local name="$1"; shift
    "$@" &
    local pid=$!
    pids+=("$pid")
    NAMES[$pid]="$name"
    echo "started $name (pid $pid)"
}

cleanup() {
    [ "$cleaned_up" -eq 1 ] && return
    cleaned_up=1
    [ "${#pids[@]}" -eq 0 ] && return

    echo "stopping services..."
    for pid in "${pids[@]}"; do
        kill -TERM "$pid" 2>/dev/null
    done

    # grace period for clean shutdown, then escalate to SIGKILL
    for _ in $(seq 1 30); do
        alive=0
        for pid in "${pids[@]}"; do
            kill -0 "$pid" 2>/dev/null && alive=1
        done
        [ "$alive" -eq 0 ] && break
        sleep 0.1
    done

    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  ${NAMES[$pid]:-pid $pid} did not stop in time; sending SIGKILL"
            kill -KILL "$pid" 2>/dev/null
        else
            echo "  ${NAMES[$pid]:-pid $pid} stopped"
        fi
    done
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

start hub python3 hub.py
start outputThinker python3 outputThinker.py
if [ -n "$BEATER_PERIOD" ]; then
    start beater python3 beater.py timedWithParameter "$BEATER_PERIOD"
else
    start beater python3 beater.py QA
fi

echo "pipeline running (pids: ${pids[*]}); Ctrl-C to stop"

# Block until any one service exits. A clean shutdown (Ctrl-C/TERM/INT) is
# handled by the trap above and exits before reaching this point's aftermath;
# reaching here means a service exited on its own -- treat it as a fault.
wait -n "${pids[@]}" 2>/dev/null
status=$?

dead_name="unknown service"
for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
        dead_name="${NAMES[$pid]:-pid $pid}"
        break
    fi
done

echo "run.sh: $dead_name exited unexpectedly (status $status); stopping the rest"
cleanup
exit 1
