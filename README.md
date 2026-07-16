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

> **Stage 6** — All core features complete.

## Architecture

```
PDF Upload
    │
    ▼
┌──────────┐
│  Parser   │  PyMuPDF extracts text, headings, sections
└────┬─────┘
     │
     ▼
┌──────────┐
│ Hierarchy │  Tree builder constructs parent-child nodes
└────┬─────┘
     │
     ▼
┌──────────┐
│  SQLite   │  Documents, versions, nodes, selections
└────┬─────┘
     │
     ▼
┌──────────┐
│Versioning │  Node matching across document versions
└────┬─────┘
     │
     ▼
┌──────────┐
│ Selection │  User pins version-specific nodes
└────┬─────┘
     │
     ▼
┌──────────┐
│   Groq   │  LLM generates QA test cases (3–5)
└────┬─────┘
     │
     ▼
┌──────────┐
│  MongoDB  │  Generations, audit logs stored here
└────┬─────┘
     │
     ▼
┌──────────┐
│ Retrieval │  Staleness detection on every fetch
└──────────┘
```

## Folder Structure

```
tri9t/
  app/
    main.py                      # FastAPI application entry point with lifespan
    core/
      config.py                  # Settings class (pydantic-settings, Groq config)
      logging.py                 # Structured logging configuration
    db/
      database.py                # SQLite engine, session, get_db dependency
      base.py                    # Declarative base and TimestampMixin
      mongo.py                   # MongoDB client singleton (generations, audit)
    models/
      document.py                # Document, DocumentVersion
      node.py                    # Node (with content_hash, logical_node_id)
      selection.py               # Selection (version-pinned node snapshot)
      generation.py              # GenerationRecord
    schemas/
      parser.py                  # Pydantic schemas for parsed content
    middleware/
      timing.py                    # Request timing (X-Process-Time header, structured logs)
      request_id.py                # X-Request-ID propagation/generation
    routers/
      health.py                    # GET /health
      metrics.py                   # GET /metrics
      ingest.py                  # POST /ingest/documents
      browse.py                  # GET /browse/documents, /browse/tree/{id}, /browse/node/{id}
      selection.py               # POST/GET/DELETE /selections/
      generation.py              # POST /generate, GET /generation/{id}, etc.
      retrieval.py               # GET /retrieval/search
      versions.py                # GET /versions/{doc_id}
    services/
      pdf_parser.py              # PDF text extraction and heading detection
      tree_builder.py            # Hierarchical node tree construction
      node_hasher.py             # SHA-256 content hashing per node
      node_matcher.py            # Cross-version node similarity matching
      versioning_service.py      # Version upload, node matching, diff
      diff_engine.py             # Semantic document comparison
      impact_analyzer.py         # Change severity classification
      selection_service.py       # Version-pinned selection management
      prompt_builder.py          # LLM prompt construction and versioning
      llm_service.py             # Groq API provider
      output_validator.py        # JSON output validation (3–5 test cases)
      retry_engine.py            # Async retry with audit callback
      generation_service.py      # Full generation workflow orchestration
      audit_service.py           # Audit event persistence to MongoDB
      staleness_service.py       # Hash-based staleness detection
      retrieval_service.py       # Enhanced retrieval with staleness info
      browse_service.py          # Document browsing and tree queries
      search_service.py          # Full-text search across nodes
      document_loader.py         # PDF file loading
      parser_report.py           # Parser warning aggregation
      parser_validator.py        # Parser output validation
    tests/
      test_health.py               # Health endpoint tests
      test_api.py                  # Browse, search, selection API tests
      test_parser.py               # PDF parser tests
      test_browse_search_selection.py  # Browse, search, selection service tests
      test_versioning.py           # Versioning, diff, impact analysis tests
      test_generation.py           # Generation pipeline tests
      test_staleness.py            # Staleness detection tests
      test_middleware.py           # Timing middleware tests
      test_production_readiness.py # Pagination, metrics, request ID tests
  data/                          # Runtime data directory
  requirements.txt
  .env.example
  .gitignore
  README.md
  APPROACH.md
  DECISION_LOG.md
  postman_collection.json
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
# Edit .env — add your GROQ_API_KEY
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

**248 tests** across 9 test files, all passing.

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check (SQLite + MongoDB + Groq status, uptime) |
| `/metrics` | GET | System resource counts (documents, versions, nodes, selections, generations) |
| `/ingest/documents` | POST | Upload and parse a PDF document |
| `/documents` | GET | List all documents (paginated, sortable, filterable) |
| `/documents/{id}` | GET | Get document with versions |
| `/documents/{doc_id}/tree` | GET | Get hierarchical node tree |
| `/nodes/{node_id}` | GET | Get single node with children |
| `/versions/{version_id}/tree` | GET | Get tree for a specific version |
| `/search` | GET | Full-text search across nodes (paginated) |
| `/selections/` | POST | Create a version-pinned selection |
| `/selections/` | GET | List all selections (paginated, sortable) |
| `/selections/{id}` | GET | Get selection by ID |
| `/selections/{id}` | DELETE | Delete a selection |
| `/generate` | POST | Generate QA test cases from selection |
| `/generation/history` | GET | Paginated generation history (filterable by staleness) |
| `/generation/{id}` | GET | Retrieve generation with staleness info |
| `/node/{node_id}/generations` | GET | All generations that included a node |
| `/selection/{id}/generations` | GET | All generations for a selection |
| `/versions/document/{doc_id}/versions` | GET | List versions for a document |
| `/versions/node/{node_id}/changes` | GET | Field-level diff summary for a node |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Tri9T Document Intelligence API` | Application name |
| `APP_VERSION` | `0.1.0` | Semantic version |
| `DEBUG` | `false` | Enable debug mode |
| `DATABASE_URL` | `sqlite:///./tri9t.db` | SQLite connection string |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `tri9t` | MongoDB database name |
| `GROQ_API_KEY` | *(empty)* | **Required** — Groq API key for LLM generation |
| `MODEL_NAME` | `llama-3.3-70b-versatile` | Groq model identifier |
| `TEMPERATURE` | `0.7` | LLM temperature (0.0–2.0) |

## Versioning Workflow

1. Upload a PDF → creates Document + DocumentVersion (v1)
2. Upload updated PDF → creates DocumentVersion (v2)
3. Parser matches nodes across versions using heading similarity + section numbers
4. Each node stores `logical_node_id` (stable) and `content_hash` (detects changes)
5. Diff engine classifies changes as ADDED / REMOVED / MODIFIED / UNCHANGED
6. Impact analyzer classifies severity: LOW → CRITICAL

## Staleness Detection

When a generation is retrieved, the system:

1. Loads the stored `node_hashes` from the MongoDB generation document
2. Compares against current `content_hash` values in SQLite
3. Classifies status:
   - **CURRENT** — all hashes match, generation is valid
   - **STALE** — all/most nodes changed, regeneration recommended
   - **PARTIALLY_STALE** — some nodes changed
   - **UNKNOWN** — generation or selection not found
4. Returns impact level and human-readable recommendation

## Duplicate Selection Policy

If the same selection is submitted for generation twice, a new generation is always created. LLMs are probabilistic — a second generation may produce different test cases. Each generation gets a unique ID, timestamp, prompt hash, response hash, and audit log. Historical generations remain reproducible.

## Sample Request/Response Payloads

### POST /generate

**Request:**
```json
{
  "selection_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**
```json
{
  "generation_id": "gen-abc-123",
  "test_cases": [
    {
      "title": "Verify battery threshold alarm triggers at 15%",
      "preconditions": "Battery is charged above 15%",
      "steps": ["Start monitoring battery level", "Discharge to 15%"],
      "expected_result": "Alarm triggers when battery reaches 15%",
      "priority": "HIGH",
      "traceability": ["1.2 Battery Threshold"]
    }
  ],
  "metadata": {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile",
    "prompt_version": "1.0",
    "processing_time_ms": 2340,
    "response_hash": "a1b2c3..."
  }
}
```

### GET /generation/{id}

**Response:**
```json
{
  "selection_id": "550e8400-e29b-41d4-a716-446655440000",
  "test_cases": [...],
  "staleness": {
    "status": "CURRENT",
    "reason": "All nodes match stored hashes",
    "changed_nodes": [],
    "impact_level": null,
    "recommendation": "No action needed - generation is current",
    "stored_version_id": "v1-abc",
    "latest_version_id": "v1-abc",
    "total_nodes": 3,
    "changed_count": 0
  }
}
```

### GET /versions/node/{node_id}/changes

**Response:**
```json
{
  "node_id": "node-abc-123",
  "logical_node_id": "lnode-456",
  "heading": "Battery Threshold",
  "old_hash": "a1b2c3...",
  "new_hash": "d4e5f6...",
  "change_type": "modified",
  "changed_fields": [
    {"field_name": "body_text", "old_value": "Threshold: 15%", "new_value": "Threshold: 10%"}
  ],
  "summaries": ["Body Text: Threshold: 15% → Threshold: 10%"],
  "impact_level": "HIGH"
}
```

## Groq Configuration

The generation pipeline uses **Groq** exclusively (via their REST API):

```bash
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
MODEL_NAME=llama-3.3-70b-versatile
TEMPERATURE=0.7
```

Get an API key at https://console.groq.com

## Known Limitations

- **SQLite** — no concurrent write access; single-process only
- **MongoDB optional** — generation features fail gracefully if unavailable
- **PDF parsing** relies on PyMuPDF heading detection; complex layouts may produce warnings
- **LLM generation** requires network access to Groq API
- **No authentication** or rate limiting on API endpoints
- **Semantic node matching** relies on heuristic heading similarity, not semantic embeddings — may fail if a heading changes completely while meaning stays the same
- **OCR for scanned PDFs** is not implemented — the parser assumes extractable text; scanned documents raise an error instead of silently generating a broken tree
- **Large PDFs** (>500 pages) are not optimized for memory or processing time
- **Staleness detection** is hash-based, not semantic — cannot detect meaning-preserving rewording

## Tech Stack

- **Python 3.10+**
- **FastAPI** — async web framework
- **Pydantic v2** — data validation
- **SQLAlchemy 2** — ORM (SQLite)
- **MongoDB** (pymongo) — generation artifacts and audit logs
- **Groq API** — LLM inference (llama-3.3-70b-versatile)
- **PyMuPDF** — PDF parsing
- **Pytest** — testing (248 tests)
