#!/usr/bin/env python3
"""writerToDatabase: persists chatLog and accumulates inline word weights.

This module is now a thin facade over ``db.py``, which provides the SQLite
backend.  The public interface -- ``record()`` and ``main()`` -- is unchanged
so that ``hub.py`` (formerly ``layerAssigner.py``) and any other callers
continue to work without modification.

Legacy chatLog line layout (preserved by ``tools/exportChatlog.py``)::

    <direction>\\t<media pairs>\\t<timestamp pairs>\\t<word pairs>

Each of the three pair fields is a space-separated positional sequence where
even indices are tokens and odd indices are their accumulated weights.

Accumulation rule: every occurrence of a token *form* displays the same
weight -- the running total of all initial weights contributed by that form
across the entire history.  The SQLite backend stores each initial weight once
(in ``occurrences``) and caches the running total in ``token_weights``, giving
the same observable output as the legacy full-file-rewrite approach without
the O(file size) cost per message.
"""
import db

# Re-export the two public names so legacy ``import writerToDatabase`` callers
# find ``writerToDatabase.record`` and ``writerToDatabase.main`` unchanged.
record = db.record
main   = db.main


if __name__ == "__main__":
    main()
