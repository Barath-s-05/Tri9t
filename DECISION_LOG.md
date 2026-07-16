# DECISION_LOG — Tri9T Document Intelligence API

## Q1: What's the one part most likely to silently give wrong results?

**Parser hierarchy reconstruction.**

If headings are incorrectly classified, the parser may produce a valid-looking tree that is structurally wrong. A missed heading level or misdetected section number silently nests content under the wrong parent, and downstream consumers (diff engine, staleness detection, generation) will operate on a flawed hierarchy without raising errors.

**Mitigation:**
- Parser warnings for duplicate headings, out-of-order numbering, skipped levels, and empty bodies (`parser_report.py`)
- Parser validation pass that checks structural invariants (`parser_validator.py`)
- Unit tests covering edge cases: deep nesting, virtual root injection, mixed numbering, skipped levels (`test_parser.py`)
- Manual inspection encouraged — warnings are logged, not swallowed

**Why this is dangerous:** The tree "works" — it stores, queries, and returns results. But if Section 3.2 is silently nested under Section 2.1, the diff engine will compare wrong nodes, the selection will pin wrong content, and the generated test cases will be traceable to the wrong section.

---

## Q2: Where did you choose simplicity over correctness?

**Node matching across document versions.**

I used heuristic matching based on heading text similarity, section numbers, and tree position instead of semantic embeddings. This approach may fail if a heading changes completely while the meaning stays the same (e.g., "Battery Runtime" → "Operating Duration").

**Why I chose heuristics:**
- **Deterministic** — same input always produces the same match, no embedding model version drift
- **Fast** — O(n²) string comparison vs. vector similarity search
- **Explainable** — the match score is composed of heading similarity, section number match, and position proximity; each factor is inspectable
- **No external dependency** — no embedding model, no vector database, no GPU

**What I sacrificed:** Semantic understanding. A heading renamed from "Emergency Shutdown Procedure" to "Critical Power-Off Protocol" would not match, even though they describe the same section. This is an acceptable tradeoff for a prototype where documents evolve incrementally (typo fixes, value changes) rather than wholesale rewrites.

---

## Q3: One unsupported input the system cannot handle?

**Scanned PDFs with no extractable text.**

The current implementation assumes PyMuPDF can extract text from the PDF. Scanned documents (image-only PDFs) contain no extractable text layer, and OCR is intentionally omitted.

**How the system handles it:** The parser raises an error instead of silently generating a broken tree. The ingest endpoint returns a clear 500 response with parse error details. This is a deliberate design choice — failing loudly is better than producing a valid-looking hierarchy from empty or garbage content.

**Future mitigation:** Adding an OCR pre-processing step (e.g., Tesseract or a cloud vision API) would handle scanned PDFs. The architecture supports this — `pdf_parser.py` is a single service that could be extended with an OCR fallback without changing any downstream code.

---

## Implementation Notes

### Version-pinned selections

A selection captures a fixed set of nodes from a specific `document_version_id`. The selection stores a `snapshot_hash` computed from the node content at creation time. When generating test cases, the selection is frozen — it never auto-updates. If the document is re-uploaded (new version), old selections remain valid for historical reference. Staleness detection (Stage 6) checks whether the underlying nodes have changed since generation.

### MongoDB for generations

Generations are semi-structured LLM outputs — schema may evolve (different fields, nested structures). SQLite requires fixed schema + migrations for every change. MongoDB's document model handles variable JSON structures natively. Audit logs are append-only event streams — natural fit for a document store. MongoDB is optional — all endpoints degrade gracefully if unreachable.

### Retry strategy for LLM failures

LLMs are non-deterministic — same input can produce different output formats. Groq API can return rate limits (429), timeouts, or server errors (5xx). Invalid JSON, missing fields, or wrong priority values must be caught before storage. The retry engine attempts up to 3 generations with validation gate, and every attempt (success or failure) is logged to MongoDB audit collection for debugging.
