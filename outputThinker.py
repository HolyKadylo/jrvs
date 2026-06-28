#!/usr/bin/env python3
"""outputThinker: composes program responses, one per beat from beater.

Watches the ``beat.signals`` channel; for each beat it builds a response and
publishes it to ``output.events``, where the output windows (and layerAssigner,
for chatLog) pick it up.
"""
import os

import bus
import timeStamper

# Picked once at startup: the project folder name (chat.sh lives alongside this
# script), used to label program output the same way bash input is labelled by
# the Linux username.
PROJECT_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
MEDIA = f"program {PROJECT_NAME}"


def respond(source, epoch):
    # TODO: temporary placeholder -- ignores input/beat entirely, always answers
    # the same fixed string regardless of source or content.
    return "беззмістовно"


def main():
    for fields in bus.tail("beat.signals"):
        source = fields[0] if fields else "?"
        epoch = fields[1] if len(fields) > 1 else str(timeStamper.now_epoch())
        bus.publish("output.events", MEDIA, respond(source, epoch))


if __name__ == "__main__":
    main()
