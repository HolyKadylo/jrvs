#!/usr/bin/env python3
"""beater: emits beat signals to outputThinker.

Modes:
  QA                        -- emit one beat per input event (from any input channel)
  timedWithParameter <secs> -- emit a beat every <secs> seconds

Each beat is a line on the ``beat.signals`` bus channel: ``<source>\t<epoch>``.
"""
import sys
import time

import bus
import timeStamper


def run_qa():
    for _ in bus.tail("input.events"):
        bus.publish("beat.signals", "QA", timeStamper.now_epoch())


def run_timed(seconds):
    while True:
        bus.publish("beat.signals", "timed", timeStamper.now_epoch())
        time.sleep(seconds)


def main(argv):
    if len(argv) >= 1 and argv[0] == "QA":
        run_qa()
    elif len(argv) >= 2 and argv[0] == "timedWithParameter":
        run_timed(float(argv[1]))
    else:
        print(
            "usage: beater.py QA | beater.py timedWithParameter <seconds>",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
