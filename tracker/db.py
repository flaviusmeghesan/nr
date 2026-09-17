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
CONTENT_TYPES = ("video", "photo", "carousel", "story")
CONTENT_LABELS = {"video": "Video", "photo": "Poza", "carousel": "Carusel", "story": "Story"}
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

CREATE TABLE IF NOT EXISTS targets (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    week         TEXT NOT NULL,
    content_type TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, week, content_type)
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL DEFAULT 'video',
    status       TEXT NOT NULL DEFAULT 'planned',
    week         TEXT NOT NULL,
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
    metrics      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_week ON posts(week);
CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id, week);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_external
    ON posts(account_id, external_id) WHERE external_id <> '';

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
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


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
