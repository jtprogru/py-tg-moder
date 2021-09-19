# Makefile

SHELL := /bin/zsh

include src/.env

V=${VERSION}
T=${TELEGRAM_BOT_TOKEN}

run:
	source venv/bin/activate && cd src && source ./.env && python3 bot.py

build-img:
	source ./src/.env && docker build . --tag ghcr.io/jtprogru/py-tg-moder:$V --build-arg TOKEN=$T
	source ./src/.env && docker tag ghcr.io/jtprogru/py-tg-moder:$V ghcr.io/jtprogru/py-tg-moder:latest

push-img:
	source ./src/.env && docker push ghcr.io/jtprogru/py-tg-moder:$V
	source ./src/.env && docker push ghcr.io/jtprogru/py-tg-moder:latest
