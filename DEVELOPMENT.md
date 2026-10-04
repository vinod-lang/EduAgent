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


## Build 8: Unified Assessment Studio

Assessment Studio replaces Generate Quiz and Question Paper navigation with one Quiz/Question Paper workspace. Dashboard Create Assessment opens it. Old navigation states map to Studio; Analytics and Smart Assistant retain their existing internal quiz APIs, including quiz_and_notice. Those legacy generation paths are compatibility paths, not the new validated Studio workflow.

`assessment_spec.py` owns immutable academic scope, exact question-type/difficulty/six-level Bloom counts, positive integer marks and deterministic question slots. Marks use quotient/remainder allocation, with extra marks assigned to earliest slots. Counts are limited to 100 questions and 10,000 marks. Scope requires actual Course/Semester/Subject and one or more Units; optional canonical material UUIDs narrow it further. No IDs/hierarchy are invented for legacy material.

`assessment_studio.py` composes exact RAG v2 queries per Unit/material using unchanged K15/final5/cosine/.65 defaults. Results are interleaved deterministically, scope-checked again, and deduplicated across branches. Every selected Unit/material must retain evidence; missing coverage fails closed before generation. Context limits (64 branches, 100 chunks, 60,000 teaching-text characters) fail explicitly rather than silently dropping scope. A query topic is configurable. No reranker, embedding changes or production vector migration occurs.

The model supplies content in strict JSON for the predetermined slots through ai_provider. Validation rejects prose/fences, duplicate object keys/question text/numbers, missing/extra fields, invalid labels, mismatched counts/slots/marks, malformed MCQs, descriptive MCQ structure and invented evidence references. Exactly one generation attempt is made; malformed output requires explicit regeneration. Structural validation cannot establish factual correctness, semantic difficulty or Bloom alignment: professor review remains required. Provenance comes from retrieval metadata, never model filenames/pages.

`assessment_pyq.py` accepts PDF/PNG/JPG/JPEG through existing local extraction/OCR and upload limits. Task-owned temporary directories are cleaned on success/failure; no course registration, SQLite inserts or Chroma ingestion occurs. Up to 20,000 characters provide style guidance, separate from academic authority. Normalized verbatim wording is rejected, but this is not a semantic plagiarism detector or reliable frequency analysis. No cloud OCR is introduced.

`assessment_export.py` produces separate in-memory student papers and professor answer keys in PDF/DOCX. Papers omit answers and retrieval metadata. Descriptive keys are explicitly suggested answers. PDFs use the installed FPDF dependency and a local font covering the text; Arial Unicode (macOS) or DejaVu Sans (Linux) is discovered, or EDUAGENT_ASSESSMENT_FONT selects a local Unicode TTF. Missing glyph coverage fails visibly instead of dropping text. No font/model download occurs. Complex-script shaping and DOCX rendering may vary across viewers.

`assessment_ui.py` owns cascading selectors, counts, plan preview, optional PYQ upload, structured review, distribution summary and separate downloads. Invalid specs disable generation. Changed configuration/PYQ hides stale downloads. A generic assessment_generated activity event contains no paper, answer, prompt or PYQ data. Log failure warns without discarding a validated result. Assessment results persist only in the Streamlit session.

All assessment tests use synthetic data, deterministic collections, temporary storage and mocked AI. Original eduagent.db/chroma_db/uploads must remain unchanged. Seven resulting pages are Professor Dashboard, Upload Content, Ask a Question, Assessment Studio, Draft Document, Analytics and Activity Log.


## Build 8 storage import safety

Importing vector_store or feature agents no longer initializes Chroma, opens a database, creates a collection, or initializes sentence-transformer embeddings. Explicit getters initialize and cache on first storage use: get_embedding_function(), get_chroma_client(path), and get_collection(path, client=..., embedding_function=...). Client/collection caches use absolute paths, so changing working directories does not reuse the wrong store. The embedding model remains all-MiniLM-L6-v2. Explicit production access may still write Chroma bookkeeping; lazy initialization does not make Chroma itself read-only.

EDUAGENT_CHROMA_PATH selects alternate storage, defaulting to ./chroma_db. An explicit path overrides the environment. Vector APIs accept collection injection (bypassing both model and client initialization), and retrieval's existing collection injection remains supported. The RAG default path now calls get_collection() only on an actual retrieval request. Material IDs, exact deletion, ownership checks, hierarchy, ranking, and relevance defaults are unchanged.

Before test-module imports, tests/conftest.py sets offline model flags, an isolated temporary Chroma path, and a temporary SQLite DB_PATH. A suite sentinel snapshots the repository-relative eduagent.db/uploads/chroma_db inventory and hashes before collection and checks them at session finish, failing the process on any difference. No user-specific hashes are hardcoded. Fresh subprocess tests replace client/model constructors with forbidden-call guards and import high-level modules against an isolated sentinel directory. This detects eager initialization despite Python module caching.

The forensic inspection observed segments foreign-key declarations referencing collection while the actual table is collections. This existing third-party schema concern has not been migrated, repaired or changed. The current preserved chroma.sqlite3 hash is a safety-fix comparison point, not a replacement for the historical canonical baseline. Production logical sanity must be inspected using SQLite mode=ro rather than initializing Chroma.


## Build 9: Professional Document Studio

Document Studio replaces Draft Document in the seven-page workspace; its old navigation state maps to Studio and Create Document opens it. The primary input is natural-language instructions. Recipient, sender, title, subject, date, reference, signature and additional context remain optional. The 17-type catalog uses stable identifiers and shared drafting/validation code; email, letter, announcement, memo and report structures differ. Legacy document_agent generation APIs remain unchanged for coordinator and attendance-warning compatibility; those plain-text APIs are not the structured Studio workflow.

DocumentRequest validates instructions/context up to 20,000 characters and optional fields up to 2,000 characters. The provider returns strict JSON; duplicate keys, missing/extra fields, nonfinite values, unsupported types, empty/malformed bodies and control characters fail visibly. Body limits are 100 paragraphs, 10,000 characters per paragraph and 60,000 total. There is one generation attempt, with no automatic repair. Optional recipient/sender/date/reference/signature must match the request exactly; unavailable fields stay empty. Natural-language facts can appear in body text. Prompts prohibit invention but semantic truth is not mechanically provable: professor review remains necessary.

DocumentTemplates define safe ordered placeholders independently of content and renderer. Standard Academic / Institutional is a generic layout, not an official institutional letterhead. No logos or seals are supplied. Custom template upload and arbitrary DOCX layout preservation are deferred; the interface supports future reviewed layouts without executing expressions, macros or template code. DOCX and PDF render from the same current validated draft. DOCX uses A4, 0.85-inch margins, Arial and clear paragraph spacing. PDF uses local Unicode fonts, failing visibly if glyph coverage is unavailable; EDUAGENT_DOCUMENT_FONT selects a local TTF. No font download occurs. Complex scripts are not guaranteed to shape correctly.

Editing is explicit through Apply edits. Preview/downloads use the applied version; unsubmitted form edits are not exported. Original AI draft and applied session versions are separate; undo returns to the previous version. Refinement uses the current draft and centralized provider. Invalid results retain prior state. Style refinements preserve optional facts and numeric tokens; explicit change/correction instructions allow intentional fact changes. This conservative guard is not semantic fact validation.

Saved drafts are explicit: Save Draft/Update Draft create or update document_drafts, leaving legacy documents (a teaching-material registry), materials and vectors untouched. CREATE TABLE IF NOT EXISTS runs only at an explicit save; listing does not create tables. Stable UUID, template, original/current JSON, timestamps and Draft/Final status are stored. Original/current survive reload; intermediate session history does not. No model reasoning, edit preferences, training or automatic learning is stored. Generic generation/save Activity Log events contain empty details, never content or instructions. Saved bodies remain local sensitive data in SQLite; no new encryption/access controls are provided.

All tests use synthetic inputs and isolated storage. Production hashes and the runtime sentinel must remain unchanged. Builds 2–8 behavior, provider defaults and RAG settings are preserved. Build 10 preference learning remains unimplemented.


## Build 10: Professor feedback, persisted history and approved preferences

DocumentVersions now assigns stable UUIDs, UTC timestamps, action sources and restore references to session snapshots. Initial generation, professor edits, AI refinements and restores have explicit sources. Undo/Restore appends a new restored version; no later snapshot is discarded. Save/Update persists all outstanding versions atomically with current JSON. Saved prefixes are immutable and stale/conflicting saves fail, requiring reload. A changed Build 9 current snapshot is labelled legacy_current (action unknown), never an invented professor edit. Loading legacy drafts performs no migration/write; explicit saving adds their known original/current snapshots lazily.

Three additive CREATE TABLE IF NOT EXISTS tables—document_versions, document_preferences and document_feedback—are initialized only on explicit Save/Approval/Feedback writes. Version/document ownership uses foreign keys and composite version/document references, supplemented by service checks; source history cannot be overwritten or crossed between documents. Original legacy documents/materials remain untouched. No production schema operation is performed during this build's isolated tests.

The deterministic diff uses field comparison and SequenceMatcher paragraph opcodes with autojunk disabled. Added/removed/changed content and advisory categories are displayed without JSON. Names/recipient/date/sender/signature/reference and numeric/amount/date-token changes default to factual. Other body changes default to unknown: heuristics cannot prove style or factual correctness. Neither candidate creation, professor edits, Save nor refinement creates an approved preference. Ignored candidates are remembered per version comparison in the session. Before approval the professor must choose a reusable category and write/review a generic instruction; factual/unknown categories themselves cannot be stored as reusable style rules. Generic suggestions never copy document text.

Preferences require explicit Approve Preference or Approve manual preference. Default scope is document-type specific; general and template scopes are available, with optional tone. Stored instructions contain no duplicated source body/diff, only optional document/two-version provenance. Management permits text updates, activation/deactivation and confirmed deletion. Only active approved matching preferences are retrieved. Deterministic ordering is template > document type > general, then additional type/tone specificity, newest update and ID. Known rule topics (opening, paragraph length, ceremonial language, subject placement, signature layout) select only the first applicable preference; identical text is deduplicated. At most eight preferences are supplied. Unknown semantic conflicts are not claimed solved: ordering and visible management remain the fallback.

Generation separates request facts/instructions, template requirements and approved style guidance. Facts/current instructions override style; templates override layout preferences. Prompt guidance is advisory and cannot populate unsupported factual fields. No source document content/IDs, preference IDs or feedback notes are sent as provenance. Refinement retains Build 9's factual guards and creates an ai_refinement version; no preference is inferred automatically. Model/provider defaults, embeddings, RAG and exports remain unchanged. This is local approved guidance retrieval, not model training, fine-tuning or automatic model learning.

Optional Good/Needs Changes feedback belongs to one saved document/version and may have a local private note. It never becomes a preference automatically. Activity events for versions, approval/update/disable/delete and feedback contain empty details. Original/current/full version snapshots remain in local SQLite, so normal local-storage privacy limits apply. Templates do not automatically change PDF/DOCX layout based on preferences; arbitrary visual-template learning is deferred. No multi-professor account isolation is added in this single-local-workspace build.

## Build 11: Student Data Hub

Student Data Hub replaces Analytics in the seven-page professor workspace; old `Analytics` navigation maps to it and Analyze Students opens it. `student_ingestion.py` parses and normalizes; `student_hub.py` adapts the canonical frame to the unchanged Build 3 engine; `student_hub_ui.py` presents one inspect/map/validate/analyze workflow. No second analytics engine or AI-based parsing/calculation is introduced. Existing `analytics_agent.py` APIs and coordinator remain unchanged. Student ID is retained in displayed/exported results; ID-only inputs use the ID as the display label without inventing a name.

Only UTF-8/BOM CSV and XLSX are supported; XLS/XLSM are explicitly rejected. Comma, semicolon, tab and pipe detection is conservative and ambiguous/unreadable input fails visibly. Headers are trimmed for display; blank/duplicate headers receive distinct labels plus warnings, while original labels remain available for suggestions. Blank rows are omitted; source row numbers remain in validation reports. Header suggestions score known aliases in the first 20 rows; the professor always confirms or changes the header. Multiple sheets require an explicit selection, never automatic combination. Hidden sheets are visible as choices with a warning on selection. Preview is limited to 20 rows.

Pinned openpyxl 3.1.5 and defusedxml 0.7.1 read workbooks in memory with `read_only=True`, `data_only=False`, `keep_links=False`; formulas are not evaluated, and formula-valued academic fields/identities are rejected. Macro-containing archives and encrypted workbooks are rejected. Limits are 10 MiB uploaded bytes, 50 MiB expanded XLSX bytes, 2,000 archive entries, 20 sheets, 10,000 data rows per selected table plus at most 20 title/header rows, 100 columns, 1,000,000 total workbook cells and 10,000 characters per cell. Limits fail rather than truncate. Simple all-zero Excel number formats preserve padded numeric identifier display; leading zeros already lost by the source's General formatting cannot be recovered.

Mapping suggestions are deterministic/advisory: aliases for ID, name, attendance and history assessment number, with possible assessment matches. Multiple candidates remain ambiguous and unselected. Professors choose identity/attendance/assessment columns, display assessment names, percentage vs raw marks and positive maxima for raw scores, then explicitly confirm all mappings. `Quiz (20)`/`out of 40` supplies only an editable maximum suggestion. Raw marks normalize to percentages, not raw-score means; selected snapshot assessments are equally weighted by Build 3. No maxima or weights are invented. Unmapped columns are ignored deliberately. History mode maps exactly one score column and a positive integer assessment number, preserving existing Build 3 trend semantics; wide snapshot assessments do not imply chronological trends.

Attendance modes are explicit: Percentage means literal 0–100 numbers or a single `%` suffix; Fraction means literal 0–1, including 1.0 → 100%, and rejects percent notation. Auto accepts 75/75% → 75%, 0 → 0%, 100 → 100%, and 0<x<1 as a fraction with an informational issue; 1≤x<2 is ambiguous and requires an explicit scale (1.0 is not silently chosen as 1% or 100%). Values outside normalized bounds fail; no clamping. Raw `16/20` is accepted only with a matching configured maximum. `23/20`, malformed strings, booleans and nonfinite values are invalid.

Blank/NA/N/A/null/none/NaN/`-` remain missing, never zero. Row issues carry source row, mapped column, severity, stable reason code and generic explanation, not raw cell values. Missing academic fields produce WARNING/incomplete eligible rows; malformed identity/academic values produce ERROR/ineligible rows. Mapped IDs/names must be present; mixed missing IDs do not silently fall back to names. Duplicate IDs (or duplicate name-only identities) are quarantined in full, not merged; distinct IDs with the same name remain separate. History duplicates use identity+assessment number and inconsistent names for one ID are errors. Any invalid history point blocks that identity's whole history until corrected, preventing a misleading latest/trend result from skipped bad points. Exact Average/Total/Class Average/Grand Total identity labels are excluded with INFO only without a competing non-summary ID; exclusion counts and rows remain reviewable.

Normalized snapshot input is `student_name`, optional `student_id`, `attendance_percent`, and selected assessment percentages. History input is `student_name`, optional `student_id`, `assessment_number`, `marks`, `attendance_percent`. Validation reports total/valid/incomplete/invalid/excluded/eligible row counts, warning/error rows, missing cells, duplicate IDs, invalid marks and attendance. Only eligible rows enter Build 3, retaining missing values. Its available-values averages, incomplete/concern overlap, latest/history trends and configurable thresholds remain intact. Counts in the validation report refer to rows; analytics counts refer to students (history may have several rows per student).

Results offer All/Concern/Attendance concern/Academic concern/Incomplete filters and literal name/ID search. Concern uses Build 3's support flag; Academic concern uses its mark/practice flag rather than conflating attendance-only risk. Public support_concern reflects any Build 3 support reason; public academic_concern reflects its mark/practice flag, so attendance-only risk is not mislabeled. The uploader itself enforces 10 MiB in addition to parser/service checks. CSV export matches the current filtered/searched view, includes public identity/status/calculation/reason fields, and omits internal analysis IDs/list/debug fields. A separate validation CSV contains only row/column/code/severity/message. UTF-8 BOM handles Unicode; spreadsheet-active string cells/headers are apostrophe-escaped to mitigate CSV formula injection. No XLSX or new PDF export is claimed.

Student workbooks, mappings, validation and results exist only in session memory; no file is written to uploads, SQLite, document storage or Chroma. No activity event is emitted, so names, IDs, headers and row details cannot enter Activity Log from this workflow. Clear Student Data clears only its state, legacy analytics batch outputs and the uploader's data via a fresh widget key. File/sheet/header/mapping/confirmation/threshold changes invalidate stale results. Downloads are explicit exports under professor control and remain sensitive once saved. Clearing application references is not a guarantee of cryptographic memory erasure or browser/download deletion. There is no multi-user access-control redesign.

The previous analytics UI's AI warning-letter/practice actions are intentionally not offered in the new hub: they send student details to the model and conflict with Build 11's no-student-data-to-AI requirement. Their existing backend compatibility APIs and tests remain intact for future explicit privacy design; coordinator routing is unchanged. No production schema migration, Chroma initialization or data persistence is performed for ingestion. Synthetic in-memory tests cover parsing/mapping/row validation/engine integration, exports and session/privacy/UI behavior. The complete regression suite and runtime sentinel must leave all original production file inventories/hashes unchanged.

## Build 12: Smart Assistant V2

The Dashboard Assistant now proposes strict immutable plans instead of invoking the legacy classifier's hardcoded PCA quiz/plain-text document paths. Existing coordinator classification APIs remain available for compatibility, but are not execution authority. A centralized-provider planner emits only the schema understood by assistant_models. Maximum five unique actions; dependencies must reference earlier actions. The explicit read/generate-only registry exposes knowledge, validated assessments, structured document drafts, local student analysis and known-page navigation. No dynamic imports supplied by the model, arbitrary function/tool names, shell actions, external messaging or persistent mutations are supported. Registry policy, not model JSON, determines confirmation; this build exposes no destructive services and rejects any confirmation-required execution.

Validation uses the existing RAG filter rules, AssessmentScope/AssessmentSpec, DocumentRequest and deterministic Student Hub services. Missing requirements produce structured clarifications, preventing the whole plan from executing. Inferred parameters are visible in the preview; professors correct/add details using ordinary text controls and submit a fresh plan, without editing JSON. Execute is explicit; changed request text invalidates execution. Stable earlier-only dependencies give deterministic ordering. Failed steps block dependents, independent steps continue, and safe retries retain completed results. Retry reports are bound to the plan ID and parameter fingerprint. No final LLM rewrite of results is performed.

Only assessment → document dependencies are supported: title, assessment type and question count. Question text, answer keys, retrieved evidence, source IDs and student results are not transferred. Existing assessment validation is reapplied at the adapter boundary; professor review and separate paper/key exports reuse the Studio renderer. Knowledge retains its typed grounded answer/sources. Documents use the existing preference-aware draft service and factual guards; an explicit Open in Document Studio action transfers a generated session snapshot to existing editing/refinement/history/export controls. Opening replaces the current editor session only by professor choice, never writes/overwrites a saved draft automatically.

Loaded student records are never planner context. Context contains availability and fixed supported operations only. Student filters use a narrow local request grammar (including “Show students with attendance concern”), avoiding AI entirely, and reuse current Hub thresholds unless explicitly overridden. Unknown student-data/personalized requests and loaded identity references are rejected before the provider. This conservative heuristic is not a universal PII detector: professors should not put private data into arbitrary requests. Identifiable data transfer/chaining and personalized advice remain unsupported. Local student outputs are rendered/exported directly; the full class summary and filtered students are labelled separately. Clearing Hub data releases Assistant plan/results too; replacing/revalidating data or changing thresholds invalidates cached Assistant results.

Plans/results/requests are session-only. No Assistant activity event or raw request is persisted. Errors displayed by the orchestrator are generic to avoid leaking provider payloads. This sacrifices detailed on-screen diagnostics; inspect dedicated service availability without logging private prompts. There is no distributed workflow, persistent recovery, arbitrary graph, material mutation, model change, or general agent framework. Academic scope/distributions must be supplied; the planner cannot select invented defaults. Existing Studio validation can reject outputs and factual accuracy still needs professor review. Synthetic mocked tests and fresh-process lazy-storage guards run under the unchanged production runtime sentinel.

## Build 13: isolated AI stack benchmark

The opt-in benchmarks package evaluates synthetic prompts/retrieval without application startup imports or production storage access. Provider instrumentation is backward-compatible: generate_chat retains its original string return and default call options; generate_chat_measured explicitly requests benchmark-only options and token/duration telemetry. Production defaults remain llama3.2:3b, all-MiniLM-L6-v2 and RAG 15/5/0.65. There is no production router, reranker, embedding replacement or reindex.

See [benchmark protocol](benchmarks/README.md) and [measured selection report](benchmarks/SELECTION_REPORT.md). Raw responses/results/caches are ignored; only authored fixtures, harness/tests and sanitized aggregate conclusions belong in source control. Subjective scores remain blank for professor review. The current pilot supports decision D: retain the stack and expand evaluation. Production runtime inventories/hashes must remain byte-identical through all tests.
