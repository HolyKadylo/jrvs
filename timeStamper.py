#!/usr/bin/env python3
"""timeStamper: system time in epoch mode."""
import time


def now_epoch():
    """Return the current system time as integer seconds since the Unix epoch."""
    return int(time.time())


if __name__ == "__main__":
    print(now_epoch())
