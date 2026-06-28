#!/bin/bash
# bashOutput: the program's output window for the bash channel.
# Follows the "output.events" bus channel and prints each program response.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUS="$DIR/bus"
mkdir -p "$BUS"
touch "$BUS/output.events"

tail -n0 -F "$BUS/output.events" | while IFS=$'\t' read -r media text; do
    printf '%s\n' "$text"
done
