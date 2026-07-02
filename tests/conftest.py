import os
import sys

import pytest

# Make the bot's source root importable (bot.py imports `core.*`, `handlers.*`)
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def audit_store(monkeypatch):
    """Give every test an in-memory storage for audit events.

    Handlers record audit events through ``core.audit.get_storage`` (not the
    per-module ``get_storage`` the tests monkeypatch), so without this fixture
    instrumented handlers would create a real ``moder.db`` during tests. The
    process-wide singleton is patched too, so any unpatched ``get_storage()``
    call stays in memory. Request the fixture by name to assert on audit rows.
    """
    from core import audit, storage
    from core.storage import Storage

    s = Storage(":memory:")
    monkeypatch.setattr(audit, "get_storage", lambda: s)
    monkeypatch.setattr(storage, "_storage", s)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _fresh_raid_tracker(monkeypatch):
    """Give every test a clean raid tracker — the module singleton would leak
    an activated raid mode from one test into the next."""
    from core import config, raid

    monkeypatch.setattr(raid, "_tracker", raid.RaidTracker(config.RAID_JOIN_LIMIT, config.RAID_WINDOW, config.RAID_DURATION))
