"""Tests for request timing middleware."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tri9t.app.db.base import Base
from tri9t.app.db.database import get_db
from tri9t.app.main import app


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    return client, session


class TestTimingHeader:
    def test_x_process_time_header_present(self):
        client, session = _make_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert "x-process-time" in resp.headers
        finally:
            app.dependency_overrides.clear()
            session.close()

    def test_x_process_time_is_numeric(self):
        client, session = _make_client()
        try:
            resp = client.get("/health")
            value = resp.headers["x-process-time"]
            float(value)
        finally:
            app.dependency_overrides.clear()
            session.close()

    def test_x_process_time_is_positive(self):
        client, session = _make_client()
        try:
            resp = client.get("/health")
            elapsed = float(resp.headers["x-process-time"])
            assert elapsed >= 0
        finally:
            app.dependency_overrides.clear()
            session.close()

    def test_x_process_time_on_404(self):
        client, session = _make_client()
        try:
            from tri9t.app.tests.test_api import _NONEXISTENT_UUID

            resp = client.get(f"/documents/{_NONEXISTENT_UUID}")
            assert resp.status_code == 404
            assert "x-process-time" in resp.headers
            elapsed = float(resp.headers["x-process-time"])
            assert elapsed >= 0
        finally:
            app.dependency_overrides.clear()
            session.close()

    def test_x_process_time_on_error(self):
        client, session = _make_client()
        try:
            resp = client.get("/documents/not-a-uuid")
            assert resp.status_code == 422
            assert "x-process-time" in resp.headers
        finally:
            app.dependency_overrides.clear()
            session.close()

    def test_x_process_time_format(self):
        client, session = _make_client()
        try:
            resp = client.get("/health")
            value = resp.headers["x-process-time"]
            assert re.match(r"^\d+\.\d{2}$", value)
        finally:
            app.dependency_overrides.clear()
            session.close()
