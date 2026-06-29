PYTHON ?= python3

.PHONY: install format lint test test-unit test-integration db-upgrade db-downgrade

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

test-unit:
	$(PYTHON) -m pytest tests/unit -m "not integration"

test-integration:
	$(PYTHON) -m pytest tests/integration -m integration

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1
