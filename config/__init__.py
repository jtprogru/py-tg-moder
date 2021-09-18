# coding=utf-8

import os


TELEGRAM_BOT_TOKEN: str = os.getenv('BOT_TOKEN')
MASTER_ADMIN_ID: int = int(os.getenv('MASTER_ADMIN_ID'))
ADMIN_LIST: list = [int(MASTER_ADMIN_ID), ]
CHAT_ID: str = os.getenv('CHAT_ID')
LINK_CHAT_RULES: str = 'https://jtprog.ru/chat-rules/'
LOG_FILE_PATH: str = '/bot/bot.log'
SENTRY_DSN: str = 'https://7a98c5baf52c4c339e7eb6b9df8e1c51@o412493.ingest.sentry.io/5351952'
