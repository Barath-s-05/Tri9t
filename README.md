# Tri9T Document Intelligence API

Production-quality FastAPI backend for parsing, browsing, and generating QA test cases from technical PDF documents.

## Project Overview

This API is designed to:

- Parse technical PDF documents into a hierarchical tree structure
- Store and manage document versions
- Detect changes across document versions
- Support browsing and searching within documents
- Allow version-pinned node selections
- Generate QA test cases using an LLM
- Detect stale generated outputs

> **Stage 1** — Foundation and project scaffolding only.

## Folder Structure

```
tri9t/
  app/
    main.py                  # FastAPI application entry point
    core/
      config.py              # Settings class (pydantic-settings)
      logging.py             # Structured logging configuration
    db/
      database.py            # Engine, session, and get_db dependency
      base.py                # Declarative base and TimestampMixin
    models/
      document.py            # Document, DocumentVersion
      node.py                # Node
      selection.py           # Selection
      generation.py          # GenerationRecord
    schemas/                 # Pydantic request/response schemas
    api/                     # API-specific utilities
    routers/
      health.py              # GET /health
      ingest.py              # Placeholder — document ingestion
      browse.py              # Placeholder — document browsing
      selection.py           # Placeholder — node selection
      generation.py          # Placeholder — QA generation
      retrieval.py           # Placeholder — search and retrieval
    services/                # Business logic layer
    utils/                   # Shared utilities
    tests/
      test_health.py         # Health endpoint tests
  docs/                      # Documentation
  data/                      # Runtime data directory
  requirements.txt
  .env.example
  .gitignore
  README.md
```

## Setup Instructions

### 1. Clone and install

```bash
git clone <repo-url>
cd tri9t
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env as needed
```

### 3. Run the application

```bash
uvicorn tri9t.app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

Interactive docs at `http://127.0.0.1:8000/docs`.

## Running Tests

```bash
pytest tri9t/app/tests/ -v
```

## Current Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/ingest/documents` | Upload document (placeholder) |
| GET | `/browse/documents` | List documents (placeholder) |
| GET | `/browse/tree/{id}` | Get document tree (placeholder) |
| POST | `/selections/` | Pin a node (placeholder) |
| POST | `/generate/test-cases` | Generate QA cases (placeholder) |
| GET | `/retrieval/search` | Search nodes (placeholder) |

## Future Features

- **Stage 2** — PDF parsing, document versioning, hierarchical tree storage
- **Stage 3** — Browsing, search, version-pinned selections
- **Stage 4** — LLM-powered QA test case generation, staleness detection
- **Stage 5** — MongoDB integration for document storage, full change detection

## Tech Stack

- **Python 3.12**
- **FastAPI** — async web framework
- **Pydantic v2** — data validation
- **SQLAlchemy 2** — ORM
- **Alembic** — database migrations
- **SQLite** — development database
- **MongoDB** — future document store
- **Pytest** — testing
