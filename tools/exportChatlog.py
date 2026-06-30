#!/usr/bin/env python3
"""exportChatlog.py: convert the SQLite chatLog store to the legacy text format.

Reads ``memory/weights.db`` and ``memory/volumes/chatLog.NNNN.db`` and emits
one TAB-separated line per message, matching the format that ``memory/chatLog``
used to contain.

Version history implemented here:
  v1  exact reproduction of the full history (default)
  v2  range/selection: --from/--to by seq or epoch; --direction input|output
  v3  volume-aware: iterates volumes in manifest order (transparent)
  v4  filter/projection: --token FORM, --limit N, --reverse
  v5  formats and follow: --format chatlog|jsonl|csv; --follow to stream new rows

Usage:
    python3 tools/exportChatlog.py [options] [DB_ROOT]

    DB_ROOT   root directory of the project (default: parent of this script's
              directory, i.e. the project root).

Options:
    --from SEQ_OR_EPOCH   start at this seq (integer) or epoch (if --by-epoch)
    --to   SEQ_OR_EPOCH   stop  at this seq (integer) or epoch (if --by-epoch)
    --by-epoch            interpret --from/--to as Unix timestamps
    --direction DIR       filter to 'input' or 'output' messages only
    --token FORM          emit only messages that contain this token form
    --limit N             emit at most N messages
    --reverse             emit messages newest-first
    --format FMT          output format: chatlog (default), jsonl, csv
    --follow              stream new messages as they are written (v5)
    --out FILE            write to FILE instead of stdout
"""
import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _db_paths(root):
    """Return (weights_db_path, volumes_dir) for the given project root."""
    memory = os.path.join(root, "memory")
    return (
        os.path.join(memory, "weights.db"),
        os.path.join(memory, "volumes"),
    )


def _project_root(explicit=None):
    if explicit:
        return os.path.abspath(explicit)
    # This script lives in <root>/tools/; go one level up.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Volume iteration (v3)
# ---------------------------------------------------------------------------

def _iter_volumes(weights_db, volumes_dir):
    """Yield (volume_n, volume_path) in ascending seq order from the manifest."""
    if not os.path.exists(weights_db):
        return
    conn = sqlite3.connect(weights_db)
    try:
        rows = conn.execute(
            "SELECT volume_n FROM volume_manifest ORDER BY volume_n ASC"
        ).fetchall()
    finally:
        conn.close()
    for (n,) in rows:
        path = os.path.join(volumes_dir, f"chatLog.{n:04d}.db")
        if os.path.exists(path):
            yield n, path


# ---------------------------------------------------------------------------
# Core query (v1-v4)
# ---------------------------------------------------------------------------

def _query_volume(vconn, weights_db, args):
    """Yield row dicts from one open volume connection, applying all filters."""
    vconn.execute("ATTACH DATABASE ? AS w", (weights_db,))

    where_clauses = []
    params = []

    if not args.by_epoch:
        if args.from_ is not None:
            where_clauses.append("m.seq >= ?")
            params.append(args.from_)
        if args.to is not None:
            where_clauses.append("m.seq <= ?")
            params.append(args.to)
    else:
        if args.from_ is not None:
            where_clauses.append("m.created_epoch >= ?")
            params.append(args.from_)
        if args.to is not None:
            where_clauses.append("m.created_epoch <= ?")
            params.append(args.to)

    if args.direction:
        where_clauses.append("m.direction = ?")
        params.append(args.direction)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    order_sql = "ORDER BY m.seq " + ("DESC" if args.reverse else "ASC")

    sql = f"""
        SELECT m.id, m.seq, m.direction, m.created_epoch
        FROM messages m
        {where_sql}
        {order_sql}
    """
    for msg_id, seq, direction, created_epoch in vconn.execute(sql, params):
        occ_rows = vconn.execute(
            """
            SELECT o.field, o.position, o.form, COALESCE(tw.total_weight, o.initial_weight)
            FROM occurrences o
            LEFT JOIN w.token_weights tw ON o.form = tw.form
            WHERE o.message_id = ?
            ORDER BY o.field, o.position
            """,
            (msg_id,)
        ).fetchall()

        # Group into fields
        fields = {0: [], 1: [], 2: []}
        for field, pos, form, weight in occ_rows:
            fields[field].append((form, weight))

        # --token filter (v4): skip messages that don't contain the form
        if args.token:
            all_forms = {form for pairs in fields.values() for form, _ in pairs}
            if args.token not in all_forms:
                continue

        yield {
            "seq": seq,
            "direction": direction,
            "created_epoch": created_epoch,
            "media": fields[0],
            "timestamp": fields[1],
            "words": fields[2],
        }


# ---------------------------------------------------------------------------
# Formatters (v5)
# ---------------------------------------------------------------------------

def _serialize_pairs(pairs):
    """Space-separated token-weight positional sequence."""
    return " ".join(f"{tok} {w}" for tok, w in pairs)


def _format_chatlog(row):
    return "\t".join([
        row["direction"],
        _serialize_pairs(row["media"]),
        _serialize_pairs(row["timestamp"]),
        _serialize_pairs(row["words"]),
    ])


def _format_jsonl(row):
    def _pairs_to_list(pairs):
        return [{"form": f, "weight": w} for f, w in pairs]
    return json.dumps({
        "seq":           row["seq"],
        "direction":     row["direction"],
        "created_epoch": row["created_epoch"],
        "media":         _pairs_to_list(row["media"]),
        "timestamp":     _pairs_to_list(row["timestamp"]),
        "words":         _pairs_to_list(row["words"]),
    }, ensure_ascii=False)


def _make_csv_writer(out):
    writer = csv.writer(out)
    writer.writerow(["seq", "direction", "created_epoch",
                     "media", "timestamp", "words"])
    return writer


def _format_csv_row(row, writer):
    writer.writerow([
        row["seq"],
        row["direction"],
        row["created_epoch"],
        _serialize_pairs(row["media"]),
        _serialize_pairs(row["timestamp"]),
        _serialize_pairs(row["words"]),
    ])


# ---------------------------------------------------------------------------
# Main export loop
# ---------------------------------------------------------------------------

def _export(args, out):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    if not os.path.exists(weights_db):
        print(f"error: weights.db not found at {weights_db}", file=sys.stderr)
        sys.exit(1)

    fmt = args.format
    csv_writer = _make_csv_writer(out) if fmt == "csv" else None

    emitted = 0

    def _emit(row):
        nonlocal emitted
        if fmt == "chatlog":
            out.write(_format_chatlog(row) + "\n")
        elif fmt == "jsonl":
            out.write(_format_jsonl(row) + "\n")
        elif fmt == "csv":
            _format_csv_row(row, csv_writer)
        out.flush()
        emitted += 1

    def _run_once():
        for _, vpath in _iter_volumes(weights_db, volumes_dir):
            vconn = sqlite3.connect(vpath)
            try:
                for row in _query_volume(vconn, weights_db, args):
                    _emit(row)
                    if args.limit and emitted >= args.limit:
                        return
            finally:
                vconn.close()

    _run_once()

    # --follow: poll for new messages (v5)
    if args.follow:
        last_seq = emitted  # rough cursor; for precision, track actual seq
        # Determine the highest seq we've seen
        conn = sqlite3.connect(weights_db)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='next_seq'").fetchone()
            cursor_seq = int(row[0]) - 1 if row else 0
        finally:
            conn.close()

        while True:
            time.sleep(0.5)
            conn = sqlite3.connect(weights_db)
            try:
                row = conn.execute("SELECT value FROM meta WHERE key='next_seq'").fetchone()
                next_seq = int(row[0]) if row else cursor_seq + 1
            finally:
                conn.close()

            if next_seq <= cursor_seq + 1:
                continue  # nothing new

            # Build a minimal args copy with from_ set past cursor
            class _FollowArgs:
                pass
            fa = _FollowArgs()
            fa.__dict__.update(vars(args))
            fa.from_ = cursor_seq + 1
            fa.to = None
            fa.by_epoch = False
            fa.follow = False

            for _, vpath in _iter_volumes(weights_db, volumes_dir):
                vconn = sqlite3.connect(vpath)
                try:
                    for r in _query_volume(vconn, weights_db, fa):
                        _emit(r)
                        cursor_seq = r["seq"]
                finally:
                    vconn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(
        description="Export the SQLite chatLog store to legacy text or other formats."
    )
    p.add_argument("db_root", nargs="?", default=None,
                   help="project root directory (default: parent of tools/)")
    p.add_argument("--from", dest="from_", type=int, default=None,
                   metavar="SEQ_OR_EPOCH",
                   help="start at this seq (or epoch with --by-epoch)")
    p.add_argument("--to", dest="to", type=int, default=None,
                   metavar="SEQ_OR_EPOCH",
                   help="stop at this seq (or epoch with --by-epoch)")
    p.add_argument("--by-epoch", action="store_true",
                   help="interpret --from/--to as Unix timestamps")
    p.add_argument("--direction", choices=["input", "output"], default=None,
                   help="filter to input or output messages")
    p.add_argument("--token", default=None, metavar="FORM",
                   help="emit only messages containing this token form")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="emit at most N messages")
    p.add_argument("--reverse", action="store_true",
                   help="emit messages newest-first")
    p.add_argument("--format", choices=["chatlog", "jsonl", "csv"],
                   default="chatlog",
                   help="output format (default: chatlog)")
    p.add_argument("--follow", action="store_true",
                   help="stream new messages as they are written")
    p.add_argument("--out", default=None, metavar="FILE",
                   help="write to FILE instead of stdout")
    return p.parse_args()


def main():
    args = _parse_args()
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            _export(args, fh)
    else:
        _export(args, sys.stdout)


if __name__ == "__main__":
    main()
