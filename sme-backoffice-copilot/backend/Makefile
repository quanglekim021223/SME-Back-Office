VENV_PYTHON := $(shell if [ -f ../.venv/bin/python ]; then echo "../.venv/bin/python"; elif [ -n "$$VIRTUAL_ENV" ]; then echo "$$VIRTUAL_ENV/bin/python"; else echo "python3"; fi)
PYTHON ?= $(VENV_PYTHON)

.PHONY: install format lint test test-unit test-integration db-upgrade db-downgrade seed-dev dev-reset

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

seed-dev:
	$(PYTHON) -m app.dev_seed

dev-reset:
	$(PYTHON) -m app.dev_reset --yes
