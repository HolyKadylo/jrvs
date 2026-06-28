#!/usr/bin/env python3
"""outputThinker: composes program responses, one per beat from beater.

Watches the ``beat.signals`` channel; for each beat it builds a response and
publishes it to ``output.events``, where the output windows (and layerAssigner,
for chatLog) pick it up.
"""
import bus
import timeStamper

MEDIA = "program anonymous"


def respond(source, epoch):
    # TODO: real response policy. For now emit a placeholder acknowledgement.
    return f"(response to {source} beat @ {epoch})"


def main():
    for fields in bus.tail("beat.signals"):
        source = fields[0] if fields else "?"
        epoch = fields[1] if len(fields) > 1 else str(timeStamper.now_epoch())
        bus.publish("output.events", MEDIA, respond(source, epoch))


if __name__ == "__main__":
    main()
