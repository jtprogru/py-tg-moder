# -*- coding: utf-8 -*-
import logging
import os

from ruamel.yaml import YAML


cfg = dict()
yaml = YAML()


def __load_cfg(configfile='config.yaml'):
    global cfg
    with open(configfile, 'r') as fr:
        cfg = yaml.load(fr.read())


__load_cfg()

TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', None)
CHAT_RULES_URL: str = 'https://jtprog.ru/chat-rules/'

DEBUG: bool = bool(os.getenv('DEBUG', True))


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)

logger = logging.getLogger(__name__)
