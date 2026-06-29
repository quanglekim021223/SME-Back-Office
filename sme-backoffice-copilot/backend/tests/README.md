# Backend tests

This directory contains unit, integration, contract, workflow, and API tests.
Tests may use synthetic or explicitly approved labelled fixtures only. Raw
customer documents must not be committed.

## Structure

- `unit/`: fast tests for pure functions, configuration, models, repositories,
  and other isolated components.
- `integration/`: tests that cross API/application boundaries using FastAPI's
  test client or future local infrastructure.
- `conftest.py`: shared fixtures such as `app` and `client`.

## Commands

From `backend/`:

```bash
make test
make test-unit
make test-integration
```
