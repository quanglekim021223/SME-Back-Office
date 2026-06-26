PYTHON ?= python3

.PHONY: install format lint test

install:
	$(PYTHON) -m pip install -e ".[dev]"

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check . --fix

lint:
	$(PYTHON) -m ruff format . --check
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy app

test:
	$(PYTHON) -m pytest
