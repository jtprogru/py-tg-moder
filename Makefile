# Makefile

SHELL := /bin/bash

-include src/.env

V=${VERSION}
T=${TELEGRAM_BOT_TOKEN}

.PHONY: default test-full sync sync-dev run build-img pytest isort black flake8 lint clean-pyc clean-full


default: test-full

sync:
	uv sync --no-dev

sync-dev:
	uv sync --dev

run:
	cd src && source ./.env && uv run python bot.py

build-img: src/.env
	docker build . --tag ghcr.io/jtprogru/py-tg-moder:$V --build-arg TOKEN=$T
	docker tag ghcr.io/jtprogru/py-tg-moder:$V ghcr.io/jtprogru/py-tg-moder:latest

pytest: clean-pyc
	uv run pytest

isort:
	uv run isort src/

black:
	uv run black src/

flake8:
	uv run flake8 src/

lint:
	uv run black --check src/
	uv run isort --check-only src/
	uv run flake8 src/

test-full: isort black flake8 pytest

clean-full:
	find ./src -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -exec rm -rf {} +

clean-pyc:
	find ./src -name '*.pyc' -exec rm -f {} +
	find ./src -name '*.pyo' -exec rm -f {} +
