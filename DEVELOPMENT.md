# Development and regression testing

Use the separate Python 3.12 environment; retain the original `venv/` until reviewed.

```sh
python3.12 -m venv .venv-rebuild
.venv-rebuild/bin/python -m pip install -r requirements-dev.txt
.venv-rebuild/bin/python -m pytest
```

The suite discovers `tests/`, not the historical `test_setup.py` import checklist.
Tests mock Ollama and vector-store boundaries. Database and Streamlit tests use
pytest temporary directories. Never point test fixtures at existing runtime data.
Offline environment variables prevent accidental model downloads in tests.

The four original analytics expected failures are resolved and run as normal tests.
Analytics accepts snapshot rows (student_name, attendance/attendance_percent,
one or more numeric marks columns) or trend rows (student_name,
assessment_number, marks, attendance_percent; optional student_id).
For trend histories, provide student_id whenever names may be shared: duplicate
assessment numbers under a name are rejected, and disjoint same-name histories
cannot be distinguished without IDs. Snapshot analysis keeps separate row IDs.
Missing data and academic concerns are independent; CSV export follows the view.

The current embedding and LLM remain all-MiniLM-L6-v2 and llama3.2:3b. A real
app run opens writable runtime storage; use isolated copies for startup checks.

Generative AI: feature agents → `ai_provider.generate_chat` → `config.py` →
Ollama. Baseline model remains `llama3.2:3b`. Start the installed service with
`ollama serve`; no model is downloaded by the provider.

Configuration is read per call. `EDUAGENT_LLM_PROVIDER` defaults to `ollama`;
`EDUAGENT_LLM_MODEL` defaults to the baseline; `EDUAGENT_LLM_TIMEOUT_SECONDS`
defaults to 120. URL precedence: `EDUAGENT_OLLAMA_BASE_URL` → `OLLAMA_HOST` →
`http://127.0.0.1:11434`. URLs must include http:// or https://. Explicit blank
or invalid settings fail clearly; no .env file or API key is needed.
For future testing, set `EDUAGENT_LLM_MODEL` to an already-installed model or
pass `model=` to `generate_chat`; per-call overrides do not alter the default.
Embeddings remain separate and unchanged.


## Build 5: professor overview and local image OCR

Professor Dashboard is the default page. Counts come from SQLite courses and
managed materials; legacy registered documents are shown separately and are not
claimed to be a verified count of indexed content. Recent activity shows known
action labels and parsed timestamps, never raw details or uploaded text.

Upload Content accepts PDF, PNG, JPG and JPEG (case-insensitive). PDFs retain
existing text/page extraction; scanned/image-only PDFs are not OCR'd in this build.
Images are decoded/validated with Pillow and OCR'd locally via pytesseract.
Tesseract must already be installed/configured on PATH; an absent engine produces
a controlled upload failure and does not prevent PDF use or startup.
Python dependencies are pinned in requirements.txt. No cloud OCR or LLM correction
is used. OCR has a 30-second timeout and preserves useful lines/Unicode while
collapsing excessive whitespace. Check the bounded 1,000-character preview for
recognition errors; no accuracy guarantee or mandatory approval is implied.

The default per-upload limit is 20 MiB. Set EDUAGENT_MAX_UPLOAD_MB to a finite,
positive value (MiB, at least one byte) to override it independently of AI settings.
UI checks uploaded size before copying bytes, and the service rechecks before
hashing, extraction or indexing. Streamlit's own incoming-upload/server limit
still applies; this application limit does not control HTTP upload buffering.
Pillow decompression-bomb warnings/errors are rejected rather than ignored.

All formats use the same UUID/hash/exact-chunk ownership service, hierarchy and
course_material collection. Managed filenames use the UUID plus validated lower-
case extension. Existing PDF/legacy records are unchanged; no schema migration
or vector rewrite is needed. Identical bytes are duplicates even with new names;
different bytes remain independent even when OCR text matches.

Normal OCR tests mock the engine and isolate SQLite/uploads/vector boundaries.
Dashboard/page tests use temporary storage and mock generation. Run:

```sh
.venv-rebuild/bin/python -m pytest -p no:cacheprovider
.venv-rebuild/bin/python -m pip check
```

Optional live OCR checks must use temporary synthetic images and temporary storage,
never original runtime data. No live LLM call is required for this build.


## Build 6: hierarchy-aware evidence retrieval

Q&A uses retrieval.retrieve_evidence → metadata-grounded context → the unchanged
AI provider. QAResult carries answer, sources and RetrievalResult; tuple unpacking
and indexing still expose (answer, source labels) for existing callers.
The basic search_database and get_all_chunks APIs remain for compatibility;
assessment retains its existing generation workflow, using the shared filter builder.

Exact optional filters: course, semester, subject, unit, material_id. Material
selection uses the registered UUID, never filename guessing. The shared builder
also supports source for the existing assessment API. Multiple filters use $and.
Ask a Question offers SQLite-backed cascading controls and an All/no-filter option
at every level. Legacy content lacking deeper metadata remains broadly/course-
searchable; exact deeper/material filters naturally exclude incompatible records.
No production vectors are migrated, and no missing academic hierarchy is invented.

The current course_material collection was inspected read-only and via a temporary
copy: its HNSW space is cosine (not assumed L2). Chroma returns cosine distance,
1 minus cosine similarity, where lower is nearer. RAG v2 refuses unknown/non-cosine
collections rather than applying an incompatible cutoff or altering an index.
Tiny negative floating-point roundoff is clamped to zero; invalid distance results
are rejected. Missing distances/IDs or mismatched response lists fail closed.

Independent retrieval settings, read per request:

- EDUAGENT_RAG_CANDIDATE_K: 15 by default.
- EDUAGENT_RAG_FINAL_K: 5 by default.
- EDUAGENT_RAG_MAX_DISTANCE: 0.65 by default, inclusive cosine-distance cutoff.

Counts must be integers in 1–200, with candidate_k >= final_k. Distance must be
finite and within 0–2. Explicit retrieve_evidence overrides take precedence.
The initial cutoff retained PCA evidence (observed best distance ~0.31) and rejected
a baking query (~0.92 best) in the temporary baseline copy. This is an initial
operational policy, not calibrated confidence or a semantic relevance guarantee.
These four baseline examples do not establish broad quality improvement.

Candidates are stably ordered by distance, then deduplicated by exact ID and
NFC/whitespace-normalized text before relevance filtering and final selection.
Case and academic symbols remain significant. Aggressive fuzzy/overlap suppression
is deliberately deferred to avoid dropping distinct facts; no reranker is added.
No surviving evidence means no generative provider call. Empty collections/scopes
are normal no-evidence states; retrieval/configuration failures surface controlled
errors rather than being presented as a successful answer.

Sources are generated solely from evidence metadata, deduplicated per material /
hierarchy / known page. Original source labels are shown, not managed UUID filenames.
Only a positive integer page in metadata can create a page label; text markers and
model-written citations are never parsed as provenance. Image/OCR sources are
page-less. Existing PDF chunks do not store reliable per-chunk pages and remain
page-less until a future ingestion/migration task. Sources identify retrieved
context, not a verified claim-by-claim citation audit of the model's answer.

Development diagnostics show candidate counts, invalid results, duplicates,
relevance rejections, final evidence count, active filters, metric and cutoff.
They contain no chunk text or question and are not persisted. The existing LLM,
embedding model, OCR/identity/deletion and analytics implementations remain intact.
Tests isolate storage and mock provider/collection boundaries; optional comparisons
use only copied Chroma storage and cached embeddings in offline mode.

Material choices include upload timestamps so same-name materials in the same
hierarchy can be selected separately using UUID-backed values. Identical human
source labels are rendered once; distinct material IDs remain in structured
provenance for inspection.


## Build 7: Professor workspace

Professor Dashboard groups Overview, Smart Assistant / Quick Actions, Academic Knowledge, and Recent Activity into tabs. Managed material records form a naturally sorted Course → Semester → Subject → Unit → Material browser. Leaf controls call the existing exact-ID hierarchy/deletion services; edits rerun the browser, deletion requires explicit confirmation, and failures retain service warnings. Legacy registrations remain informational and separate; no managed ownership or missing hierarchy is inferred.

Smart Assistant retains the existing coordinator and dispatch behavior, including quiz_and_notice. Create Assessment temporarily opens Generate Quiz; Question Paper remains available separately. Old navigation states map to the dashboard or Activity Log. Activity Log shows only sanitized known actions and parsed timestamps, never stored details or arbitrary action text. Eight navigation pages remain.

Workspace tests use temporary SQLite/uploads and deterministic vector substitutes. AI is mocked. No production storage migration, re-embedding, provider/model, retrieval, analytics, or assessment behavior changes are introduced.
