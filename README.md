# py-tg-moder

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


Бот-модератор для чата [@jtprgoru_chat](https://t.me/jtprgoru_chat)

Умеет пока не так много, но начало положено.

Перед запуском создать файлик `src/.env` с содержимым:
```ini
export TELEGRAM_BOT_TOKEN='1234567890:qwertyuiopHGVBNVJHVJVMNBVMNBVposdfghi'
export VERSION=0.1.2
```

Развернут на домашнем Docker Swarm через [Portainer](https://portainer.io). Запустить с помощью `docker compose up -d`: 

```yaml
---
version: '3.7'
services:
  bot:
    image: ghcr.io/jtprogru/py-tg-moder:main
    env_file:
      - ./src/.env
```

