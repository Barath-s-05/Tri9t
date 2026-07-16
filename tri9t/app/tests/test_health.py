"""Health endpoint tests."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from tri9t.app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """GET /health should return HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_healthy_status() -> None:
    """GET /health should return status 'healthy'."""
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "healthy"


def test_health_has_required_fields() -> None:
    """Response must contain all required top-level fields."""
    data = client.get("/health").json()
    assert "status" in data
    assert "version" in data
    assert "uptime_seconds" in data
    assert "services" in data
    assert "timestamp" in data


def test_health_version_matches_config() -> None:
    """Version field should match APP_VERSION from settings."""
    from tri9t.app.core.config import settings

    data = client.get("/health").json()
    assert data["version"] == settings.APP_VERSION


def test_health_uptime_is_non_negative() -> None:
    """Uptime should be a non-negative float."""
    data = client.get("/health").json()
    assert isinstance(data["uptime_seconds"], float)
    assert data["uptime_seconds"] >= 0


def test_health_uptime_increases_between_requests() -> None:
    """Uptime should increase between two sequential requests."""
    import time

    from tri9t.app.state import record_startup

    record_startup()
    first = client.get("/health").json()["uptime_seconds"]
    time.sleep(0.05)
    second = client.get("/health").json()["uptime_seconds"]
    assert second > first


def test_health_services_has_all_keys() -> None:
    """Services object must contain sqlite, mongodb, and groq."""
    data = client.get("/health").json()
    assert "sqlite" in data["services"]
    assert "mongodb" in data["services"]
    assert "groq" in data["services"]


def test_health_sqlite_connected() -> None:
    """SQLite should report connected when the DB is reachable."""
    data = client.get("/health").json()
    assert data["services"]["sqlite"] == "connected"


def test_health_mongo_unavailable() -> None:
    """MongoDB should report unavailable when ping fails."""
    with patch("tri9t.app.routers.health._check_mongodb", return_value="unavailable"):
        data = client.get("/health").json()
        assert data["services"]["mongodb"] == "unavailable"


def test_health_mongo_connected() -> None:
    """MongoDB should report connected when ping succeeds."""
    with patch("tri9t.app.routers.health._check_mongodb", return_value="connected"):
        data = client.get("/health").json()
        assert data["services"]["mongodb"] == "connected"


def test_health_groq_configured() -> None:
    """Groq should report configured when API key is set."""
    with patch("tri9t.app.routers.health._check_groq", return_value="configured"):
        data = client.get("/health").json()
        assert data["services"]["groq"] == "configured"


def test_health_groq_not_configured() -> None:
    """Groq should report not_configured when API key is empty."""
    with patch("tri9t.app.routers.health._check_groq", return_value="not_configured"):
        data = client.get("/health").json()
        assert data["services"]["groq"] == "not_configured"


def test_health_timestamp_format() -> None:
    """Timestamp should be a valid ISO-8601 UTC string."""
    from datetime import datetime

    data = client.get("/health").json()
    ts = data["timestamp"]
    assert ts.endswith("Z")
    # Parse back to verify it's valid ISO format
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert dt.tzinfo is not None


def test_health_status_200_even_when_mongo_down() -> None:
    """HTTP 200 should be returned even when MongoDB is unavailable."""
    with patch("tri9t.app.routers.health._check_mongodb", return_value="unavailable"):
        response = client.get("/health")
        assert response.status_code == 200
