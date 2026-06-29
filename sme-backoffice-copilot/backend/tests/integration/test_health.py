import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "local"}
