# Alembic migrations

Versioned relational schema migrations live here. Migration generation and
review are owned by backend engineers; production execution is owned by the
deployment operator. Generated migrations must never contain document or model
inference logic.

Common local commands from `backend/`:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```
