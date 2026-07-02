# -*- coding: utf-8 -*-
"""Shared Jinja2 environment for the dashboard (single instance, one place)."""

import os
from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _format_ts(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


templates.env.filters["ts"] = _format_ts
