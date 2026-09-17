"""Schema si acces la baza de date SQLite (doar stdlib)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "tracker.db"
MEDIA_DIR = Path(os.environ.get("TRACKER_MEDIA", ROOT / "media"))

PLATFORMS = ("instagram", "facebook", "tiktok")
PLATFORM_LABELS = {"instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok"}
CONTENT_TYPES = ("any", "video", "photo", "carousel", "story")
CONTENT_LABELS = {"any": "Orice postare", "video": "Video", "photo": "Poza",
                  "carousel": "Carusel", "story": "Story"}
# 'any' e doar pentru tinte ("4 postari pe saptamana, indiferent de tip").
POST_CONTENT_TYPES = ("video", "photo", "carousel", "story")
PERIODS = ("week", "month")
PERIOD_LABELS = {"week": "saptamana", "month": "luna"}
STATUSES = ("idea", "planned", "scheduled", "posted")
STATUS_LABELS = {"idea": "Idee", "planned": "Planificat",
                 "scheduled": "Programat", "posted": "Postat"}
ANY_WEEK = "*"  # target recurent, valabil pentru orice saptamana

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS clients (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    notes      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    platform     TEXT NOT NULL,
    handle       TEXT NOT NULL DEFAULT '',
    external_id  TEXT NOT NULL DEFAULT '',
    access_token TEXT NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    UNIQUE(client_id, platform, handle)
);

CREATE TABLE IF NOT EXISTS members (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);

-- O tinta se poate pune fie pe un cont anume, fie pe client (adica pe toate
-- platformele lui la un loc - cazul obisnuit cand acelasi material se publica
-- peste tot si se numara o singura data). `period` e 'week' sau 'month', iar
-- `period_key` e '*' pentru o tinta recurenta, sau '2026-W38' / '2026-09'
-- pentru o valoare valabila doar in perioada aia.
CREATE TABLE IF NOT EXISTS targets (
    id           INTEGER PRIMARY KEY,
    client_id    INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    account_id   INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    period       TEXT NOT NULL DEFAULT 'week',
    period_key   TEXT NOT NULL DEFAULT '*',
    content_type TEXT NOT NULL,
    target_min   INTEGER NOT NULL DEFAULT 0,
    target_max   INTEGER NOT NULL DEFAULT 0,
    CHECK (client_id IS NOT NULL OR account_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_targets_client
    ON targets(client_id, period, period_key, content_type) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_targets_account
    ON targets(account_id, period, period_key, content_type) WHERE account_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL DEFAULT 'video',
    status       TEXT NOT NULL DEFAULT 'planned',
    week         TEXT NOT NULL,
    month        TEXT NOT NULL DEFAULT '',
    planned_for  TEXT NOT NULL DEFAULT '',
    posted_at    TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    caption      TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    author       TEXT NOT NULL DEFAULT '',
    media_path   TEXT NOT NULL DEFAULT '',
    thumb_url    TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'manual',
    external_id  TEXT NOT NULL DEFAULT '',
    content_group TEXT NOT NULL DEFAULT '',
    metrics      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_week ON posts(week);
CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id, week);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_external
    ON posts(account_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_posts_group ON posts(content_group);
CREATE INDEX IF NOT EXISTS idx_posts_month ON posts(month);

-- Maparea de coloane CSV -> campuri interne, salvata per platforma, ca sa nu
-- o refaci de fiecare data cand exporti din Business Suite / TikTok Studio.
CREATE TABLE IF NOT EXISTS import_profiles (
    id         INTEGER PRIMARY KEY,
    platform   TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT 'implicit',
    mapping    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, name)
);
"""

_local = threading.local()


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def db_path() -> Path:
    return Path(os.environ.get("TRACKER_DB", DEFAULT_DB))


def connect() -> sqlite3.Connection:
    """Conexiune per-thread (HTTPServer-ul e threaded)."""
    conn = getattr(_local, "conn", None)
    path = db_path()
    if conn is not None and getattr(_local, "path", None) == str(path):
        return conn
    if conn is not None:
        conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    _local.path = str(path)
    return conn


def init_db() -> sqlite3.Connection:
    conn = connect()
    migrate(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def migrate(conn: sqlite3.Connection) -> None:
    """Aduce o baza mai veche la schema curenta, pastrand datele.

    Se ruleaza inainte de SCHEMA (care e doar CREATE IF NOT EXISTS si deci nu
    modifica tabele existente).
    """
    posts_cols = _columns(conn, "posts")
    if posts_cols and "content_group" not in posts_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN content_group TEXT NOT NULL DEFAULT ''")
    if posts_cols and "month" not in posts_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN month TEXT NOT NULL DEFAULT ''")
        # completam luna din datele deja existente
        conn.execute("UPDATE posts SET month = substr("
                     "COALESCE(NULLIF(posted_at, ''), planned_for), 1, 7) "
                     "WHERE month = ''")

    targets_cols = _columns(conn, "targets")
    if targets_cols and "target_count" in targets_cols:
        # Schema veche: tinte doar pe cont, doar saptamanale, doar numar fix.
        conn.execute("ALTER TABLE targets RENAME TO targets_old")
        conn.executescript(SCHEMA)
        conn.execute("""
            INSERT INTO targets (account_id, period, period_key, content_type,
                                 target_min, target_max)
            SELECT account_id, 'week', week, content_type, target_count, target_count
            FROM targets_old
        """)
        conn.execute("DROP TABLE targets_old")
    conn.commit()


def reset_thread_state() -> None:
    """Folosit de teste ca sa nu tina conexiuni catre un DB sters."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.path = None


def query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def load_metrics(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}
