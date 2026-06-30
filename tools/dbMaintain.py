#!/usr/bin/env python3
"""dbMaintain.py: maintenance utilities for the chatLog SQLite store.

Subcommands:
    integrity       PRAGMA quick_check / integrity_check on all databases
    rebuild-weights Recompute token_weights from occurrences; report and repair drift
    vacuum          VACUUM the active volume and weights.db; --into PATH for VACUUM INTO
    backup          Consistent snapshot via VACUUM INTO
    stats           Database sizes, row counts, heaviest tokens, volume listing
    prune           Remove messages by age (--before-epoch) or by volume (--volume N)

Usage:
    python3 tools/dbMaintain.py <subcommand> [options] [DB_ROOT]

    DB_ROOT   project root directory (default: parent of this script's directory).

Note on prune and weights:
    Pruning removes occurrences rows from the store.  By default, token_weights
    are NOT decremented — they reflect all-time totals.  Pass --rebuild-weights
    after pruning (or use the dedicated subcommand) to recompute totals from the
    surviving occurrences.
"""
import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _project_root(explicit=None):
    if explicit:
        return os.path.abspath(explicit)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db_paths(root):
    memory = os.path.join(root, "memory")
    return (
        os.path.join(memory, "weights.db"),
        os.path.join(memory, "volumes"),
    )


def _iter_volumes(weights_db, volumes_dir):
    """Yield (volume_n, path) in ascending order from the manifest."""
    if not os.path.exists(weights_db):
        return
    conn = sqlite3.connect(weights_db)
    try:
        rows = conn.execute(
            "SELECT volume_n, status FROM volume_manifest ORDER BY volume_n ASC"
        ).fetchall()
    finally:
        conn.close()
    for n, status in rows:
        path = os.path.join(volumes_dir, f"chatLog.{n:04d}.db")
        if os.path.exists(path):
            yield n, path, status


def _open(path, read_only=False):
    uri = f"file:{path}{'?mode=ro' if read_only else ''}".replace("\\", "/")
    conn = sqlite3.connect(f"file:{path}", uri=False)
    if read_only:
        conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------

def cmd_integrity(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)
    ok = True

    def _check(label, path, mode):
        nonlocal ok
        if not os.path.exists(path):
            print(f"  MISSING  {label}")
            return
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute(f"PRAGMA {mode}").fetchall()
        finally:
            conn.close()
        results = [r[0] for r in rows]
        if results == ["ok"]:
            print(f"  ok       {label}")
        else:
            ok = False
            print(f"  FAIL     {label}")
            for r in results:
                print(f"           {r}")

    mode = "integrity_check" if args.full else "quick_check"
    print(f"Running {mode}...")
    _check("weights.db", weights_db, mode)
    for n, vpath, status in _iter_volumes(weights_db, volumes_dir):
        _check(f"volumes/chatLog.{n:04d}.db  [{status}]", vpath, mode)

    if ok:
        print("All databases OK.")
    else:
        print("One or more databases FAILED integrity check.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# rebuild-weights
# ---------------------------------------------------------------------------

def cmd_rebuild_weights(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    if not os.path.exists(weights_db):
        print("error: weights.db not found.", file=sys.stderr)
        sys.exit(1)

    print("Recomputing token_weights from occurrences across all volumes...")

    # Accumulate SUM(initial_weight) per form from every volume
    recomputed = {}
    for n, vpath, _ in _iter_volumes(weights_db, volumes_dir):
        conn = sqlite3.connect(vpath)
        try:
            rows = conn.execute(
                "SELECT form, SUM(initial_weight) FROM occurrences GROUP BY form"
            ).fetchall()
        finally:
            conn.close()
        for form, total in rows:
            recomputed[form] = recomputed.get(form, 0) + total

    # Compare to cached token_weights
    wconn = sqlite3.connect(weights_db)
    try:
        cached = dict(wconn.execute(
            "SELECT form, total_weight FROM token_weights"
        ).fetchall())

        all_forms = set(recomputed) | set(cached)
        drifted = []
        for form in sorted(all_forms):
            r = recomputed.get(form, 0)
            c = cached.get(form, 0)
            if r != c:
                drifted.append((form, c, r))

        if not drifted:
            print(f"No drift detected ({len(cached)} forms checked).")
            return

        print(f"Drift detected in {len(drifted)} form(s):")
        for form, cached_v, computed_v in drifted:
            print(f"  {form!r:30s}  cached={cached_v}  computed={computed_v}")

        if args.dry_run:
            print("Dry run: no changes written.")
            return

        # Repair
        wconn.execute("BEGIN")
        try:
            # Delete forms that no longer appear in occurrences
            for form, _, computed_v in drifted:
                if computed_v == 0 and form not in recomputed:
                    wconn.execute("DELETE FROM token_weights WHERE form=?", (form,))
                else:
                    wconn.execute(
                        "INSERT INTO token_weights(form, total_weight) VALUES (?, ?)"
                        " ON CONFLICT(form) DO UPDATE SET total_weight=excluded.total_weight",
                        (form, recomputed.get(form, 0))
                    )
            wconn.execute("COMMIT")
        except Exception:
            wconn.execute("ROLLBACK")
            raise

        print(f"Repaired {len(drifted)} form(s).")
    finally:
        wconn.close()


# ---------------------------------------------------------------------------
# vacuum
# ---------------------------------------------------------------------------

def cmd_vacuum(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    def _vacuum_one(label, path):
        if not os.path.exists(path):
            print(f"  skipped (not found): {label}")
            return
        conn = sqlite3.connect(path)
        try:
            if args.into:
                dest = args.into
                if os.path.isdir(dest):
                    dest = os.path.join(dest, os.path.basename(path))
                conn.execute(f"VACUUM INTO ?", (dest,))
                print(f"  VACUUM INTO {dest}  ← {label}")
            else:
                conn.execute("VACUUM")
                print(f"  VACUUM  {label}")
        finally:
            conn.close()

    print("Vacuuming databases...")
    _vacuum_one("weights.db", weights_db)
    for n, vpath, _ in _iter_volumes(weights_db, volumes_dir):
        _vacuum_one(f"volumes/chatLog.{n:04d}.db", vpath)
    print("Done.")


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

def cmd_backup(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    dest_dir = os.path.abspath(args.dest)
    os.makedirs(dest_dir, exist_ok=True)

    def _backup_one(label, path):
        if not os.path.exists(path):
            print(f"  skipped (not found): {label}")
            return
        dest = os.path.join(dest_dir, os.path.basename(path))
        conn = sqlite3.connect(path)
        try:
            conn.execute("VACUUM INTO ?", (dest,))
        finally:
            conn.close()
        size = os.path.getsize(dest)
        print(f"  {label}  →  {dest}  ({size:,} bytes)")

    print(f"Backing up to {dest_dir}...")
    _backup_one("weights.db", weights_db)
    for n, vpath, _ in _iter_volumes(weights_db, volumes_dir):
        _backup_one(f"volumes/chatLog.{n:04d}.db", vpath)
    print("Done.")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def cmd_stats(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    if not os.path.exists(weights_db):
        print("No database found. Run the pipeline first.")
        return

    wconn = sqlite3.connect(weights_db)
    try:
        token_count = wconn.execute("SELECT COUNT(*) FROM token_weights").fetchone()[0]
        top_n = args.top
        top_tokens = wconn.execute(
            "SELECT form, total_weight FROM token_weights"
            " ORDER BY total_weight DESC, form LIMIT ?",
            (top_n,)
        ).fetchall()
        volumes = wconn.execute(
            "SELECT volume_n, seq_min, seq_max, epoch_min, epoch_max, status, byte_size"
            " FROM volume_manifest ORDER BY volume_n"
        ).fetchall()
        next_seq = wconn.execute(
            "SELECT value FROM meta WHERE key='next_seq'"
        ).fetchone()
        schema_v = wconn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
    finally:
        wconn.close()

    weights_size = os.path.getsize(weights_db)
    total_messages = int(next_seq[0]) - 1 if next_seq else 0
    total_vol_size = 0

    print(f"Schema version : {schema_v[0] if schema_v else '?'}")
    print(f"Total messages : {total_messages}")
    print(f"Unique forms   : {token_count}")
    print(f"weights.db     : {weights_size:,} bytes")
    print()
    print("Volumes:")
    for n, seq_min, seq_max, ep_min, ep_max, status, byte_size in volumes:
        vpath = os.path.join(volumes_dir, f"chatLog.{n:04d}.db")
        fsize = os.path.getsize(vpath) if os.path.exists(vpath) else 0
        total_vol_size += fsize
        seq_range = f"seq {seq_min}–{seq_max}" if seq_min is not None else "empty"
        print(f"  [{n:04d}] {status:6s}  {seq_range:25s}  {fsize:>12,} bytes")
    print(f"  Total volume storage: {total_vol_size:,} bytes")

    if top_tokens:
        print(f"\nTop {top_n} tokens by weight:")
        for form, w in top_tokens:
            print(f"  {w:>8}  {form}")


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------

def cmd_prune(args):
    root = _project_root(args.db_root)
    weights_db, volumes_dir = _db_paths(root)

    if not os.path.exists(weights_db):
        print("error: weights.db not found.", file=sys.stderr)
        sys.exit(1)

    if args.before_epoch is None and args.volume is None:
        print("error: specify --before-epoch or --volume.", file=sys.stderr)
        sys.exit(1)

    pruned_msgs = 0
    pruned_occ  = 0

    for n, vpath, status in _iter_volumes(weights_db, volumes_dir):
        # Volume filter
        if args.volume is not None and n != args.volume:
            continue

        conn = sqlite3.connect(vpath)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN")
            try:
                if args.before_epoch is not None:
                    msg_ids = [
                        r[0] for r in conn.execute(
                            "SELECT id FROM messages WHERE created_epoch < ?",
                            (args.before_epoch,)
                        ).fetchall()
                    ]
                else:
                    msg_ids = [r[0] for r in conn.execute("SELECT id FROM messages").fetchall()]

                if not msg_ids:
                    conn.execute("ROLLBACK")
                    continue

                if args.dry_run:
                    occ_count = conn.execute(
                        f"SELECT COUNT(*) FROM occurrences"
                        f" WHERE message_id IN ({','.join('?'*len(msg_ids))})",
                        msg_ids
                    ).fetchone()[0]
                    print(f"  [dry run] volume {n:04d}: would remove"
                          f" {len(msg_ids)} messages, {occ_count} occurrences")
                    conn.execute("ROLLBACK")
                    continue

                placeholders = ",".join("?" * len(msg_ids))
                occ_del = conn.execute(
                    f"DELETE FROM occurrences WHERE message_id IN ({placeholders})",
                    msg_ids
                ).rowcount
                msg_del = conn.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    msg_ids
                ).rowcount
                conn.execute("COMMIT")
                pruned_msgs += msg_del
                pruned_occ  += occ_del
                print(f"  volume {n:04d}: removed {msg_del} messages, {occ_del} occurrences")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    if not args.dry_run:
        print(f"Pruned {pruned_msgs} messages and {pruned_occ} occurrences total.")
        print("Note: token_weights reflect all-time totals and were NOT decremented.")
        print("      Run 'rebuild-weights' to recompute from surviving occurrences.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(
        description="Maintenance utilities for the chatLog SQLite store."
    )
    sub = p.add_subparsers(dest="command", required=True)

    # integrity
    pi = sub.add_parser("integrity", help="Run SQLite integrity checks.")
    pi.add_argument("db_root", nargs="?", default=None)
    pi.add_argument("--full", action="store_true",
                    help="Use integrity_check instead of quick_check (slower).")

    # rebuild-weights
    pr = sub.add_parser("rebuild-weights",
                        help="Recompute token_weights from occurrences.")
    pr.add_argument("db_root", nargs="?", default=None)
    pr.add_argument("--dry-run", action="store_true",
                    help="Report drift without writing changes.")

    # vacuum
    pv = sub.add_parser("vacuum", help="VACUUM databases.")
    pv.add_argument("db_root", nargs="?", default=None)
    pv.add_argument("--into", default=None, metavar="PATH",
                    help="Use VACUUM INTO to write compacted copies to PATH.")

    # backup
    pb = sub.add_parser("backup", help="Snapshot databases via VACUUM INTO.")
    pb.add_argument("dest", help="Destination directory for backup files.")
    pb.add_argument("db_root", nargs="?", default=None)

    # stats
    ps = sub.add_parser("stats", help="Show database statistics.")
    ps.add_argument("db_root", nargs="?", default=None)
    ps.add_argument("--top", type=int, default=10, metavar="N",
                    help="Show top N tokens by weight (default: 10).")

    # prune
    pp = sub.add_parser("prune", help="Remove old messages.")
    pp.add_argument("db_root", nargs="?", default=None)
    pp.add_argument("--before-epoch", type=int, default=None, metavar="EPOCH",
                    help="Remove messages with created_epoch < EPOCH.")
    pp.add_argument("--volume", type=int, default=None, metavar="N",
                    help="Remove all messages from volume N.")
    pp.add_argument("--dry-run", action="store_true",
                    help="Report what would be removed without deleting.")

    return p.parse_args()


def main():
    args = _parse_args()
    dispatch = {
        "integrity":       cmd_integrity,
        "rebuild-weights": cmd_rebuild_weights,
        "vacuum":          cmd_vacuum,
        "backup":          cmd_backup,
        "stats":           cmd_stats,
        "prune":           cmd_prune,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
