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

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
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

# The baseline schema above is frozen. Every later change lives here as a
# migration script; ``PRAGMA user_version`` records how many have been applied,
# so the same code path upgrades existing databases and freshly created ones.
_MIGRATIONS: list[str] = [
    # v1: audit log, per-day message stats, soft-delete for warns.
    """
    ALTER TABLE warns ADD COLUMN deleted_at INTEGER;
    CREATE INDEX idx_warns_active ON warns (chat_id, user_id) WHERE deleted_at IS NULL;

    CREATE TABLE audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id    INTEGER NOT NULL,
        user_id    INTEGER,            -- target; NULL for chat-level events
        actor_id   INTEGER,            -- moderator / web admin; NULL = bot automation
        event      TEXT NOT NULL,
        reason     TEXT,
        meta       TEXT,               -- JSON blob with event-specific details
        created_at INTEGER NOT NULL
    );
    CREATE INDEX idx_audit_chat_time  ON audit_log (chat_id, created_at);
    CREATE INDEX idx_audit_event_time ON audit_log (event, created_at);
    CREATE INDEX idx_audit_chat_user  ON audit_log (chat_id, user_id, created_at);

    CREATE TABLE message_stats (
        chat_id INTEGER NOT NULL,
        day     TEXT    NOT NULL,     -- UTC 'YYYY-MM-DD'
        user_id INTEGER NOT NULL,
        count   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chat_id, day, user_id)
    );
    CREATE INDEX idx_msgstats_chat_day ON message_stats (chat_id, day);
    """,
]


def _utc_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


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
            self._migrate()

    def _migrate(self) -> None:
        """Apply pending migrations; ``PRAGMA user_version`` gates what already ran."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            self._conn.executescript(script)
            self._conn.execute(f"PRAGMA user_version = {number}")
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
        """Count a user's active (not soft-deleted) warns."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM warns WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL",
                (chat_id, user_id),
            ).fetchone()
        return row["n"]

    def list_warns(self, chat_id: int, user_id: int, include_deleted: bool = False) -> list[dict]:
        """Return a user's warns, oldest first; soft-deleted ones only on request."""
        query = "SELECT id, chat_id, user_id, moderator_id, reason, created_at, deleted_at FROM warns WHERE chat_id = ? AND user_id = ?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        with self._lock:
            rows = self._conn.execute(f"{query} ORDER BY id", (chat_id, user_id)).fetchall()
        return [dict(r) for r in rows]

    def remove_last_warn(self, chat_id: int, user_id: int, now: Optional[int] = None) -> bool:
        """Soft-delete the most recent active warn; return True if one was removed.

        Rows are kept for history/analytics and hard-deleted later by retention.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM warns WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                (chat_id, user_id),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute("UPDATE warns SET deleted_at = ? WHERE id = ?", (_now(now), row["id"]))
            self._conn.commit()
        return True

    def clear_warns(self, chat_id: int, user_id: int, now: Optional[int] = None) -> int:
        """Soft-delete all active warns for a user; return how many were affected."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE warns SET deleted_at = ? WHERE chat_id = ? AND user_id = ? AND deleted_at IS NULL",
                (_now(now), chat_id, user_id),
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

    # -- audit log ---------------------------------------------------------------

    def add_audit_event(
        self,
        chat_id: int,
        event: str,
        user_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        reason: Optional[str] = None,
        meta: Optional[dict] = None,
        now: Optional[int] = None,
    ) -> int:
        """Append an event to the audit log; ``meta`` is stored as a JSON blob."""
        payload = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit_log (chat_id, user_id, actor_id, event, reason, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, actor_id, str(event), reason, payload, _now(now)),
            )
            self._conn.commit()
            return cur.lastrowid

    def list_audit_events(
        self,
        chat_id: Optional[int] = None,
        event: Optional[str] = None,
        user_id: Optional[int] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return audit events, newest first, filtered by any combination of args."""
        clauses: list[str] = []
        params: list = []
        for clause, value in (
            ("chat_id = ?", chat_id),
            ("event = ?", event),
            ("user_id = ?", user_id),
            ("created_at >= ?", since),
            ("created_at < ?", until),
        ):
            if value is not None:
                clauses.append(clause)
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, chat_id, user_id, actor_id, event, reason, meta, created_at FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["meta"] = json.loads(item["meta"]) if item["meta"] is not None else None
            events.append(item)
        return events

    # -- per-day message statistics ----------------------------------------------

    def record_message_stat(self, chat_id: int, user_id: int, now: Optional[int] = None) -> None:
        """Count a message towards the per-day statistics (UTC day buckets)."""
        day = _utc_day(_now(now))
        with self._lock:
            self._conn.execute(
                "INSERT INTO message_stats (chat_id, day, user_id, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(chat_id, day, user_id) DO UPDATE SET count = count + 1",
                (chat_id, day, user_id),
            )
            self._conn.commit()

    # -- retention -----------------------------------------------------------------

    @staticmethod
    def _retention_cutoffs(retention_days: int, now: Optional[int] = None) -> tuple[int, str]:
        """Cutoff as (unix ts, YYYY-MM-DD): start of the UTC day ``retention_days`` back."""
        cutoff_day = datetime.fromtimestamp(_now(now), tz=timezone.utc).date() - timedelta(days=retention_days)
        cutoff_ts = int(datetime(cutoff_day.year, cutoff_day.month, cutoff_day.day, tzinfo=timezone.utc).timestamp())
        return cutoff_ts, cutoff_day.strftime("%Y-%m-%d")

    def purge_old_data(self, retention_days: int, now: Optional[int] = None) -> dict[str, int]:
        """Hard-delete history older than ``retention_days`` (whole UTC days).

        Only history is touched: audit events, soft-deleted warns and per-day
        message stats. Live moderation state (active warns, mutes, members,
        captchas, username cache, counters) is never purged. Returns the number
        of rows removed per table.
        """
        cutoff_ts, cutoff_date = self._retention_cutoffs(retention_days, now)
        with self._lock:
            counts = {
                "audit_log": self._conn.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff_ts,)).rowcount,
                "warns": self._conn.execute("DELETE FROM warns WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff_ts,)).rowcount,
                "message_stats": self._conn.execute("DELETE FROM message_stats WHERE day < ?", (cutoff_date,)).rowcount,
            }
            self._conn.commit()
        return counts

    def purge_counts(self, retention_days: int, now: Optional[int] = None) -> dict[str, int]:
        """Dry run of :meth:`purge_old_data`: how many rows *would* be deleted."""
        cutoff_ts, cutoff_date = self._retention_cutoffs(retention_days, now)
        with self._lock:
            return {
                "audit_log": self._conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE created_at < ?", (cutoff_ts,)).fetchone()["n"],
                "warns": self._conn.execute("SELECT COUNT(*) AS n FROM warns WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff_ts,)).fetchone()["n"],
                "message_stats": self._conn.execute("SELECT COUNT(*) AS n FROM message_stats WHERE day < ?", (cutoff_date,)).fetchone()["n"],
            }

    def vacuum(self) -> None:
        """Compact the database file (reclaims pages freed by purges).

        Briefly blocks other writers — acceptable for this single-instance bot.
        """
        with self._lock:
            self._conn.commit()  # VACUUM refuses to run inside a transaction
            self._conn.execute("VACUUM")

    # -- dashboard aggregates ------------------------------------------------------

    def list_chats(self) -> list[int]:
        """Chat ids present anywhere in the data (members, audit log or stats)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id FROM members UNION SELECT chat_id FROM audit_log UNION SELECT chat_id FROM message_stats ORDER BY chat_id",
            ).fetchall()
        return [r["chat_id"] for r in rows]

    def member_totals(self, chat_id: int, now: Optional[int] = None) -> dict:
        """Headline numbers for a chat: known members, active mutes, pending captchas."""
        ts = _now(now)
        with self._lock:
            members = self._conn.execute("SELECT COUNT(*) AS n FROM members WHERE chat_id = ?", (chat_id,)).fetchone()["n"]
            mutes = self._conn.execute(
                "SELECT COUNT(*) AS n FROM mutes WHERE chat_id = ? AND (until IS NULL OR until > ?)",
                (chat_id, ts),
            ).fetchone()["n"]
            captchas = self._conn.execute("SELECT COUNT(*) AS n FROM captchas WHERE chat_id = ?", (chat_id,)).fetchone()["n"]
        return {"members": members, "active_mutes": mutes, "pending_captchas": captchas}

    def message_series(self, chat_id: int, since_day: str) -> list[dict]:
        """Daily message totals for a chat since a UTC day (inclusive), oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, SUM(count) AS count FROM message_stats WHERE chat_id = ? AND day >= ? GROUP BY day ORDER BY day",
                (chat_id, since_day),
            ).fetchall()
        return [dict(r) for r in rows]

    def top_posters(self, chat_id: int, since_day: str, limit: int = 10) -> list[dict]:
        """Most active users in a chat since a UTC day (inclusive)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, SUM(count) AS count FROM message_stats WHERE chat_id = ? AND day >= ? GROUP BY user_id ORDER BY count DESC, user_id LIMIT ?",
                (chat_id, since_day, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def audit_series(self, chat_id: int, since: int) -> list[dict]:
        """Per-day, per-event counts from the audit log since a unix ts, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT strftime('%Y-%m-%d', created_at, 'unixepoch') AS day, event, COUNT(*) AS count "
                "FROM audit_log WHERE chat_id = ? AND created_at >= ? GROUP BY day, event ORDER BY day",
                (chat_id, since),
            ).fetchall()
        return [dict(r) for r in rows]

    def audit_totals(self, chat_id: int, since: int) -> dict[str, int]:
        """Total count per event type from the audit log since a unix ts."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT event, COUNT(*) AS count FROM audit_log WHERE chat_id = ? AND created_at >= ? GROUP BY event",
                (chat_id, since),
            ).fetchall()
        return {r["event"]: r["count"] for r in rows}

    def count_audit_events(
        self,
        chat_id: Optional[int] = None,
        event: Optional[str] = None,
        user_id: Optional[int] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> int:
        """Total rows matching the same filters as ``list_audit_events`` (for pagination)."""
        clauses: list[str] = []
        params: list = []
        for clause, value in (
            ("chat_id = ?", chat_id),
            ("event = ?", event),
            ("user_id = ?", user_id),
            ("created_at >= ?", since),
            ("created_at < ?", until),
        ):
            if value is not None:
                clauses.append(clause)
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM audit_log {where}", params).fetchone()
        return row["n"]

    def top_warned(self, chat_id: int, since: int, limit: int = 10) -> list[dict]:
        """Users with the most warns (including soft-deleted history) since a unix ts."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, COUNT(*) AS count FROM warns WHERE chat_id = ? AND created_at >= ? GROUP BY user_id ORDER BY count DESC, user_id LIMIT ?",
                (chat_id, since, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def usernames_map(self, user_ids: list[int]) -> dict[int, str]:
        """Best-effort user_id -> @username for display (only cached names)."""
        if not user_ids:
            return {}
        placeholders = ",".join("?" for _ in user_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT username, user_id FROM usernames WHERE user_id IN ({placeholders})",
                list(user_ids),
            ).fetchall()
        return {r["user_id"]: r["username"] for r in rows}

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
