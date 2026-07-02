import asyncio
import os
import sqlite3
from datetime import datetime, timezone

import pytest

from core import backups, config


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = tmp_path / "backups"
    monkeypatch.setattr(config, "BACKUP_DIR", str(d))
    monkeypatch.setattr(config, "BACKUP_KEEP", 3)
    return d


def _ts(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def _touch(directory, name):
    directory.mkdir(exist_ok=True)
    (directory / name).write_bytes(b"old")


# -- snapshot ---------------------------------------------------------------------


def test_snapshot_is_a_valid_sqlite_copy(backup_dir, audit_store):
    audit_store.add_warn(100, 42, moderator_id=1, reason="флуд")
    path = backups._make_snapshot(now=_ts(2026, 7, 2, 3, 0))
    assert os.path.basename(path) == "moder-20260702T030000Z.sqlite"
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM warns").fetchone()[0] == 1
    finally:
        conn.close()


def test_snapshot_overwrites_same_second_run(backup_dir, audit_store):
    now = _ts(2026, 7, 2, 3, 0)
    backups._make_snapshot(now=now)
    path = backups._make_snapshot(now=now)  # VACUUM INTO refuses to overwrite on its own
    assert os.path.exists(path)


# -- rotation ---------------------------------------------------------------------


def test_rotation_keeps_newest_and_ignores_foreign_files(backup_dir):
    for day in range(1, 6):
        _touch(backup_dir, f"moder-2026070{day}T030000Z.sqlite")
    _touch(backup_dir, "notes.txt")

    removed = backups._rotate_local()

    assert sorted(removed) == ["moder-20260701T030000Z.sqlite", "moder-20260702T030000Z.sqlite"]
    kept = sorted(os.listdir(backup_dir))
    assert kept == [
        "moder-20260703T030000Z.sqlite",
        "moder-20260704T030000Z.sqlite",
        "moder-20260705T030000Z.sqlite",
        "notes.txt",
    ]


# -- full run ---------------------------------------------------------------------


def test_backup_once_creates_file_and_audits(backup_dir, audit_store):
    meta = asyncio.run(backups.backup_once(actor_id=7))
    assert meta["file"].startswith("moder-") and meta["size"] > 0
    assert os.path.exists(backup_dir / meta["file"])
    assert "s3_key" not in meta and "s3_error" not in meta  # S3 not configured

    events = audit_store.list_audit_events(event="backup_created")
    assert len(events) == 1
    assert events[0]["actor_id"] == 7
    assert events[0]["meta"]["file"] == meta["file"]


@pytest.fixture
def s3_settings(monkeypatch):
    monkeypatch.setattr(config, "S3_ENDPOINT", "https://s3.example.com")
    monkeypatch.setattr(config, "S3_BUCKET", "bkt")
    monkeypatch.setattr(config, "S3_PREFIX", "p/")
    monkeypatch.setattr(config, "S3_ACCESS_KEY", "AK")
    monkeypatch.setattr(config, "S3_SECRET_KEY", "SK")


class FakeS3:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.puts = []
        self.deleted = []
        FakeS3.last = self

    def put_object(self, key, body):
        self.puts.append((key, len(body)))

    def list_keys(self, prefix):
        return [
            "p/moder-20260628T030000Z.sqlite",
            "p/moder-20260629T030000Z.sqlite",
            "p/moder-20260630T030000Z.sqlite",
            "p/moder-20260701T030000Z.sqlite",
            "p/notes.txt",
        ]

    def delete_object(self, key):
        self.deleted.append(key)


def test_mirror_uploads_and_rotates_bucket(backup_dir, audit_store, s3_settings, monkeypatch):
    monkeypatch.setattr(backups, "S3Client", FakeS3)

    meta = asyncio.run(backups.backup_once())

    client = FakeS3.last
    assert client.puts == [(f"p/{meta['file']}", meta["size"])]
    # keep=3: the oldest backup key goes, foreign keys under the prefix stay.
    assert client.deleted == ["p/moder-20260628T030000Z.sqlite"]
    assert meta["s3_key"] == f"p/{meta['file']}"


def test_backup_survives_s3_failure(backup_dir, audit_store, s3_settings, monkeypatch):
    class ExplodingS3(FakeS3):
        def put_object(self, key, body):
            raise RuntimeError("boom")

    monkeypatch.setattr(backups, "S3Client", ExplodingS3)

    meta = asyncio.run(backups.backup_once())

    assert meta["s3_error"] is True
    assert os.path.exists(backup_dir / meta["file"])  # local snapshot intact
    assert audit_store.list_audit_events(event="backup_created")[0]["meta"]["s3_error"] is True


# -- startup catch-up and loop ----------------------------------------------------


def test_due_on_startup_when_no_backups(backup_dir):
    assert backups._due_on_startup() is True


def test_not_due_with_fresh_backup(backup_dir):
    _touch(backup_dir, "moder-20260702T030000Z.sqlite")
    assert backups._due_on_startup() is False


def test_due_again_once_newest_is_a_day_old(backup_dir):
    name = "moder-20260701T030000Z.sqlite"
    _touch(backup_dir, name)
    day_ago = int(os.stat(backup_dir / name).st_mtime) - 86400
    os.utime(backup_dir / name, (day_ago, day_ago))
    assert backups._due_on_startup() is True


def test_loop_catches_up_on_startup(backup_dir, audit_store, monkeypatch):
    monkeypatch.setattr(backups, "seconds_until", lambda hour: 3600)

    async def scenario():
        task = asyncio.create_task(backups.backup_loop())
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(scenario())
    assert len(backups.list_local_backups()) == 1


def test_loop_skips_startup_backup_when_fresh(backup_dir, audit_store, monkeypatch):
    _touch(backup_dir, "moder-20260702T030000Z.sqlite")
    monkeypatch.setattr(backups, "seconds_until", lambda hour: 3600)

    async def scenario():
        task = asyncio.create_task(backups.backup_loop())
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(scenario())
    assert audit_store.list_audit_events(event="backup_created") == []


def test_start_backups_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "BACKUP_ENABLED", False)
    monkeypatch.setattr(backups, "_task", None)

    async def scenario():
        backups.start_backups(None)

    asyncio.run(scenario())
    assert backups._task is None
