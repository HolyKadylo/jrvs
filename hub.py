#!/usr/bin/env python3
"""hub.py: the pipeline hub (renamed from layerAssigner.py).

Watches both bus channels. For every message it timestamps (timeStamper),
tokenizes the text into words/punctuation, assigns an initial weight to every
token -- media, timestamp, and word tokens alike -- and hands the structured
line to writerToDatabase, which persists it to the SQLite store and updates
accumulated token weights.

Input weights are directed by inputThinker. Output weights default to 1 (a
hook is left for a symmetric outputThinker-directed policy).

The "layer" term is freed by this rename for future use in a real layer
architecture.
"""
import re
import threading

import bus
import inputThinker
import timeStamper
import writerToDatabase

TOKEN_RE = re.compile(r"\w+|[^\w\s]")

_lock = threading.Lock()  # single writer; serialise records


def tokenize(text):
    return TOKEN_RE.findall(text)


def _assign(tokens, direction, start_index):
    """Return ``[[token, initial_weight], ...]`` using the per-direction policy."""
    pairs = []
    for offset, tok in enumerate(tokens):
        if direction == "input":
            w = inputThinker.weight(tok, start_index + offset)
        else:
            w = 1  # TODO: outputThinker-directed weighting for output tokens
        pairs.append([tok, w])
    return pairs


def process(direction, media, text):
    media_tokens = media.split()
    ts_tokens    = [str(timeStamper.now_epoch())]
    word_tokens  = tokenize(text)

    idx = 0
    media_pairs = _assign(media_tokens, direction, idx)
    idx += len(media_tokens)
    ts_pairs = _assign(ts_tokens, direction, idx)
    idx += len(ts_tokens)
    word_pairs = _assign(word_tokens, direction, idx)

    with _lock:
        return writerToDatabase.record(direction, media_pairs, ts_pairs, word_pairs)


def _watch(channel, direction):
    for fields in bus.tail(channel):
        media = fields[0] if fields else ""
        text  = fields[1] if len(fields) > 1 else ""
        process(direction, media, text)


def main():
    threads = [
        threading.Thread(target=_watch, args=("input.events",  "input"),  daemon=True),
        threading.Thread(target=_watch, args=("output.events", "output"), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
