# Purpose — Refactoring 01: Move persistent memory to SQLite

## Problem

`memory/chatLog` is a single plain-text file. `writerToDatabase.record()` reloads
the whole file (`_load`), normalises **every** token occurrence to its new total,
and rewrites the whole file (`_write`) on **every** message — required by the
"all occurrences of a form share one total" invariant. Per-message cost is
O(file size); cumulative cost over M messages is ≈ O(M²). This degrades as the
log grows and is already flagged as a scalability defect.

## Goal

Replace flat-file persistence with an embedded SQLite store that:

- makes a write O(k log N) for a message of k tokens, not O(file size);
- keeps reads indexed and bounded regardless of history size;
- preserves the **exact** observable semantics of `chatLog`;
- ships tooling to reproduce the legacy text format on demand, maintain the
  database, cap file growth via 1 GB log volumes, and keep a clear path to a
  multi-host engine later.

## Non-goals and constraints

- **No migration.** The existing `memory/chatLog` is discarded at cutover
  (explicit instruction). The database starts empty.
- **Single host, single writer** for this refactor. SQLite allows one writer at
  a time; the pipeline already serialises to one writer (`layerAssigner._lock`),
  so this is not a regression. Multi-host is a separate, optional phase.
- **No third-party dependency.** Python's standard-library `sqlite3` module is
  used; no `pip install`.

## Semantics to preserve (the invariant)

A message is a `direction` (`input`/`output`) plus three ordered token fields:
media, timestamp, words. Every occurrence of a token *form* displays the same
weight — the running total = sum of the initial weights of all its occurrences
across all history. Media tokens and the epoch-second timestamp token accumulate
exactly like word tokens (per `writerToDatabase._totals`).

The legacy file stored this total inline on every occurrence and rewrote them all
on each change. The SQLite design stores each occurrence **once** and derives the
current total from a single token-weight row, producing the same observable
output without rewriting history.

## Data model

- `messages(id, seq, direction, created_epoch)` — ordered message list.
- `occurrences(id, message_id, field, position, form, initial_weight)` — one row
  per token occurrence (field: 0=media, 1=timestamp, 2=words), storing the
  per-occurrence initial weight (the delta), not the display total.
- `token_weights(form PRIMARY KEY, total_weight)` — incremental cache of
  `SUM(initial_weight)` per form; the value shown for every occurrence.
- `meta(key, value)` — `schema_version`, `page_size`, `created_at`.
- Indices: `occurrences(form)`, `occurrences(message_id, field, position)`.

`token_weights` is a derived cache: it can be rebuilt at any time from
`occurrences`, which is the integrity backstop. The timestamp token is both an
`occurrences` row (so it accumulates weight, matching legacy) and denormalised
into `messages.created_epoch` for range queries.

## Log volumes (growth control)

Append-only message/occurrence data is partitioned into volume files
`memory/volumes/chatLog.NNNN.db`. The active volume receives writes; at ≥ 1 GB it
is sealed (read-only) and a new volume is opened. `token_weights` is held
**globally** in a dedicated index database `memory/weights.db`, `ATTACH`-ed by the
writer, so the cross-history weight invariant survives partitioning — rotation
never splits or resets weights. 1 GB bounds the per-file cost of `VACUUM`,
backup, and copy, and keeps every file far below SQLite limits (≈ 17.5 TB at the
default page size).

## Maintenance

Reclaiming space after deletes requires `VACUUM` (full rebuild, needs up to twice
the file size in free space) or `auto_vacuum` (incremental, but fragments and
does not compact partial pages). Consistent backups use `VACUUM INTO` (minimal
snapshot) or the backup API. These primitives back the maintenance utilities.

## Engine portability (future multi-host)

All persistence sits behind one storage module/interface, so SQLite is a single
implementation. SQLite-specific operations (`PRAGMA`, `ATTACH`, `VACUUM`, volume
files, the in-process writer lock) are isolated. A client/server engine
(e.g. PostgreSQL) replaces them when concurrent multi-host writers are required;
that engine also removes the need for file-volume rotation and the writer lock.
Switch criteria: the data is accessed from more than one host, write concurrency
must exceed one writer, or content approaches the TB range.

## References

- C:\Users\ptigo\jrvs\writerToDatabase.py, writerToDatabase.py (record/_load/_totals/_write), n.d., jrvs project (local)
- C:\Users\ptigo\jrvs\layerAssigner.py, layerAssigner.py (single-writer lock, line 22; process(), line 53), n.d., jrvs project (local)
- C:\Users\ptigo\jrvs\TODO.md, TODO.md ("full file rewrite on every message"), n.d., jrvs project (local)
- https://www.sqlite.org/whentouse.html, Appropriate Uses For SQLite, 2025, SQLite Development Team (Hipp, D.R. et al.)
- https://www.sqlite.org/limits.html, Implementation Limits For SQLite, 2026, SQLite Development Team (Hipp, D.R. et al.)
- https://www.sqlite.org/lang_vacuum.html, VACUUM, 2025, SQLite Development Team (Hipp, D.R. et al.)
