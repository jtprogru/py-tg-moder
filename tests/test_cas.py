import core.cas as cas_module
from core.cas import casapi


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_check_ok(monkeypatch):
    monkeypatch.setattr(cas_module.requests, "get", lambda url: FakeResponse(200, {"ok": True}))
    assert casapi.check(user_id=123) == {"ok": True}


def test_check_not_found(monkeypatch):
    monkeypatch.setattr(cas_module.requests, "get", lambda url: FakeResponse(404, {}))
    result = casapi.check(user_id=123)
    assert result["ok"] is False
    assert "description" in result
