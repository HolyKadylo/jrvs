#!/bin/bash
# bashInput: read user input in a bash shell and publish it to the bus.
# Each line becomes an "input.events" message with media "bash <username>".
# temp/ holds only runtime-created files; it's recreated automatically if missing.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP="$DIR/temp"
mkdir -p "$TEMP"
USERNAME="$(whoami)"

while IFS= read -r -p '> ' line; do
    line=${line//$'\t'/ }          # keep the TAB field-delimiter invariant
    printf '%s\t%s\n' "bash $USERNAME" "$line" >> "$TEMP/input.events"
done
