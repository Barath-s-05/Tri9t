"""Health endpoint tests."""

from fastapi.testclient import TestClient

from tri9t.app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """GET /health should return HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_healthy_status() -> None:
    """GET /health should return {'status': 'healthy'}."""
    response = client.get("/health")
    data = response.json()
    assert data == {"status": "healthy"}
