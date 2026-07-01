# -*- coding: utf-8 -*-
"""SQLite persistence layer.

A thin repository over a single SQLite database so handlers never touch SQL
directly. The store keeps moderation state that must survive a bot restart:
member activity ("newness" + stats), warns, active mutes and free-form
counters.

The repository is synchronous; async handlers should call it through
``asyncio.to_thread`` (the same pattern the CAS client already uses). The
connection is opened with ``check_same_thread=False`` and guarded by a lock so
it is safe to use from the thread pool.
"""

import os
import sqlite3
import threading
import time
from typing import Optional

from core.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    chat_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    first_seen    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS warns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    moderator_id  INTEGER,
    reason        TEXT,
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warns_chat_user ON warns (chat_id, user_id);

CREATE TABLE IF NOT EXISTS mutes (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    until       INTEGER,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS counters (
    chat_id INTEGER NOT NULL,
    name    TEXT NOT NULL,
    value   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, name)
);

CREATE TABLE IF NOT EXISTS usernames (
    username TEXT PRIMARY KEY,
    user_id  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS captchas (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    deadline   INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
"""


def _now(now: Optional[int]) -> int:
    return int(time.time()) if now is None else now


class Storage:
    """Repository over a SQLite database."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            if self.path != ":memory:":
                # Better read/write concurrency for a long-running process.
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- members: "newness" + activity stats -----------------------------------

    def record_member(self, chat_id: int, user_id: int, now: Optional[int] = None) -> None:
        """Remember when a user was first seen in a chat (no-op if already known)."""
        ts = _now(now)
        with self._lock:
            self._conn.execute(
                "INSERT INTO members (chat_id, user_id, first_seen, last_seen) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id, user_id) DO NOTHING",
                (chat_id, user_id, ts, ts),
            )
            self._conn.commit()

    def touch_member(self, chat_id: int, user_id: int, now: Optional[int] = None) -> int:
        """Count a message from a user, returning the new message count."""
        ts = _now(now)
        with self._lock:
            self._conn.execute(
                "INSERT INTO members (chat_id, user_id, first_seen, last_seen, message_count) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, message_count = message_count + 1",
                (chat_id, user_id, ts, ts),
            )
            row = self._conn.execute(
                "SELECT message_count FROM members WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
            self._conn.commit()
        return row["message_count"]

    def get_member(self, chat_id: int, user_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT chat_id, user_id, first_seen, last_seen, message_count FROM members WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def is_new_member(
        self,
        chat_id: int,
        user_id: int,
        max_messages: int = 5,
        max_age_seconds: int = 86400,
        now: Optional[int] = None,
    ) -> bool:
        """Treat unknown users and users still within their grace window as new.

        A user is "new" until they have either sent ``max_messages`` messages or
        been known for ``max_age_seconds`` — whichever comes first.
        """
        member = self.get_member(chat_id, user_id)
        if member is None:
            return True
        if member["message_count"] >= max_messages:
            return False
        return _now(now) - member["first_seen"] < max_age_seconds

    # -- warns -----------------------------------------------------------------

    def add_warn(
        self,
        chat_id: int,
        user_id: int,
        moderator_id: Optional[int] = None,
        reason: Optional[str] = None,
        now: Optional[int] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO warns (chat_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, user_id, moderator_id, reason, _now(now)),
            )
            self._conn.commit()
            return cur.lastrowid

    def count_warns(self, chat_id: int, user_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM warns WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
        return row["n"]

    def list_warns(self, chat_id: int, user_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, chat_id, user_id, moderator_id, reason, created_at FROM warns WHERE chat_id = ? AND user_id = ? ORDER BY id",
                (chat_id, user_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def remove_last_warn(self, chat_id: int, user_id: int) -> bool:
        """Drop the most recent warn for a user; return True if one was removed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM warns WHERE chat_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                (chat_id, user_id),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute("DELETE FROM warns WHERE id = ?", (row["id"],))
            self._conn.commit()
        return True

    def clear_warns(self, chat_id: int, user_id: int) -> int:
        """Remove all warns for a user; return how many were removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM warns WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount

    # -- mutes -----------------------------------------------------------------

    def add_mute(
        self,
        chat_id: int,
        user_id: int,
        until: Optional[int] = None,
        now: Optional[int] = None,
    ) -> None:
        """Record an active mute. ``until`` is a unix timestamp, or None for indefinite."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO mutes (chat_id, user_id, until, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET until = excluded.until, created_at = excluded.created_at",
                (chat_id, user_id, until, _now(now)),
            )
            self._conn.commit()

    def remove_mute(self, chat_id: int, user_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def is_muted(self, chat_id: int, user_id: int, now: Optional[int] = None) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT until FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
        if row is None:
            return False
        return row["until"] is None or row["until"] > _now(now)

    def get_active_mutes(self, now: Optional[int] = None) -> list[dict]:
        """Return mutes that are still in effect (used to rearm timers on startup)."""
        ts = _now(now)
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id, user_id, until, created_at FROM mutes WHERE until IS NULL OR until > ? ORDER BY chat_id, user_id",
                (ts,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- counters / stats ------------------------------------------------------

    def increment_counter(self, chat_id: int, name: str, amount: int = 1) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO counters (chat_id, name, value) VALUES (?, ?, ?) ON CONFLICT(chat_id, name) DO UPDATE SET value = value + excluded.value",
                (chat_id, name, amount),
            )
            row = self._conn.execute(
                "SELECT value FROM counters WHERE chat_id = ? AND name = ?",
                (chat_id, name),
            ).fetchone()
            self._conn.commit()
        return row["value"]

    def get_counter(self, chat_id: int, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM counters WHERE chat_id = ? AND name = ?",
                (chat_id, name),
            ).fetchone()
        return row["value"] if row else 0

    # -- username -> id cache --------------------------------------------------

    def remember_user(self, user_id: int, username: Optional[str]) -> None:
        """Cache a @username -> user_id mapping so commands can target by name.

        The Bot API can't resolve usernames on demand, so we remember the ones
        we see. No-op for users without a username.
        """
        if not username:
            return
        uname = username.lower().lstrip("@")
        with self._lock:
            self._conn.execute(
                "INSERT INTO usernames (username, user_id) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET user_id = excluded.user_id",
                (uname, user_id),
            )
            self._conn.commit()

    def resolve_username(self, username: str) -> Optional[int]:
        """Return the cached user_id for a @username, or None if never seen."""
        uname = username.lower().lstrip("@")
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM usernames WHERE username = ?",
                (uname,),
            ).fetchone()
        return row["user_id"] if row else None

    # -- pending captcha challenges --------------------------------------------

    def add_captcha(self, chat_id: int, user_id: int, message_id: int, deadline: int) -> None:
        """Persist a pending captcha so it can be rearmed after a restart.

        ``deadline`` is the unix timestamp by which the user must pass, and
        ``message_id`` is the challenge message so it can be removed later.
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO captchas (chat_id, user_id, message_id, deadline) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET message_id = excluded.message_id, deadline = excluded.deadline",
                (chat_id, user_id, message_id, deadline),
            )
            self._conn.commit()

    def remove_captcha(self, chat_id: int, user_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM captchas WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def list_captchas(self) -> list[dict]:
        """Return all pending captcha challenges (used to rearm timers on startup)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id, user_id, message_id, deadline FROM captchas ORDER BY chat_id, user_id",
            ).fetchall()
        return [dict(r) for r in rows]


_storage: Optional[Storage] = None
_storage_lock = threading.Lock()


def get_storage() -> Storage:
    """Return the process-wide storage, creating it on first use.

    Lazy so importing this module has no side effects (no DB file is created
    until something actually needs the store).
    """
    global _storage
    if _storage is None:
        with _storage_lock:
            if _storage is None:
                _storage = Storage(DB_PATH)
    return _storage
