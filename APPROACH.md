# APPROACH — Tri9T Document Intelligence API

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       FastAPI Router Layer                   │
│  health │ ingest │ browse │ selection │ generation │ search  │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                       Service Layer                         │
│  parser │ tree_builder │ versioning │ diff_engine │         │
│  impact_analyzer │ selection │ generation │ retrieval │     │
│  staleness │ search │ audit_service │ retry_engine          │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Storage Layer                             │
│  SQLite (SQLAlchemy)        │  MongoDB (pymongo)            │
│  documents, versions,       │  generations,                 │
│  nodes, selections          │  audit_logs                   │
└─────────────────────────────────────────────────────────────┘
```

## Parser Evolution

The initial parser had several issues that were discovered during testing with real-world technical PDFs:

**Issue 1: Table rows merged into body text.**
PyMuPDF extracts table cells as individual text blocks. The first parser concatenated adjacent blocks naively, causing table rows to merge into a single unreadable body field.
**Fix:** Table detection logic was added using block position analysis — blocks within a tight grid pattern are flagged as `table` type nodes rather than merged into section bodies.

**Issue 2: Out-of-order section numbering.**
Sections like 3.4 appearing before 3.3 in the PDF (common in draft documents) caused the hierarchy builder to attach 3.4 under 3.2.
**Fix:** The tree builder now uses page-order as the primary ordering signal, with section numbers as a secondary hint. A parser warning is emitted when numbering is detected out of sequence.

**Issue 3: Deep headings attached to wrong parent.**
A heading like 2.1.1.1 appearing after 2.1.2 was incorrectly nested under 2.1.2 instead of 2.1.1.
**Fix:** The stack-based hierarchy algorithm was reworked to pop levels correctly — it tracks the current depth and only pops when a same-or-higher-level heading is encountered, ensuring correct parent assignment.

**Issue 4: Skipped heading levels.**
Documents jumping from H1 to H3 (missing H2) produced a flat, broken tree.
**Fix:** A virtual root node is injected when the first heading level is > 1, and skipped levels generate a parser warning.

## Parser Design

**Input:** PDF file uploaded via `POST /ingest/documents`

**Process:**
1. PyMuPDF extracts text blocks with page numbers and position data
2. Heading detection uses font size, bold weight, and indentation heuristics
3. Section numbers extracted via regex (`1.`, `1.1`, `1.1.1`, etc.)
4. Each block becomes a candidate node with heading, body, level, page

**Output:** Flat list of parsed sections with metadata

**Edge cases handled:**
- Duplicate headings → warning logged, UUID suffix added
- Empty headings → warning, heading set to placeholder
- Missing body text → warning, body set to empty
- Out-of-order numbering → warning, hierarchy still built
- Skipped levels (H1 → H3) → warning, virtual root injected

## Hierarchy Construction

**Service:** `tree_builder.py`

1. Build virtual root node if document starts at level > 1
2. Use a stack-based algorithm to track parent relationships
3. Each node gets a UUID `id`, links to `parent_id`, stores `level`
4. Nodes ordered by `page_number` then position within page

**Result:** Parent-child tree stored in SQLite `nodes` table

## Hashing Strategy

**Service:** `node_hasher.py`

Each node's `content_hash` is a SHA-256 of:
- Normalised heading (lowercased, stripped)
- Normalised body text (lowercased, stripped)
- Section number
- Node type
- Parent ID (heading path)

Including the parent ID ensures that moving a requirement under a different section — even if the heading and body text are identical — produces a different hash. This catches structural changes where content is relocated rather than modified.

## Version Matching Strategy

**Service:** `versioning_service.py`

When a new document version is uploaded, nodes from the new version are matched against nodes from the previous version:

1. **Exact match** — identical heading → reuse `logical_node_id`
2. **Similar match** — heading similarity score > threshold (0.6) + section number match → reuse `logical_node_id`
3. **Position match** — same level, adjacent position → moderate confidence
4. **No match** — new node gets fresh `logical_node_id`

**Similarity metric:** Case-insensitive exact match, then substring containment, then Levenshtein-like comparison via `SequenceMatcher`.

**Result:** Each node in the new version either gets an existing `logical_node_id` (tracked across versions) or a new one (addition).

## Duplicate Selection Policy

The assignment requires a defined policy for what happens when the same selection is submitted for generation twice.

**Policy:** Always create a new generation, even if the same selection is submitted again.

**Rationale:**
- LLMs are probabilistic — a second generation from the same input may produce different test cases
- Each generation gets a unique ID, timestamp, prompt hash, response hash, and audit log
- Historical generations remain reproducible (stored with their exact prompt hash and LLM response)
- The staleness detection system already handles version drift — duplicate submissions are just another form of idempotent operation
- Forbidding duplicate submissions would force users to delete and recreate selections, which is worse UX

**Implementation:**
- `POST /generate` accepts any valid `selection_id` — no deduplication check
- Each call creates a new MongoDB document with a new `_id`
- The `generation_history` endpoint returns all generations, so users can compare outputs
- No rate limiting at this layer (can be added later)

## Why SQLite for Document Data

| Factor | SQLite | PostgreSQL |
|--------|--------|------------|
| Setup complexity | Zero config, file-based | Server process, auth, config |
| Deployment | Single binary, portable | Requires infrastructure |
| Concurrency | Single-writer sufficient for this use case | Overkill for demo/prototype |
| Performance | Fast for <10GB datasets | Marginal gain at this scale |
| Testing | In-memory mode, fast CI | Additional dependency |

**Decision:** SQLite is the right choice for a prototype/MVP. The service layer abstracts the DB, so migrating to PostgreSQL later requires only changing the connection string and fixing any raw SQL.

## Why MongoDB for Generations

| Factor | SQLite | MongoDB |
|--------|--------|---------|
| Schema flexibility | Fixed schema, migrations needed | Flexible, documents can vary |
| Write pattern | Generations are append-only, high-volume | Natural fit for document store |
| Query pattern | Retrieval by selection_id, version_id | Simple key queries, pagination |
| Audit logs | Relational overhead for event streams | Schema-less events, easy to append |
| Separation of concerns | Mixed with document data | Clean separation: structure vs. artifacts |

**Decision:** MongoDB stores AI outputs (generations, audit logs) while SQLite stores structured document data. This gives schema flexibility for LLM outputs (which may change format) without polluting the relational model.

## Prompt Design

**Service:** `prompt_builder.py`

The system prompt instructs the LLM to:
1. Act as a QA engineer for technical documents
2. Return exactly 3–5 test cases as JSON
3. Each test case has: `title`, `priority`, `preconditions`, `steps[]`, `expected_result`
4. Priority must be one of: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
5. Return raw JSON only — no markdown, no explanation

The user prompt includes:
- Full text reconstruction from all selected nodes (page-ordered)
- Section numbers and headings for context
- Instruction to generate technical QA test cases

**Prompt versioning:** Hash of the system prompt text enables detecting when the prompt template itself changes.

## JSON Validation

**Service:** `output_validator.py`

Post-generation validation checks:
1. Response is valid JSON (strips markdown fences if present)
2. `test_cases` key exists and is a list
3. Minimum 3 test cases, maximum 5
4. Each test case has all required fields (`title`, `priority`, `preconditions`, `steps`, `expected_result`)
5. `title` is non-empty string
6. `steps` is a list of strings
7. `priority` is one of `LOW|MEDIUM|HIGH|CRITICAL`

Invalid output triggers retry (not silent failure).

## Retry Strategy

**Service:** `retry_engine.py`

- Max 3 attempts per generation
- On validation failure: log event, increment attempt, retry with same input
- On LLM error (timeout, rate limit, 5xx): log event, retry with backoff
- On max retries exceeded: raise `GenerationError` with details
- Audit callback invoked on every attempt (success or failure)

**No exponential backoff** — Groq has fast retry windows and the model is fast enough that simple immediate retry works.

## Staleness Detection

**Service:** `staleness_service.py`

When retrieving a generation:

1. Load the stored generation document from MongoDB
2. Extract `node_hashes` (list of content hashes at generation time)
3. Resolve the `selection_id` to get current `node_ids`
4. Load current nodes from SQLite
5. Compare each stored hash against current `content_hash`
6. Count changed nodes

**Classification:**
- 0 changed → `CURRENT`
- All changed → `STALE`
- Some changed → `PARTIALLY_STALE`
- Generation/selection not found → `UNKNOWN`

**Edge case:** If stored version differs from latest version but all hashes match → `PARTIALLY_STALE` (newer version exists even if content is identical).

**Impact analysis** reuses `diff_engine.py` and `impact_analyzer.py` to determine severity of changes.

## Diff Summary API

The `GET /versions/node/{node_id}/changes` endpoint returns a structured diff for any node:

```json
{
  "node_id": "abc-123",
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

**What the response includes:**
- `change_type`: `added`, `removed`, `modified`, or `unchanged`
- `changed_fields`: field-level old/new values (heading, body_text, level, section_number)
- `summaries`: human-readable one-liners for each change
- `impact_level`: severity classification from `impact_analyzer.py` (LOW → CRITICAL)
- `old_hash` / `new_hash`: content hashes for programmatic comparison

This is not a boolean flag — it's a full semantic diff with field-level granularity and impact classification.

## Failure Modes

| Failure | Handling |
|---------|----------|
| MongoDB unreachable | Graceful degradation — generation endpoints return 503 |
| Groq API key missing | Endpoint returns 503 with clear message |
| Groq rate limit | Retry engine attempts up to 3 times |
| Invalid LLM output | Validation catches, retry triggers regeneration |
| PDF parse failure | Ingest endpoint returns 500 with parse error details |
| Missing selection | 404 with clear message |
| Empty node list | 422 with message explaining no valid nodes |
| Staleness check with missing generation | Returns `UNKNOWN` status, not error |

## Tradeoffs

| Decision | Tradeoff |
|----------|----------|
| SQLite over PostgreSQL | Simpler setup, but no concurrent writes |
| MongoDB for generations | Schema flexibility, but adds operational complexity |
| Hash-based staleness | Fast comparison, but can't detect semantic changes (e.g., meaning-preserving rewording) |
| Fixed retry count (3) | Simple, but may not suit all error types |
| Groq-only (no multi-provider) | Simpler code, but vendor lock-in |
| No markdown in LLM output | Cleaner JSON, but less expressive prompts |
| Synchronous staleness check on retrieval | Adds latency to every GET, but ensures freshness |
| Always create new generation on duplicate submission | More storage, but preserves probabilistic LLM nature and full audit trail |
