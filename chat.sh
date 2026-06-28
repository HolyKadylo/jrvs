#!/bin/bash
# chat.sh -- main controller for the bash channel.
#
# Whatever you type here is transferred to the bash input channel (published to
# bus/input.events, the same channel bashInput.sh feeds). Program responses that
# arrive on bus/output.events are echoed back here in green.
#
# If a terminal emulator is available it also opens the dedicated bashInput and
# bashOutput windows; otherwise it runs fine headless (just this transcript).
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUS="$DIR/bus"
mkdir -p "$BUS"
touch "$BUS/input.events" "$BUS/output.events" "$BUS/beat.signals"

GREEN=$'\033[32m'
RESET=$'\033[0m'

# Echo program responses (output.events) into this transcript, in green.
( tail -n0 -F "$BUS/output.events" | while IFS=$'\t' read -r media text; do
      printf '%s%s%s\n' "$GREEN" "$text" "$RESET"
  done ) &
TAIL_PID=$!
trap 'kill "$TAIL_PID" 2>/dev/null' EXIT INT TERM

# Optionally pop the dedicated input/output shells in their own windows.
TERM_EMU="${TERMINAL:-xterm}"
if command -v "$TERM_EMU" >/dev/null 2>&1; then
    "$TERM_EMU" -e "$DIR/bashOutput.sh" &
    "$TERM_EMU" -e "$DIR/bashInput.sh" &
fi

# Main transcript: read user lines and forward them to the bash input channel.
while IFS= read -r -p 'you> ' line; do
    line=${line//$'\t'/ }
    printf '%s\t%s\n' 'bash anonymous' "$line" >> "$BUS/input.events"
done
