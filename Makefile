# Makefile

SHELL := /bin/bash

include src/.env

V=${VERSION}
T=${TELEGRAM_BOT_TOKEN}

.PHONY: default test-full isort clean-pyc clean-full


default: test-full

&venv-activate:
	source venv/bin/activate &&

run:
	source venv/bin/activate && cd src && source ./.env && python3 bot.py

build-img: src/.env
	docker build . --tag ghcr.io/jtprogru/py-tg-moder:$V --build-arg TOKEN=$T
	docker tag ghcr.io/jtprogru/py-tg-moder:$V ghcr.io/jtprogru/py-tg-moder:latest

venv:
	$(which python3) -m venv venv

install-deps-prod: requirements.txt
	./venv/bin/pip install -r requirements.txt

install-deps-dev: requirements-dev.txt
	./venv/bin/pip install -r requirements-dev.txt

pytest: clean-pyc
	./venv/bin/python -m py.test

isort:
	./venv/bin/python -m isort src/

black:
	./venv/bin/python -m black src/

flake8:
	./venv/bin/python -m flake8 src/

test-full: isort black flake8 pytest

clean-full:
	find ./src -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -exec rm -rf {} +

clean-pyc:
	find ./src -name '*.pyc' -exec rm --force {} +
	find ./src -name '*.pyo' -exec rm --force {} +
