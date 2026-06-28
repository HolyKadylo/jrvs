#!/bin/bash
# chat.sh -- main controller for the bash channel.
#
# Whatever you type here is transferred to the bash input channel (published to
# temp/input.events, the same channel bashInput.sh feeds). Program responses that
# arrive on temp/output.events are echoed back here in green, prefixed with the
# project folder name. temp/ holds only runtime-created files and is safe to
# delete; it's recreated automatically.
#
# If a terminal emulator is available it also opens the dedicated bashInput and
# bashOutput windows; otherwise it runs fine headless (just this transcript).
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP="$DIR/temp"
mkdir -p "$TEMP"
touch "$TEMP/input.events" "$TEMP/output.events" "$TEMP/beat.signals"

NAME="$(basename "$DIR")"
USERNAME="$(whoami)"

GREEN=$'\033[32m'
RESET=$'\033[0m'

# Echo program responses (output.events) into this transcript, in green.
# Responses can arrive while the user's prompt is sitting on screen waiting for
# input; clear that line first so the response always lands on its own line, then
# reprint the prompt so it's never silently lost underneath the response text.
( tail -n0 -F "$TEMP/output.events" | while IFS=$'\t' read -r media text; do
      printf '\r\033[K%s%s> %s%s\n' "$GREEN" "$NAME" "$text" "$RESET"
      printf '%s> ' "$USERNAME"
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
while IFS= read -r -p "$USERNAME> " line; do
    line=${line//$'\t'/ }
    printf '%s\t%s\n' "bash $USERNAME" "$line" >> "$TEMP/input.events"
done
