import asyncio
from types import SimpleNamespace

import handlers.service_handlers as service_handlers


class FakeMessage:
    def __init__(self):
        self.from_user = SimpleNamespace(id=42)
        self.deleted = False
        self.replies = []

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def _update(message):
    return SimpleNamespace(message=message, effective_message=message)


def test_delete_bad_message_removes_service_message():
    message = FakeMessage()
    asyncio.run(service_handlers.delete_bad_message(_update(message), None))
    assert message.deleted is True


def test_ping_replies_pong():
    message = FakeMessage()
    asyncio.run(service_handlers.ping(_update(message), None))
    assert message.replies and "pong" in message.replies[0]


def test_errors_logging_logs_error(caplog):
    ctx = SimpleNamespace(error=ValueError("boom"))
    with caplog.at_level("WARNING"):
        asyncio.run(service_handlers.errors_logging("update-repr", ctx))
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_errors_logging_skips_not_modified_warning(caplog):
    # "Message is not modified" is benign and must not be logged at WARNING.
    ctx = SimpleNamespace(error=SimpleNamespace(message="Message is not modified"))
    with caplog.at_level("WARNING"):
        asyncio.run(service_handlers.errors_logging("update-repr", ctx))
    assert not any('caused error' in r.getMessage() for r in caplog.records if r.levelname == "WARNING")
