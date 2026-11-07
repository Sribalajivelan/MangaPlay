from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS manga(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapter(
  id INTEGER PRIMARY KEY,
  manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
  number REAL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('uploading','queued','processing','ready','failed','cancelled')),
  stage TEXT,
  progress REAL NOT NULL DEFAULT 0,
  detail TEXT,
  error TEXT,
  page_count INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  queued_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  ready_at TEXT
);
CREATE INDEX IF NOT EXISTS chapter_manga ON chapter(manga_id, number, id);
CREATE INDEX IF NOT EXISTS chapter_status ON chapter(status, queued_at);
CREATE TABLE IF NOT EXISTS stage_run(
  id INTEGER PRIMARY KEY,
  chapter_id INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  seconds REAL,
  cost_usd REAL NOT NULL DEFAULT 0,
  note TEXT
);
CREATE TABLE IF NOT EXISTS reading_state(
  chapter_id INTEGER PRIMARY KEY REFERENCES chapter(id) ON DELETE CASCADE,
  beat_id TEXT,
  y REAL NOT NULL DEFAULT 0,
  rate REAL,
  pace REAL,
  expressive INTEGER,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state(key TEXT PRIMARY KEY, value TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.LIBRARY.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    return con


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per unit of work; commits on success, rolls back on error."""
    con = connect()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with db() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"library.db is schema {version}, this app knows {SCHEMA_VERSION}")
        con.executescript(SCHEMA)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def recover_after_restart() -> int:
    """A chapter left 'processing' by a crash or restart goes back to the queue; it resumes from the first
    incomplete stage because every stage checks its own outputs. Returns how many were recovered."""
    with db() as con:
        cur = con.execute(
            "UPDATE chapter SET status='queued', stage=NULL, detail='resumed after restart', updated_at=? WHERE status='processing'",
            (now(),),
        )
        return cur.rowcount


# ---- paths: always derived from integer ids, never from user text ------------------------------------

def manga_dir(manga_id: int) -> Path:
    return config.LIBRARY / "manga" / str(int(manga_id))


def chapter_dir(manga_id: int, chapter_id: int) -> Path:
    return manga_dir(manga_id) / "chapters" / str(int(chapter_id))


def remove_tree(path: Path) -> None:
    """Delete a directory that must live inside the library."""
    resolved = path.resolve()
    if config.LIBRARY not in resolved.parents:
        raise ValueError(f"refusing to delete outside the library: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved, ignore_errors=False)
