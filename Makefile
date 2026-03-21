PYTHON ?= python3
PORT ?= 5000

.PHONY: init install dev run test lint fmt check clean assets

init:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip
	. .venv/bin/activate && pip install -e ".[dev]"

install: init

run:
	. .venv/bin/activate && flask --app wsgi run --debug --host 127.0.0.1 --port $(PORT)

dev: run

test:
	. .venv/bin/activate && pytest

lint:
	. .venv/bin/activate && ruff check .

fmt:
	. .venv/bin/activate && ruff check . --fix

check: lint test

assets:
	npm install
	npm run build

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

assets-dev:
	npm install && npm run dev

assets-build:
	npm install && npm run build
