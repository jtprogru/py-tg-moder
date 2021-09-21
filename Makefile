# Makefile

SHELL := /bin/zsh

include src/.env

V=${VERSION}
T=${TELEGRAM_BOT_TOKEN}

&venv-activate:
	source venv/bin/activate &&

run:
	source venv/bin/activate && cd src && source ./.env && python3 bot.py

build-img:
	source ./src/.env && docker build . --tag ghcr.io/jtprogru/py-tg-moder:$V --build-arg TOKEN=$T
	source ./src/.env && docker tag ghcr.io/jtprogru/py-tg-moder:$V ghcr.io/jtprogru/py-tg-moder:main

venv:
	$(which python3) -m venv venv

install-deps-prod:
	source venv/bin/activate && pip install -r requirements.txt

install-deps-dev:
	source venv/bin/activate && pip install -r requirements.txt && pip install -r dev-requirements.txt

pytest:
	source venv/bin/activate && python -m pytest

isort:
	source venv/bin/activate && python -m isort src/

black:
	source venv/bin/activate && python -m black src/

flake8:
	source venv/bin/activate && python -m flake8 src/
