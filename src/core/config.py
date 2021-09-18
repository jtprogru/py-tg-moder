# -*- coding: utf-8 -*-
import os

from ruamel.yaml import YAML

cfg = dict()
yaml = YAML()


def __load_cfg(configfile='config.yaml'):
    global cfg
    with open(configfile, 'r') as fr:
        cfg = yaml.load(fr.read())


__load_cfg()

TELEGRAM_BOT_OWNER: int = int(os.getenv('TELEGRAM_BOT_OWNER'))
TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_RULES_URL: str = 'https://jtprog.ru/chat-rules/'

DEBUG: bool = bool(os.getenv('DEBUG'))
