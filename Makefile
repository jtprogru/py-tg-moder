# Makefile

SHELL := /bin/bash

-include src/.env

V=${VERSION}

.PHONY: default help test-full sync sync-dev run build-img pytest fmt lint clean


default: help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync: ## Install runtime dependencies
	uv sync --no-dev

sync-dev: ## Install dependencies including dev group
	uv sync --dev

run: ## Run the bot locally
	cd src && source ./.env && uv run python bot.py

build-img: src/.env ## Build and tag the Docker image
	docker build . --tag ghcr.io/jtprogru/py-tg-moder:$V
	docker tag ghcr.io/jtprogru/py-tg-moder:$V ghcr.io/jtprogru/py-tg-moder:latest

pytest: clean ## Run the test suite with coverage gate
	uv run pytest --cov=src --cov-report=term --cov-fail-under=85

fmt: ## Format and auto-fix code with ruff
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

lint: ## Check formatting and lint with ruff
	uv run ruff format --check src/ tests/
	uv run ruff check src/ tests/

test-full: lint pytest ## Run lint and tests

clean: ## Remove compiled Python files and other artifacts
	find ./src -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -exec rm -rf {} +
	find ./src -name '*.pyc' -exec rm -f {} +
	find ./src -name '*.pyo' -exec rm -f {} +
