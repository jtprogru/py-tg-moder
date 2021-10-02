# py-tg-moder

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Docker](https://github.com/jtprogru/py-tg-moder/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/jtprogru/py-tg-moder/actions/workflows/docker-publish.yml)
[![Testing](https://github.com/jtprogru/py-tg-moder/actions/workflows/testing.yml/badge.svg)](https://github.com/jtprogru/py-tg-moder/actions/workflows/testing.yml)
[![Deploy](https://github.com/jtprogru/py-tg-moder/actions/workflows/deploy-k8s.yml/badge.svg)](https://github.com/jtprogru/py-tg-moder/actions/workflows/deploy-k8s.yml)
[![GitHub stars](https://img.shields.io/github/stars/jtprogru/py-tg-moder.svg)](https://github.com/jtprogru/py-tg-moder/stargazers)
[![GitHub issues](https://img.shields.io/github/issues-raw/jtprogru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/issues)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/jtprogru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/releases/latest)
[![GitHub](https://img.shields.io/github/license/jtprgoru/py-tg-moder)](https://github.com/jtprogru/py-tg-moder/)
[![Wiki](https://img.shields.io/badge/Wiki-READ-success)](https://github.com/jtprogru/py-tg-moder/wiki)

Бот-модератор для чата [@jtprgoru_chat](https://t.me/jtprgoru_chat)

Умеет пока не так много, но начало положено.

## Documentation

Вся документация, а так же основные "хотелки на перспективу" фиксируются в [Wiki](https://github.com/jtprogru/py-tg-moder/wiki) этого проекта. 

## Environment Variables

Перед запуском создать файлик `src/.env` с содержимым:
```ini
export TELEGRAM_BOT_TOKEN='1234567890:qwertyuiopHGVBNVJHVJVMNBVMNBVposdfghi'
export VERSION=0.1.2
export SENTRY_DSN="https://xxxxjkhkjahsdkjashd@o444444.ingest.sentry.io/1234567"
```

## Run locally 

Развернут на домашнем Docker Swarm через [Portainer](https://portainer.io). Запустить с помощью `docker compose up -d`: 

```yaml
---
version: '3.7'
services:
  bot:
    image: ghcr.io/jtprogru/py-tg-moder:latest
    env_file:
      - ./src/.env
```

## Feedback

Если случилось так, что ты начал использовать и у тебя есть фидбэк, пожалуйста создай [issues](https://github.com/jtprogru/py-tg-moder/issues) или обратись в Telegram-чат [jtprogru_chat)](https://t.me/jtprogru_chat).

## Authors

- Michael Savin
  - :octocat: [@jtprogru](https://www.github.com/jtprogru)
  - :bird: [@jtprogru](https://www.twitter.com/jtprogru)
  - :moneybag: [savinmi.ru](https://savinmi.ru)
