#!/usr/bin/env python3
"""layerAssigner.py — compatibility shim.

Renamed to hub.py (Phase 2 of refactoring-01-sqlite).
This file re-exports hub's public names so any script or import that still
references layerAssigner continues to work.  Use hub.py going forward.
"""
from hub import process, tokenize, main  # noqa: F401

if __name__ == "__main__":
    main()
