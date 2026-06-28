#!/bin/bash
# bashOutput: the program's output window for the bash channel.
# Follows the "output.events" bus channel and prints each program response.
# temp/ holds only runtime-created files; it's recreated automatically if missing.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP="$DIR/temp"
mkdir -p "$TEMP"
touch "$TEMP/output.events"

NAME="$(basename "$DIR")"

tail -n0 -F "$TEMP/output.events" | while IFS=$'\t' read -r media text; do
    printf '%s> %s\n' "$NAME" "$text"
done
