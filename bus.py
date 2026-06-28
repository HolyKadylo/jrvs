#!/usr/bin/env python3
"""File-based message bus for jrvs.

All inter-process communication goes through append-only text files under the
``temp/`` directory next to this module. ``temp/`` holds nothing but these
runtime-created channel files -- it's safe to delete at any time; the next
publish/tail call recreates it. Each line is one message whose fields are
TAB-separated. Producers call :func:`publish`; consumers iterate :func:`tail`.

Field values are sanitised so they can never contain a TAB or newline, which keeps
the one-message-per-line / TAB-delimited invariant intact regardless of user input.
"""
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BUS_DIR = os.path.join(ROOT, "temp")


def ensure_bus():
    os.makedirs(BUS_DIR, exist_ok=True)


def path(channel):
    return os.path.join(BUS_DIR, channel)


def _clean(value):
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def publish(channel, *fields):
    """Append one TAB-separated message to ``temp/<channel>``."""
    ensure_bus()
    line = "\t".join(_clean(f) for f in fields)
    with open(path(channel), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def tail(channel, from_start=False, poll=0.2):
    """Yield messages (lists of TAB-split fields) as they are appended.

    Blocks between reads, polling every ``poll`` seconds. Starts at the end of the
    file unless ``from_start`` is set, so a fresh consumer only sees new messages.
    """
    ensure_bus()
    target = path(channel)
    open(target, "a", encoding="utf-8").close()  # make sure it exists
    with open(target, "r", encoding="utf-8") as fh:
        if not from_start:
            fh.seek(0, os.SEEK_END)
        pending = ""
        while True:
            chunk = fh.readline()
            if chunk:
                if chunk.endswith("\n"):
                    full = pending + chunk[:-1]
                    pending = ""
                    yield full.split("\t")
                else:
                    pending += chunk  # partial line, wait for the rest
            else:
                time.sleep(poll)
