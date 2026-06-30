#!/usr/bin/env python3
"""db.py: SQLite persistence for chatLog — Phase 1+5 implementation.

Storage layout (Phase 5 volume architecture):
  memory/weights.db               — global token_weights, volume_manifest, meta
  memory/volumes/chatLog.NNNN.db  — per-volume messages and occurrences

The writer ATTACHes weights.db to the active volume connection so that a
message insert and its weight updates commit in one SQLite transaction
(single-connection ATTACH provides this guarantee).

Volume rotation: the active volume is sealed at ≥ 1 GB and a new one is
opened automatically.  The global token_weights in weights.db are unaffected
by rotation — the cross-history weight invariant survives partitioning.

Public API (mirrors legacy writerToDatabase):
    record(direction, media_pairs, ts_pairs, word_pairs) → finalised line
    main()                                               → print weight table
    open_connection()                                    → ensure DB is ready
"""
import os
import sqlite3
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(ROOT, "memory")
VOLUMES_DIR = os.path.join(MEMORY_DIR, "volumes")
WEIGHTS_DB = os.path.join(MEMORY_DIR, "weights.db")

VOLUME_MAX_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB; lower in tests via monkey-patch

_conn = None           # active volume connection (weights.db ATTACHed as "w")
_conn_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _volume_path(n):
    return os.path.join(VOLUMES_DIR, f"chatLog.{n:04d}.db")


def _setup_weights_db():
    """Ensure weights.db and its schema exist."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS token_weights (
                form         TEXT    PRIMARY KEY,
                total_weight INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS volume_manifest (
                id         INTEGER PRIMARY KEY,
                volume_n   INTEGER NOT NULL UNIQUE,
                seq_min    INTEGER,
                seq_max    INTEGER,
                epoch_min  INTEGER,
                epoch_max  INTEGER,
                status     TEXT    NOT NULL DEFAULT 'active'
                               CHECK(status IN ('active', 'sealed')),
                byte_size  INTEGER
            );
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');
            INSERT OR IGNORE INTO meta(key, value) VALUES ('next_seq', '1');
        """)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value)"
            " VALUES ('created_at', CAST(strftime('%s', 'now') AS TEXT))"
        )
        conn.commit()
    finally:
        conn.close()


def _setup_volume_db(path):
    """Ensure a volume database and its schema exist at *path*."""
    os.makedirs(VOLUMES_DIR, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id            INTEGER PRIMARY KEY,
                seq           INTEGER NOT NULL UNIQUE,
                direction     TEXT    NOT NULL,
                created_epoch INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS occurrences (
                id             INTEGER PRIMARY KEY,
                message_id     INTEGER NOT NULL REFERENCES messages(id),
                field          INTEGER NOT NULL,
                position       INTEGER NOT NULL,
                form           TEXT    NOT NULL,
                initial_weight INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_occ_form
                ON occurrences(form);
            CREATE INDEX IF NOT EXISTS idx_occ_msg_field_pos
                ON occurrences(message_id, field, position);
        """)
        conn.commit()
    finally:
        conn.close()


def _open_volume_conn(volume_n):
    """Open the volume database and ATTACH weights.db as alias 'w'.

    check_same_thread=False is safe here because every caller holds _conn_lock,
    so only one thread accesses this connection at a time.
    """
    vpath = _volume_path(volume_n)
    _setup_volume_db(vpath)
    conn = sqlite3.connect(vpath, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("ATTACH DATABASE ? AS w", (WEIGHTS_DB,))
    return conn


def _register_volume(volume_n):
    """Insert an 'active' row in volume_manifest for *volume_n*."""
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO volume_manifest(volume_n, status)"
            " VALUES (?, 'active')",
            (volume_n,)
        )
        conn.commit()
    finally:
        conn.close()


def _active_volume_n():
    """Return the volume_n of the current active volume, or None if none."""
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        row = conn.execute(
            "SELECT volume_n FROM volume_manifest"
            " WHERE status='active' ORDER BY volume_n DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _rotate(old_conn, old_n):
    """Seal *old_n*, open the next volume, return new connection. Caller holds _conn_lock."""
    global _conn

    vpath = _volume_path(old_n)
    byte_size = os.path.getsize(vpath) if os.path.exists(vpath) else 0

    old_conn.execute(
        "UPDATE w.volume_manifest SET status='sealed', byte_size=?"
        " WHERE volume_n=?",
        (byte_size, old_n)
    )
    old_conn.commit()
    old_conn.close()

    new_n = old_n + 1
    _setup_volume_db(_volume_path(new_n))
    _register_volume(new_n)
    _conn = _open_volume_conn(new_n)
    return _conn


def _acquire():
    """Return the active write connection, initialising or rotating as needed.

    Caller MUST hold _conn_lock.
    """
    global _conn

    if _conn is None:
        _setup_weights_db()
        n = _active_volume_n()
        if n is None:
            n = 0
            _setup_volume_db(_volume_path(n))
            _register_volume(n)
        _conn = _open_volume_conn(n)

    # Rotation check: query actual file size without touching DB state
    row = _conn.execute(
        "SELECT volume_n FROM w.volume_manifest"
        " WHERE status='active' ORDER BY volume_n DESC LIMIT 1"
    ).fetchone()
    if row is not None:
        vpath = _volume_path(row[0])
        if os.path.exists(vpath) and os.path.getsize(vpath) >= VOLUME_MAX_BYTES:
            _conn = _rotate(_conn, row[0])

    return _conn


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------

def _coerce_pairs(pairs, label=""):
    """Return list of [token, int_weight], raising ValueError on bad weight."""
    result = []
    for tok, w in pairs:
        if not isinstance(w, int):
            try:
                w = int(w)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"non-integer weight for token {tok!r} in {label}: {w!r}"
                ) from exc
        result.append([tok, w])
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_connection():
    """Ensure the write connection is open and return it. Thread-safe."""
    with _conn_lock:
        return _acquire()


def record(direction, media_pairs, ts_pairs, word_pairs):
    """Persist one message and update token weights.

    Each *_pairs argument is [[token, initial_weight], ...].  Weights are
    coerced to int; a non-integer weight raises ValueError immediately rather
    than silently corrupting the store.

    Returns the finalised line as [direction, media_pairs, ts_pairs,
    word_pairs] with weights replaced by the current accumulated totals
    (matching the legacy return value).
    """
    media_pairs = _coerce_pairs(media_pairs, "media")
    ts_pairs    = _coerce_pairs(ts_pairs,    "timestamp")
    word_pairs  = _coerce_pairs(word_pairs,  "words")

    # The timestamp token value IS the epoch; pull it for messages.created_epoch
    created_epoch = int(ts_pairs[0][0]) if ts_pairs else 0

    with _conn_lock:
        conn = _acquire()

        conn.execute("BEGIN")
        try:
            # Global sequence number (atomic increment in weights.db)
            seq = int(
                conn.execute("SELECT value FROM w.meta WHERE key='next_seq'").fetchone()[0]
            )
            conn.execute(
                "UPDATE w.meta SET value=? WHERE key='next_seq'", (seq + 1,)
            )

            # Insert the message row
            cur = conn.execute(
                "INSERT INTO messages(seq, direction, created_epoch)"
                " VALUES (?, ?, ?)",
                (seq, direction, created_epoch)
            )
            msg_id = cur.lastrowid

            # Insert occurrences and accumulate weights in token_weights
            all_fields = ((0, media_pairs), (1, ts_pairs), (2, word_pairs))
            forms = set()
            for field_idx, pairs in all_fields:
                for pos, (tok, w) in enumerate(pairs):
                    conn.execute(
                        "INSERT INTO occurrences"
                        "(message_id, field, position, form, initial_weight)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (msg_id, field_idx, pos, tok, w)
                    )
                    conn.execute(
                        "INSERT INTO w.token_weights(form, total_weight) VALUES (?, ?)"
                        " ON CONFLICT(form) DO UPDATE"
                        " SET total_weight = total_weight + excluded.total_weight",
                        (tok, w)
                    )
                    forms.add(tok)

            # Update manifest range columns for the active volume
            conn.execute(
                """
                UPDATE w.volume_manifest
                SET seq_max   = ?,
                    epoch_max = ?,
                    seq_min   = COALESCE(seq_min,   ?),
                    epoch_min = COALESCE(epoch_min, ?)
                WHERE status = 'active'
                """,
                (seq, created_epoch, seq, created_epoch)
            )

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Read back current totals for the return value
        placeholders = ",".join("?" * len(forms))
        totals = dict(
            conn.execute(
                f"SELECT form, total_weight FROM w.token_weights WHERE form IN ({placeholders})",
                list(forms)
            ).fetchall()
        )

    def _with_totals(pairs):
        return [[tok, totals[tok]] for tok, _ in pairs]

    return [
        direction,
        _with_totals(media_pairs),
        _with_totals(ts_pairs),
        _with_totals(word_pairs),
    ]


def main():
    """Read-only view: token form and accumulated total weight, heaviest first."""
    open_connection()   # ensure weights.db exists
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        rows = conn.execute(
            "SELECT form, total_weight FROM token_weights"
            " ORDER BY total_weight DESC, form"
        ).fetchall()
    finally:
        conn.close()
    for form, total in rows:
        print(f"{total}\t{form}")


if __name__ == "__main__":
    main()
