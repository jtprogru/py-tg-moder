from core.duration import format_duration, parse_duration


def test_parse_single_units():
    assert parse_duration("30m") == 1800
    assert parse_duration("1h") == 3600
    assert parse_duration("1d") == 86400
    assert parse_duration("45s") == 45


def test_parse_combined():
    assert parse_duration("1h30m") == 5400
    assert parse_duration("1d2h") == 93600


def test_parse_invalid_returns_none():
    assert parse_duration(None) is None
    assert parse_duration("") is None
    assert parse_duration("forever") is None
    assert parse_duration("0m") is None  # zero -> no real duration


def test_parse_case_insensitive_and_spaces():
    assert parse_duration("1H") == 3600
    assert parse_duration("2 h") == 7200


def test_format_duration():
    assert format_duration(1800) == "30 мин"
    assert format_duration(3600) == "1 ч"
    assert format_duration(5400) == "1 ч 30 мин"
    assert format_duration(86400) == "1 д"
