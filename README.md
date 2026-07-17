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

> **Stage 7** — Production-ready. All core features + production quality complete.

## Architecture

```
PDF
 │
 ▼
PyMuPDF Parser
 │
 ▼
Hierarchy Builder
 │
 ▼
SQLite
 │
 ▼
Versioning
 │
 ▼
Selections
 │
 ▼
Prompt Builder
 │
 ▼
Groq
 │
 ▼
MongoDB
 │
 ▼
Generation Retrieval
 │
 ▼
Staleness Detection
```

**Error handling:** The global exception handler logs unexpected exceptions server-side with full stack traces while returning sanitized structured errors (`{error, message, hint}`) to clients. No internal details leak to the caller.

## Parser Reporting

Every ingestion returns a structured parser report with:

- Pages processed, nodes created, headings/tables/lists detected
- Processing time in milliseconds
- Parser warnings for structural irregularities: duplicate headings, out-of-order numbering, skipped heading levels, empty body text
- Table detection via block position analysis

The parser handles edge cases robustly: duplicate headings get UUID suffixes with warnings, skipped levels (e.g., H1 → H3) trigger virtual root injection, and out-of-order section numbers are flagged while the hierarchy is still built correctly.

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
      ingest.py                  # POST /ingest/document
      browse.py                  # GET /documents, /documents/{id}/tree, /nodes/{id}
      selection.py               # POST/GET/DELETE /selections/
      generation.py              # POST /generate, GET /generation/{id}, etc.
      retrieval.py               # GET /search
      versions.py                # POST /versions/ingest, GET /versions/document/{id}/versions
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

All paginated list endpoints return `{items, page, limit, total, pages}`.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check (SQLite + MongoDB + Groq status, uptime) |
| `/metrics` | GET | System resource counts (SQLite + MongoDB generation count) |
| `/ingest/document` | POST | Upload and parse a PDF document |
| `/documents` | GET | List all documents (paginated, sortable, filterable) |
| `/documents/{id}` | GET | Get document with versions |
| `/documents/{doc_id}/tree` | GET | Get hierarchical node tree |
| `/nodes/{node_id}` | GET | Get single node with children |
| `/versions/{version_id}/tree` | GET | Get tree for a specific version |
| `/search` | GET | Full-text search across nodes (paginated, filterable by impact) |
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

## Pagination

All list endpoints support pagination via `page` and `limit` query parameters:

```
GET /documents?page=1&limit=10
GET /search?query=safety&page=2&limit=5
GET /selections/?page=1&limit=20
GET /generation/history?page=1&limit=10
```

All paginated responses share a consistent format:

```json
{
  "items": [...],
  "page": 1,
  "limit": 10,
  "total": 42,
  "pages": 5
}
```

## Sorting

List endpoints support `sort` and `order` query parameters:

```
GET /documents?sort=title&order=asc
GET /documents?sort=created_at&order=desc
GET /selections/?sort=selection_name&order=asc
GET /search?query=safety&sort=score&order=desc
```

## Filtering

List endpoints support optional filter parameters:

```
GET /documents?title=CT200              # Filter by title substring
GET /search?impact_level=HIGH           # Filter by impact level
GET /generation/history?stale=true      # Filter by staleness status
```

Filtering never breaks existing APIs — unsupported filters are silently ignored.

## Request IDs

Every request includes an `X-Request-ID` header:

- If the client sends one, it is echoed back
- Otherwise, a UUID v4 is generated automatically
- Request IDs appear in all structured logs for correlation

## Metrics

```
GET /metrics
```

Returns aggregate counts of all major resource types. Document, version, node, and selection counts come from SQLite. Generation count comes from MongoDB (returns 0 if MongoDB is unavailable).

```json
{
  "documents": 42,
  "versions": 87,
  "nodes": 1523,
  "selections": 12,
  "generations": 36
}
```

## Health

```
GET /health
```

Returns detailed system status including uptime, service connectivity, and version:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "services": {
    "sqlite": "connected",
    "mongodb": "connected",
    "groq": "configured"
  },
  "timestamp": "2025-01-15T10:30:00Z"
}
```

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
