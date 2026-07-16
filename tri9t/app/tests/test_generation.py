"""Tests for the AI generation engine.

All LLM calls are mocked – no real Groq API is ever contacted.
MongoDB interactions are patched at the collection level.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tri9t.app.db.base import Base
from tri9t.app.models.node import Node
from tri9t.app.services import (
    audit_service,
    generation_service,
    output_validator,
    prompt_builder,
    retry_engine,
)
from tri9t.app.services.llm_service import GroqProvider, get_provider
from tri9t.app.services.prompt_builder import PROMPT_TEMPLATE, PromptSet
from tri9t.app.services.output_validator import ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    id: str = "n1",
    heading: str = "Intro",
    level: int = 1,
    body_text: str = "Body text here.",
    section_number: str | None = "1",
    page_number: int = 1,
    content_hash: str = "abc123",
    version_id: str = "v1",
) -> Node:
    return Node(
        id=id,
        document_id="doc1",
        version_id=version_id,
        heading=heading,
        level=level,
        body_text=body_text,
        section_number=section_number,
        page_number=page_number,
        content_hash=content_hash,
    )


VALID_LLM_OUTPUT = json.dumps(
    {
        "test_cases": [
            {
                "title": "Login with valid credentials",
                "preconditions": "User account exists",
                "steps": ["Open login page", "Enter credentials", "Click login"],
                "expected_result": "User is logged in",
                "priority": "HIGH",
                "traceability": ["1.2 Authentication"],
            },
            {
                "title": "Login with invalid password",
                "preconditions": "User account exists",
                "steps": ["Open login page", "Enter wrong password", "Click login"],
                "expected_result": "Error message shown",
                "priority": "MEDIUM",
                "traceability": ["1.2 Authentication"],
            },
            {
                "title": "Login with empty fields",
                "preconditions": "Login page is displayed",
                "steps": ["Open login page", "Leave fields empty", "Click login"],
                "expected_result": "Validation error shown",
                "priority": "LOW",
                "traceability": ["1.2 Authentication"],
            },
        ]
    }
)


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def sample_nodes():
    return [
        _make_node("n1", "Introduction", 1, "Welcome text.", "1", 1, "hash_a"),
        _make_node("n2", "Requirements", 2, "System needs RAM.", "1.1", 2, "hash_b"),
        _make_node("n3", "Safety", 2, "Wear goggles.", "1.2", 3, "hash_c"),
    ]


@pytest.fixture()
def three_valid_cases():
    return json.loads(VALID_LLM_OUTPUT)["test_cases"]


# ===================================================================
# Prompt Builder
# ===================================================================


class TestPromptBuilder:
    def test_reconstruct_text_orders_by_page(self, sample_nodes):
        text = prompt_builder.reconstruct_text(sample_nodes)
        assert "Introduction" in text
        idx_intro = text.index("Introduction")
        idx_req = text.index("Requirements")
        assert idx_intro < idx_req

    def test_build_prompt_returns_all_fields(self, sample_nodes):
        ps = prompt_builder.build_prompt(sample_nodes)
        assert isinstance(ps, PromptSet)
        assert ps.system_prompt
        assert ps.developer_prompt
        assert ps.user_prompt
        assert ps.prompt_version == PROMPT_TEMPLATE["version"]
        assert len(ps.prompt_hash) == 64  # SHA-256 hex

    def test_prompt_version_is_string(self, sample_nodes):
        ps = prompt_builder.build_prompt(sample_nodes)
        assert isinstance(ps.prompt_version, str)

    def test_prompt_hash_deterministic(self, sample_nodes):
        a = prompt_builder.build_prompt(sample_nodes)
        b = prompt_builder.build_prompt(sample_nodes)
        assert a.prompt_hash == b.prompt_hash

    def test_prompt_hash_changes_with_input(self, sample_nodes):
        a = prompt_builder.build_prompt(sample_nodes)
        b = prompt_builder.build_prompt([sample_nodes[0]])
        assert a.prompt_hash != b.prompt_hash

    def test_user_prompt_contains_node_content(self, sample_nodes):
        ps = prompt_builder.build_prompt(sample_nodes)
        assert "Welcome text." in ps.user_prompt
        assert "System needs RAM." in ps.user_prompt


# ===================================================================
# Output Validator
# ===================================================================


class TestOutputValidator:
    def test_valid_output(self):
        r = output_validator.validate_output(VALID_LLM_OUTPUT)
        assert r.is_valid is True
        assert len(r.test_cases) == 3

    def test_invalid_json(self):
        r = output_validator.validate_output("not json at all {{{")
        assert r.is_valid is False
        assert any("Invalid JSON" in e for e in r.errors)

    def test_missing_test_cases_key(self):
        r = output_validator.validate_output(json.dumps({"data": []}))
        assert r.is_valid is False
        assert any("test_cases" in e for e in r.errors)

    def test_too_few_test_cases(self):
        payload = json.dumps(
            {"test_cases": [{"title": "A", "preconditions": "B", "steps": [], "expected_result": "C", "priority": "LOW", "traceability": []}]}
        )
        r = output_validator.validate_output(payload)
        assert r.is_valid is False
        assert any("Too few" in e for e in r.errors)

    def test_too_many_test_cases(self):
        cases = [
            {"title": f"T{i}", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW", "traceability": []}
            for i in range(6)
        ]
        r = output_validator.validate_output(json.dumps({"test_cases": cases}))
        assert r.is_valid is False
        assert any("Too many" in e for e in r.errors)

    def test_missing_required_field(self):
        cases = [
            {"title": f"T{i}", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW"}
            for i in range(3)
        ]
        r = output_validator.validate_output(json.dumps({"test_cases": cases}))
        assert r.is_valid is False
        assert any("traceability" in e for e in r.errors)

    def test_empty_title_rejected(self):
        cases = [
            {"title": "", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW", "traceability": []}
            for _ in range(3)
        ]
        r = output_validator.validate_output(json.dumps({"test_cases": cases}))
        assert r.is_valid is False
        assert any("empty" in e for e in r.errors)

    def test_steps_not_list_rejected(self):
        cases = [
            {"title": "T", "preconditions": "P", "steps": "bad", "expected_result": "E", "priority": "LOW", "traceability": []}
            for _ in range(3)
        ]
        r = output_validator.validate_output(json.dumps({"test_cases": cases}))
        assert r.is_valid is False
        assert any("steps" in e for e in r.errors)

    def test_strips_markdown_fences(self):
        fenced = "```json\n" + VALID_LLM_OUTPUT + "\n```"
        r = output_validator.validate_output(fenced)
        assert r.is_valid is True

    def test_invalid_priority_rejected(self):
        cases = [
            {"title": "T", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "P1", "traceability": []}
            for _ in range(3)
        ]
        r = output_validator.validate_output(json.dumps({"test_cases": cases}))
        assert r.is_valid is False
        assert any("priority" in e for e in r.errors)

    def test_valid_priorities_accepted(self):
        for prio in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            cases = [
                {"title": "T", "preconditions": "P", "steps": [], "expected_result": "E", "priority": prio, "traceability": []}
                for _ in range(3)
            ]
            r = output_validator.validate_output(json.dumps({"test_cases": cases}))
            assert r.is_valid is True, f"Priority {prio} should be valid"


# ===================================================================
# Retry Engine
# ===================================================================


class TestRetryEngine:
    def test_success_first_attempt(self):
        async def ok():
            return VALID_LLM_OUTPUT

        raw, cases, retries = _run(
            retry_engine.execute_with_retry(ok, output_validator.validate_output)
        )
        assert retries == 0
        assert len(cases) == 3

    def test_success_after_retries(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "bad"
            return VALID_LLM_OUTPUT

        raw, cases, retries = _run(
            retry_engine.execute_with_retry(flaky, output_validator.validate_output)
        )
        assert retries == 2
        assert len(cases) == 3

    def test_max_retries_exceeded(self):
        async def always_bad():
            return "not json"

        with pytest.raises(Exception, match="All .* attempts failed"):
            _run(
                retry_engine.execute_with_retry(
                    always_bad, output_validator.validate_output, max_retries=2
                )
            )

    def test_event_callback_called(self):
        events: list[tuple] = []

        async def bad():
            return "invalid"

        with pytest.raises(Exception):
            _run(
                retry_engine.execute_with_retry(
                    bad,
                    output_validator.validate_output,
                    max_retries=1,
                    on_event=lambda t, d: events.append((t, d)),
                )
            )
        event_types = [t for t, _ in events]
        assert "validation_failed" in event_types
        assert "retry_attempt" in event_types


# ===================================================================
# LLM Provider Factory
# ===================================================================


class TestLLMProviders:
    def test_groq_provider(self):
        p = get_provider("groq", "key")
        assert isinstance(p, GroqProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("bogus", "key")


# ===================================================================
# Generation Service (mocked MongoDB + LLM)
# ===================================================================


class TestGenerationService:
    def test_selection_not_found(self, db):
        with patch(
            "tri9t.app.services.generation_service.get_selection",
            return_value=None,
        ):
            with pytest.raises(generation_service.GenerationError, match="not found"):
                _run(
                    generation_service.generate_test_cases(db, "nonexistent")
                )

    def test_no_nodes(self, db):
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": []}
        with patch(
            "tri9t.app.services.generation_service.get_selection",
            return_value=sel,
        ):
            with pytest.raises(generation_service.GenerationError, match="no nodes"):
                _run(generation_service.generate_test_cases(db, "s1"))

    def test_no_api_key(self, db):
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1"]}
        node = _make_node("n1")
        db.add(node)
        db.commit()
        with (
            patch(
                "tri9t.app.services.generation_service.get_selection",
                return_value=sel,
            ),
            patch(
                "tri9t.app.services.generation_service.settings"
            ) as mock_settings,
        ):
            mock_settings.GROQ_API_KEY = ""
            mock_settings.MODEL_NAME = "llama-3.3-70b-versatile"
            mock_settings.TEMPERATURE = 0.7
            with pytest.raises(generation_service.GenerationError, match="Groq API key"):
                _run(generation_service.generate_test_cases(db, "s1"))

    def test_full_workflow(self, db):
        sel = {
            "id": "s1",
            "document_version_id": "v1",
            "node_ids": ["n1", "n2"],
        }
        nodes = [_make_node("n1"), _make_node("n2")]
        for n in nodes:
            db.add(n)
        db.commit()

        mock_col = MagicMock()
        mock_col.insert_one = MagicMock()

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = VALID_LLM_OUTPUT

        with (
            patch(
                "tri9t.app.services.generation_service.get_selection",
                return_value=sel,
            ),
            patch(
                "tri9t.app.services.generation_service.get_generations_collection",
                return_value=mock_col,
            ),
            patch(
                "tri9t.app.services.generation_service.settings"
            ) as mock_settings,
            patch(
                "tri9t.app.services.generation_service.llm_service"
            ) as mock_llm,
            patch(
                "tri9t.app.services.generation_service.audit_service"
            ),
        ):
            mock_settings.GROQ_API_KEY = "test-key"
            mock_settings.MODEL_NAME = "llama-3.3-70b-versatile"
            mock_settings.TEMPERATURE = 0.7
            mock_llm.get_provider.return_value = mock_provider

            result = _run(
                generation_service.generate_test_cases(db, "s1")
            )

        assert "generation_id" in result
        assert len(result["test_cases"]) == 3
        assert result["metadata"]["provider"] == "groq"
        mock_col.insert_one.assert_called_once()

    def test_stores_response_hash(self, db):
        sel = {
            "id": "s1",
            "document_version_id": "v1",
            "node_ids": ["n1"],
        }
        node = _make_node("n1")
        db.add(node)
        db.commit()
        mock_col = MagicMock()
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = VALID_LLM_OUTPUT

        with (
            patch(
                "tri9t.app.services.generation_service.get_selection",
                return_value=sel,
            ),
            patch(
                "tri9t.app.services.generation_service.get_generations_collection",
                return_value=mock_col,
            ),
            patch(
                "tri9t.app.services.generation_service.settings"
            ) as mock_settings,
            patch(
                "tri9t.app.services.generation_service.llm_service"
            ) as mock_llm,
            patch(
                "tri9t.app.services.generation_service.audit_service"
            ),
        ):
            mock_settings.GROQ_API_KEY = "k"
            mock_settings.MODEL_NAME = "m"
            mock_settings.TEMPERATURE = 0.7
            mock_llm.get_provider.return_value = mock_provider

            result = _run(
                generation_service.generate_test_cases(db, "s1")
            )

        assert len(result["metadata"]["response_hash"]) == 64

    def test_stores_processing_time(self, db):
        sel = {
            "id": "s1",
            "document_version_id": "v1",
            "node_ids": ["n1"],
        }
        node = _make_node("n1")
        db.add(node)
        db.commit()
        mock_col = MagicMock()
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = VALID_LLM_OUTPUT

        with (
            patch(
                "tri9t.app.services.generation_service.get_selection",
                return_value=sel,
            ),
            patch(
                "tri9t.app.services.generation_service.get_generations_collection",
                return_value=mock_col,
            ),
            patch(
                "tri9t.app.services.generation_service.settings"
            ) as mock_settings,
            patch(
                "tri9t.app.services.generation_service.llm_service"
            ) as mock_llm,
            patch(
                "tri9t.app.services.generation_service.audit_service"
            ),
        ):
            mock_settings.GROQ_API_KEY = "k"
            mock_settings.MODEL_NAME = "m"
            mock_settings.TEMPERATURE = 0.7
            mock_llm.get_provider.return_value = mock_provider

            result = _run(
                generation_service.generate_test_cases(db, "s1")
            )

        assert "processing_time_ms" in result["metadata"]
        assert isinstance(result["metadata"]["processing_time_ms"], int)
        assert result["metadata"]["processing_time_ms"] >= 0


# ===================================================================
# Audit Service (mocked MongoDB)
# ===================================================================


class TestAuditService:
    def test_log_event_inserts(self):
        mock_col = MagicMock()
        with patch(
            "tri9t.app.services.audit_service.get_audit_collection",
            return_value=mock_col,
        ):
            audit_service.log_event("generation_started", "g1", {"k": "v"})
            mock_col.insert_one.assert_called_once()
            doc = mock_col.insert_one.call_args[0][0]
            assert doc["event_type"] == "generation_started"
            assert doc["generation_id"] == "g1"
            assert "timestamp" in doc

    def test_get_events_returns_list(self):
        mock_col = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = [
            {"event_type": "started", "timestamp": "t1"},
            {"event_type": "completed", "timestamp": "t2"},
        ]
        mock_col.find.return_value = mock_cursor

        with patch(
            "tri9t.app.services.audit_service.get_audit_collection",
            return_value=mock_col,
        ):
            events = audit_service.get_events("g1")
            assert len(events) == 2

    def test_log_event_handles_mongo_error(self):
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = Exception("connection lost")
        with patch(
            "tri9t.app.services.audit_service.get_audit_collection",
            return_value=mock_col,
        ):
            # Should not raise
            audit_service.log_event("generation_failed", "g1")


# ===================================================================
# API Endpoints (mocked services)
# ===================================================================


class TestGenerationAPI:
    def test_post_generate_selection_not_found(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app
        from tri9t.app.db.database import get_db

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        test_db = TestSession()

        def override_db():
            yield test_db

        app.dependency_overrides[get_db] = override_db

        with patch(
            "tri9t.app.routers.generation.generate_test_cases",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = generation_service.GenerationError(
                "Selection not found"
            )
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/generate",
                json={"selection_id": "bad"},
            )
            assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_post_generate_success(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app
        from tri9t.app.db.database import get_db

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        test_db = TestSession()

        def override_db():
            yield test_db

        app.dependency_overrides[get_db] = override_db

        fake_result = {
            "generation_id": "gen-123",
            "test_cases": [
                {"title": "T1", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW", "traceability": []},
                {"title": "T2", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW", "traceability": []},
                {"title": "T3", "preconditions": "P", "steps": [], "expected_result": "E", "priority": "LOW", "traceability": []},
            ],
            "metadata": {"provider": "groq", "model": "m", "processing_time_ms": 100},
        }

        with patch(
            "tri9t.app.routers.generation.generate_test_cases",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = fake_result
            client = TestClient(app)
            resp = client.post("/generate", json={"selection_id": "s1"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["generation_id"] == "gen-123"
            assert len(body["test_cases"]) == 3

        app.dependency_overrides.clear()

    def test_get_generation_not_found(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app

        with patch(
            "tri9t.app.routers.generation.get_generation",
            return_value=None,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/generation/nonexistent")
            assert resp.status_code == 404

    def test_get_generation_found(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app

        fake_doc = {
            "selection_id": "s1",
            "test_cases": [],
            "provider": "groq",
        }
        with patch(
            "tri9t.app.routers.generation.get_generation",
            return_value=fake_doc,
        ):
            client = TestClient(app)
            resp = client.get("/generation/g1")
            assert resp.status_code == 200
            assert resp.json()["provider"] == "groq"

    def test_generation_history(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app

        fake_hist = {
            "generations": [{"_id": "g1"}, {"_id": "g2"}],
            "total": 2,
        }
        with patch(
            "tri9t.app.routers.generation.get_generation_history",
            return_value=fake_hist,
        ):
            client = TestClient(app)
            resp = client.get("/generation/history")
            assert resp.status_code == 200
            assert resp.json()["total"] == 2

    def test_post_generate_no_api_key(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app
        from tri9t.app.db.database import get_db

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        test_db = TestSession()

        def override_db():
            yield test_db

        app.dependency_overrides[get_db] = override_db

        with patch(
            "tri9t.app.routers.generation.generate_test_cases",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = generation_service.GenerationError(
                "No Groq API key configured"
            )
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/generate", json={"selection_id": "s1"})
            assert resp.status_code == 503

        app.dependency_overrides.clear()
