import core.cas as cas_module
from core.cas import casapi


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_check_ok(monkeypatch):
    monkeypatch.setattr(cas_module.requests, "get", lambda url, **kwargs: FakeResponse(200, {"ok": True}))
    assert casapi.check(user_id=123) == {"ok": True}


def test_check_not_found(monkeypatch):
    monkeypatch.setattr(cas_module.requests, "get", lambda url, **kwargs: FakeResponse(404, {}))
    result = casapi.check(user_id=123)
    assert result["ok"] is False
    assert "description" in result


def test_check_network_error_fails_open(monkeypatch):
    def _boom(url, **kwargs):
        raise cas_module.requests.RequestException("boom")

    monkeypatch.setattr(cas_module.requests, "get", _boom)
    result = casapi.check(user_id=123)
    assert result["ok"] is False
    assert "description" in result


class _BadJsonResponse:
    status_code = 200

    def json(self):
        raise ValueError("no json")


def test_check_malformed_json_fails_open(monkeypatch):
    # A 200 with a body that isn't JSON must not crash the join flow.
    monkeypatch.setattr(cas_module.requests, "get", lambda url, **kwargs: _BadJsonResponse())
    result = casapi.check(user_id=123)
    assert result["ok"] is False
    assert "description" in result
