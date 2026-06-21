# SME Back-Office Copilot

Foundation for an agentic platform that processes SME financial documents,
reconciles payments, and turns verified financial data into operational
insights.

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

## Documentation

- [Repository structure](docs/repository_structure.md)
- [Product brief](docs/product_brief.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data_model.md)
- [Evaluation strategy](docs/evaluation.md)

