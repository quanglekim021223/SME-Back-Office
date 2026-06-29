from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    """Create a fresh FastAPI app for each test."""

    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient]:
    """Create a TestClient around the test app."""

    with TestClient(app) as test_client:
        yield test_client
