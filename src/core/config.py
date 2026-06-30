# -*- coding: utf-8 -*-
import logging
import os
from typing import Optional

from ruamel.yaml import YAML

cfg = dict()
yaml = YAML()

# config.yaml lives next to the package root (src/config.yaml), one level up
# from this module (src/core/). Resolving it relative to __file__ keeps loading
# independent of the current working directory (local runs, Docker, pytest).
_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def __load_cfg(configfile=_DEFAULT_CONFIG):
    global cfg
    with open(configfile, "r") as fr:
        cfg = yaml.load(fr.read())


__load_cfg()

TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_RULES_URL: str = "https://jtprog.ru/chat-rules/"

# Chats (numeric id or @username) the bot is allowed to operate in.
ALLOWED_CHATS: list = list(cfg.get("allowed_chats", []) or [])

# Human-readable handle of the chat this bot serves, shown in /start and /help.
MAIN_GROUP: str = next((str(c) for c in ALLOWED_CHATS if str(c).startswith("@")), "")

# Moderation behaviour toggles.
DELETE_ON_BAN: bool = bool(cfg.get("moderation", {}).get("delete_on_ban", True))

# Warns before an automatic punishment, and what that punishment is (mute|ban).
WARN_LIMIT: int = int(cfg.get("moderation", {}).get("warn_limit", 3))
_warn_action: str = str(cfg.get("moderation", {}).get("warn_action", "mute")).lower()
WARN_ACTION: str = _warn_action if _warn_action in {"mute", "ban"} else "mute"

# Content filter for messages from newcomers (links/forwards/mentions/invites).
_newcomer: dict = cfg.get("moderation", {}).get("newcomer_filter", {}) or {}
NEWCOMER_FILTER_ENABLED: bool = bool(_newcomer.get("enabled", True))
NEWCOMER_MAX_MESSAGES: int = int(_newcomer.get("max_messages", 5))
NEWCOMER_MAX_AGE: int = int(_newcomer.get("max_age_seconds", 86400))
_newcomer_action: str = str(_newcomer.get("action", "delete")).lower()
NEWCOMER_ACTION: str = _newcomer_action if _newcomer_action in {"delete", "mute", "warn"} else "delete"
NEWCOMER_BLOCK_LINKS: bool = bool(_newcomer.get("block_links", True))
NEWCOMER_BLOCK_FORWARDS: bool = bool(_newcomer.get("block_forwards", True))
NEWCOMER_BLOCK_MENTIONS: bool = bool(_newcomer.get("block_mentions", True))

# Flood control: >limit messages within window_seconds -> temporary mute.
_flood: dict = cfg.get("moderation", {}).get("flood", {}) or {}
FLOOD_ENABLED: bool = bool(_flood.get("enabled", True))
FLOOD_LIMIT: int = int(_flood.get("limit", 7))
FLOOD_WINDOW: int = int(_flood.get("window_seconds", 10))
FLOOD_MUTE_SECONDS: int = int(_flood.get("mute_seconds", 60))

# Captcha / verification of new members.
_captcha: dict = cfg.get("moderation", {}).get("captcha", {}) or {}
CAPTCHA_ENABLED: bool = bool(_captcha.get("enabled", True))
CAPTCHA_TIMEOUT: int = int(_captcha.get("timeout_seconds", 60))
_captcha_fail: str = str(_captcha.get("fail_action", "kick")).lower()
CAPTCHA_FAIL_ACTION: str = _captcha_fail if _captcha_fail in {"kick", "ban"} else "kick"

# Managed media deletion: which media types to delete from non-admins.
_media: dict = cfg.get("moderation", {}).get("media", {}) or {}
MEDIA_ENABLED: bool = bool(_media.get("enabled", True))
MEDIA_NOTIFY: bool = bool(_media.get("notify", True))
MEDIA_NOTIFY_TTL: int = int(_media.get("notify_ttl_seconds", 15))
MEDIA_BLOCK_VOICE: bool = bool(_media.get("block_voice", True))
MEDIA_BLOCK_VIDEO: bool = bool(_media.get("block_video", True))
MEDIA_BLOCK_VIDEO_NOTE: bool = bool(_media.get("block_video_note", True))
MEDIA_BLOCK_LOCATION: bool = bool(_media.get("block_location", True))

# Path to the SQLite database that holds moderation state (warns, mutes, stats).
# Env DB_PATH wins over config.yaml so deployments can point it at a mounted
# volume without touching the image.
DB_PATH: str = os.getenv("DB_PATH") or str(cfg.get("storage", {}).get("path", "moder.db"))

DEBUG: bool = _parse_bool(os.getenv("DEBUG"))
SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")

# Single, project-wide logging configuration.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if DEBUG else logging.INFO,
)

logger = logging.getLogger(__name__)
