# -*- coding: utf-8 -*-
import logging
import os
from typing import Optional

from ruamel.yaml import YAML

cfg = dict()
yaml = YAML()


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def __load_cfg(configfile="config.yaml"):
    global cfg
    with open(configfile, "r") as fr:
        cfg = yaml.load(fr.read())


__load_cfg()

TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_RULES_URL: str = "https://jtprog.ru/chat-rules/"

DEBUG: bool = _parse_bool(os.getenv("DEBUG"))
SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")

# Single, project-wide logging configuration.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if DEBUG else logging.INFO,
)

logger = logging.getLogger(__name__)
