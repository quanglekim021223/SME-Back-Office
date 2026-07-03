# SME Back-Office Copilot

Foundation for a controlled multi-agent platform that processes SME financial
documents, reconciles payments, and turns verified financial data into
operational insights.

This repository intentionally contains no accounting or AI business logic. It
defines service boundaries, deployment shells, ownership expectations, and the
technical documents that future implementation should follow.

## Start locally

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

- Frontend: `http://localhost:3000`
- API health check: `http://localhost:8000/health`
- API documentation: `http://localhost:8000/docs`

## Development commands

Install local development dependencies:

```bash
make install
```

Run formatting, linting, and tests:

```bash
make format
make lint
make test
```

Run the local deterministic evaluation suite:

```bash
cd backend
python -m app.evaluations.runner --format markdown
python -m app.evaluations.runner --format json --output ../data/evaluation-report.json
```

The evaluation command currently checks the controlled workflow replay scenarios
and applies the initial local release gate before real AI providers are enabled.

## Documentation

- [Repository structure](docs/repository_structure.md)
- [Product brief](docs/product_brief.md)
- [Architecture](docs/architecture.md)
- [Agent architecture](docs/agent_architecture.md)
- [Implementation plan](docs/implementation_plan.md)
- [Data model](docs/data_model.md)
- [Evaluation strategy](docs/evaluation.md)
