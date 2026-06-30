"""Parsing and formatting of human durations like ``30m``, ``1h``, ``1d``."""

import re
from typing import Optional

_DURATION_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_FORMAT_UNITS = ((86400, "д"), (3600, "ч"), (60, "мин"), (1, "с"))


def parse_duration(text: Optional[str]) -> Optional[int]:
    """Parse a duration into seconds.

    Accepts one or more ``<number><unit>`` tokens (s/m/h/d), e.g. ``30m``,
    ``1h``, ``1d``, ``1h30m``. Returns the total in seconds, or ``None`` if the
    text contains no valid token (so callers can treat it as "no duration").
    """
    if not text:
        return None
    total = 0
    matched = False
    for number, unit in _DURATION_RE.findall(text):
        total += int(number) * _UNIT_SECONDS[unit.lower()]
        matched = True
    return total if matched and total > 0 else None


def format_duration(seconds: int) -> str:
    """Render seconds as a short human string, e.g. 5400 -> ``1 ч 30 мин``."""
    parts = []
    for unit_seconds, label in _FORMAT_UNITS:
        if seconds >= unit_seconds:
            quantity, seconds = divmod(seconds, unit_seconds)
            parts.append(f"{quantity} {label}")
    return " ".join(parts) if parts else "0 с"
