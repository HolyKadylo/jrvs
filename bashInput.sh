#!/bin/bash
# bashInput: read user input in a bash shell and publish it to the bus.
# Each line becomes an "input.events" message with media "bash anonymous".
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUS="$DIR/bus"
mkdir -p "$BUS"

while IFS= read -r -p '> ' line; do
    line=${line//$'\t'/ }          # keep the TAB field-delimiter invariant
    printf '%s\t%s\n' 'bash anonymous' "$line" >> "$BUS/input.events"
done
