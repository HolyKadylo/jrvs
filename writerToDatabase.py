#!/usr/bin/env python3
"""writerToDatabase: persists chatLog and accumulates inline word weights.

chatLog line layout (one message per line)::

    <direction>\t<media pairs>\t<timestamp pairs>\t<word pairs>

``<direction>`` is ``input`` or ``output`` and carries no weight. Each of the other
three fields is a space-separated *positional* sequence where even indices are
tokens and odd indices are their weights -- robust even when a token is itself a
number (epoch) or punctuation, which rules out a ``token:weight`` delimiter.

Accumulation rule (the literal "add the word weight to all the occurrences"):
when a new line is recorded, each token's initial weight is added to the running
total for its exact form, and EVERY occurrence of that form across chatLog is
rewritten to the new total. Because all occurrences therefore share one total, no
separate per-occurrence store is needed -- each new occurrence simply bumps it.
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CHATLOG = os.path.join(ROOT, "chatLog")


def _parse_pairs(field):
    parts = field.split(" ") if field else []
    pairs = []
    for i in range(0, len(parts) - 1, 2):
        pairs.append([parts[i], int(parts[i + 1])])
    return pairs


def _serialize_pairs(pairs):
    return " ".join(f"{tok} {w}" for tok, w in pairs)


def _load():
    lines = []
    if os.path.exists(CHATLOG):
        with open(CHATLOG, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.rstrip("\n")
                if not raw:
                    continue
                f = raw.split("\t")
                lines.append([
                    f[0],
                    _parse_pairs(f[1] if len(f) > 1 else ""),
                    _parse_pairs(f[2] if len(f) > 2 else ""),
                    _parse_pairs(f[3] if len(f) > 3 else ""),
                ])
    return lines


def _totals(lines):
    """Map each token form to its current (shared) total weight."""
    total = {}
    for _, media, ts, words in lines:
        for section in (media, ts, words):
            for tok, w in section:
                total[tok] = w  # invariant: equal across all occurrences
    return total


def _write(lines):
    tmp = CHATLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for direction, media, ts, words in lines:
            fh.write("\t".join([
                direction,
                _serialize_pairs(media),
                _serialize_pairs(ts),
                _serialize_pairs(words),
            ]) + "\n")
    os.replace(tmp, CHATLOG)


def record(direction, media_pairs, ts_pairs, word_pairs):
    """Append a message to chatLog, accumulating inline weights across the file.

    Each ``*_pairs`` argument is a list of ``[token, initial_weight]``. Returns the
    finalised new line (weights replaced by the accumulated totals).
    """
    lines = _load()
    total = _totals(lines)

    new_line = [
        direction,
        [list(p) for p in media_pairs],
        [list(p) for p in ts_pairs],
        [list(p) for p in word_pairs],
    ]

    # Accumulate this line's initial weights into the running totals, left to right
    # so a form repeated within one line bumps the total for each occurrence.
    for section in (new_line[1], new_line[2], new_line[3]):
        for pair in section:
            total[pair[0]] = total.get(pair[0], 0) + pair[1]
            pair[1] = total[pair[0]]

    lines.append(new_line)

    # Normalize EVERY occurrence -- existing lines and the new one -- to the final
    # totals, so all occurrences of a form share one weight (including any repeats
    # within this same line).
    for _, media, ts, words in lines:
        for section in (media, ts, words):
            for pair in section:
                pair[1] = total[pair[0]]

    _write(lines)
    return new_line


def main():
    """Read-only DB view: accumulated weight per token form, heaviest first."""
    total = _totals(_load())
    for tok, w in sorted(total.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{w}\t{tok}")


if __name__ == "__main__":
    main()
