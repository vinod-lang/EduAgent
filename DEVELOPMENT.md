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

## Build 14: evaluation V2

Expanded isolated synthetic evaluation compares unchanged prompts with opt-in Ollama response schemas. Product validators, privacy boundaries, production models and RAG configuration remain unchanged. See [Evaluation V2](benchmarks/EVALUATION_V2.md). Structured syntax, service validity and body facts are measured separately; subjective review remains blank. No repair loop/router or default structured mode is enabled. Raw responses remain ignored, and production runtime hashes must remain identical.


## Build 15 — structured generation boundary

Active structured generation now runs through `structured_generation.generate_structured`:
provider-native schema → bounded object parsing → JSON Schema → original product validator.
`StructuredGenerationResult[T]` holds the typed accepted value, failure category,
attempt count, first failure, and response length/hash only. It never logs or stores
prompts, model text, student records, preference text, or retrieved chunks.

Production call audit:
- `assistant_planner.plan_request`: structured ActionPlan; privacy/local student
  gates precede inference; service registry, dependencies and clarification stay authoritative.
- `assessment_studio.generate_assessment`: structured predetermined slots; the original
  evidence, distributions, MCQ/answer, duplicate and PYQ guards remain authoritative.
- `document_studio.generate_draft` / `refine_draft`: structured DocumentDraft;
  optional metadata, template/style precedence and original refinement guards remain.
- `student_support_agent.answer_question`: grounded free-form text, unchanged evidence gate.
- Legacy compatibility APIs `assessment_agent.generate_questions` (JSON array),
  `document_agent.generate_document` (prose), and `coordinator.classify_intent`
  (text label) retain their public contracts and central provider. Current Studios
  and assistant planning do not use these old output contracts.

All three structured features default to `retry=False`; callers may explicitly
opt into a single structural retry. Maximum two generation calls. Planner schema
violations are conservatively non-retryable because policy and shape overlap;
malformed JSON can retry. Enum/constant/count violations and all product validator
failures never retry. Retry feedback is one generic sentence without prior output.
Provider connection/timeouts never retry. No general JSON repair exists.

Only exact JSON, one `json` fence, or `Here is the result:` followed by a newline
and one object are accepted. Duplicate keys, nonfinite literals, competing content,
arrays and arbitrary prefixes are rejected. Planner parsing caps at 30,000 characters;
other structured responses cap at 1,000,000, with existing product budgets retained.

Document explicit date/reference/recipient/sender/signature/title/subject fields
are checked in their corresponding output fields. `generate_draft` optionally
accepts `required_body_facts` (at most 20 explicit literal strings, each ≤500 chars),
for professor/caller-supplied amounts/counts or other facts that MUST appear in body.
Whitespace normalization only; no semantic guessing, extraction from free prose,
value repair, or fact invention. This opt-in contract is not a new UI control and
is not persisted in version history. Free-text fact preservation still requires
professor review. Existing refinement numeric guards remain conservative rather
than a semantic guarantee. Request facts > template layout > approved style.

Schemas draw from product enums, the service registry and deterministic slots;
contract synchronization tests guard field drift. Historical Build 13/14 schemas
and result interpretation remain unchanged. `jsonschema` is an explicit dependency
already present in `.venv-rebuild`; no package installation occurred.

The current Ollama provider explicitly advertises native structured-output support;
unsupported provider configurations still fail centrally. Runtime-specific support
for the full JSON Schema grammar (including tuple slots) was not live-tested in
Build 15. Unsupported grammar fails visibly; no model-specific workaround exists.
No model router, production model/default/RAG/embedding change or live inference.


## Build 16 — professor validation and document fact continuity

`generation_diagnostics` defines typed safe failures, validation statuses and
technical provenance. `generation_ui` is the reusable workflow renderer.
Expected generation failures retain their existing public exception classes and
carry a safe diagnostic (category/attempt count, no raw payload). No schema,
provider internals, paths, tracebacks, rejected text or private facts are rendered.
Validation means contract acceptance, not factual accuracy. Success remains
subject to professor review. Assessment summaries present the existing validator
results. Planner clarification/refusal and execution partial failures remain distinct.
RAG still uses its original evidence gate; Student Data Hub remains deterministic.
No new Activity Log payloads or generation-status events were added.

Document facts originate only from nonempty explicit structured request fields,
explicit caller-designated body facts, or explicit professor fact management.
`DocumentFactExpectation` records identity, field, source, value, required state,
and confirmation timestamp. No free-text prose is promoted automatically.
Body constraints are literal phrases with whitespace normalization and numeric/word
boundaries; this is not semantic equivalence or comprehensive hallucination detection.

Each `DocumentVersions` snapshot owns its fact tuple and generation provenance.
Edits that conflict are held in session for explicit resolution; current preview,
downloads and storage retain the previous valid version. Professors may explicitly
update confirmed facts and apply the edit, or retain constraints and revise the edit.
Changed body facts require explicitly entered replacement phrases. Removing a fact
is an explicit action; its prior snapshots remain auditable. Matching fact management
creates a new version even if document content is unchanged. Fact updates are never
silent document corrections. Refinement receives protected facts and revalidates
before adoption, even when the instruction requests an explicit change. Change the
confirmed fact via professor editing first. Restore pairs historical content with
that historical version's expectations/provenance, creating a new restore version.

Explicit Save/Update atomically writes additive `document_fact_expectations` and
`document_generation_provenance` tables linked to `document_versions`. Initialization
is idempotent and happens only at an explicit repository write. Loading legacy
Build 9/10 histories does not migrate or infer historical facts. Saved snapshots
cannot be overwritten. Provenance records configured provider/model, UTC time,
attempts, validation status, grounding, preference application and professor editing;
no raw prompts/responses are persisted as diagnostic metadata. Accepted document
content continues to use the existing explicit-save repository.

Fact values are private document metadata: they appear only in the professor's
fact-management UI, document lifecycle storage and protected refinement constraints.
They do not enter Activity Log, Chroma, benchmark datasets or exported content.
Exports use the current applied document, without extra provenance/fact sections.
Facts removed from current constraints remain in historical snapshots intentionally.
Assessment/planner provenance is session-only because those workflows have no
artifact persistence layer. No production LLM/embedding/RAG settings changed.
No live inference is needed for Build 16 checks.

## Build 17 — evaluated AI profile and portable exports

The centralized production profile now prefers `qwen2.5:3b`, with explicitly
configured `llama3.2:3b` fallback. Embeddings remain `all-MiniLM-L6-v2`;
dense retrieval uses candidate K 15, final K 5 and cosine-distance cutoff 0.50.
Reranking and model routing remain disabled. This recommendation follows the
user-supplied October 2026 Linux RTX 3050 evaluation; Build 17 does not rerun
benchmarks. The cutoff was evaluated with synthetic inputs and is not a universal
quality guarantee. Validate it against an approved real NIT course corpus before
claiming institutional retrieval quality. Historical benchmark artifacts are unchanged.

Configuration precedence:

- `EDUAGENT_LLM_PREFERRED_MODEL` overrides legacy `EDUAGENT_LLM_MODEL`, then the
  centralized Qwen default applies.
- `EDUAGENT_LLM_FALLBACK_MODEL` defaults to Llama; `none` disables fallback.
- `EDUAGENT_RAG_DISTANCE_THRESHOLD` overrides legacy `EDUAGENT_RAG_MAX_DISTANCE`.
  Explicit retrieval arguments take precedence over environment values.
- Existing provider URL/timeout and candidate/final K settings remain available.
- `EDUAGENT_EMBEDDING_MODEL` only accepts the existing MiniLM identifier. Changing
  embedding spaces requires a separately reviewed migration, which this build forbids.

Rollback without source edits: set `EDUAGENT_LLM_PREFERRED_MODEL=llama3.2:3b`
and `EDUAGENT_RAG_DISTANCE_THRESHOLD=0.65`. No `.env` file or secret is required.
An unavailable preferred model uses only the configured, already installed fallback.
If neither is installed, generation fails with an actionable controlled error.
Model discovery calls Ollama's local inventory API: it never pulls, installs,
downloads, executes shell commands or invokes cloud providers. Transport or generation
failure does not trigger a second model call. Explicit per-call benchmark/model
arguments remain exact overrides, with no automatic fallback. This is a single default
model policy, not task-based routing. `get_ai_stack_status()` is an explicit inventory
read, not generation; it reports the effective profile without paths or service URLs.
Successful generation provenance records the effective model and fallback state.
Legacy saved provenance without the new optional fields remains readable.

Assessment normalization accepts only the equivalent four-single-key A/B/C/D
option-list representation and converts it into the canonical option mapping.
Missing, duplicate, unknown, nested or ambiguous options remain rejected. It does
not fix question content, answers, distributions, evidence or malformed JSON.
The unchanged schema and product validators remain the final acceptance authority.
Only aggregate normalization flags/types are retained, not rejected raw output.
The no-evidence gate still rejects insufficient retrieval before any model call.

PDF exporters share `font_resolver`. `EDUAGENT_PDF_FONT` provides a local font path;
existing `EDUAGENT_DOCUMENT_FONT` / `EDUAGENT_ASSESSMENT_FONT` overrides take
precedence for their exporters. Explicit invalid overrides fail visibly rather than
silently selecting another font. Without an override the resolver checks known
macOS, Linux and Windows fonts and verifies coverage for the actual text.
No font is downloaded or bundled. Future packaged DejaVu fonts require a reviewed
redistribution license placed beside them; mere resolver support is not a license
review. Missing fonts or unsupported glyphs produce a safe actionable export error.
Cross-platform path selection is tested deterministically; actual deployment font
availability still requires an on-machine check. Legacy compatibility exports keep
their existing behavior and are not redesigned here.

Production SQLite, upload and Chroma files are not migrated or reindexed. All new
checks use isolated storage and mocked model boundaries, with no live inference.

## Build 18 — application use-case boundary

Before Build 18 the UI mixed rendering/session orchestration with calls into
agents, lifecycle functions and repositories; Assessment Studio also queried
legacy SQLite scope directly. Most actual product validation, calculations,
structured generation and persistence already lived outside Streamlit.
This build preserves those tested implementations and puts application services
between active widgets and their operations.

```text
Streamlit rendering / widgets / navigation / session state
                         ↓
application.create_application_services()
                         ↓
Material / Knowledge / Assessment / Document / Student / Assistant
                   Activity / Dashboard services
                         ↓
Existing domain validators, lifecycle, repositories, retrieval
                         ↓
Central AI provider / lazy vector storage / SQLite / managed files
```

Architecture inventory and separation:

| Active workflow | UI responsibility | Application boundary | Existing domain/storage/AI responsibility |
|---|---|---|---|
| Professor Dashboard | Cards, tabs, navigation, delete confirmation | Dashboard workspace queries; Material and Activity services | Existing deterministic summary/tree and registry/lifecycle; no generation |
| Smart Assistant | Request collection, session invalidation, preview, explicit execute/retry | Assistant plan/preview/validate/execute | Existing planner/provider and allowlisted executor; privacy/confirmation/dependency rules unchanged |
| Upload Content | Bytes and hierarchy collection, progress and outcomes | Material upload/edit/delete/get/list/hierarchy | Existing UUID/hash/Unit lifecycle, extraction, vector/SQLite/file rollback |
| Ask Knowledge Base | Scope widgets, answer/source/diagnostic presentation | Knowledge ask/retrieve | Existing hierarchy-aware retrieval, no-evidence gate and centralized provider |
| Assessment Studio | Specification controls, session fingerprint, preview/download buttons | Assessment generation/PYQ extraction/exports; Material scope queries | Existing plan/schema/product validation, normalization, evidence and exports |
| Document Studio | Editor fields, explicit fact/preference decisions, session versions | Document generation/refinement/edit/save/load/history/restore/facts/feedback/exports | Existing facts, version snapshots, preference-aware generation and document repository |
| Student Data Hub | Upload/mapping confirmation, session cleanup, display/search controls | Student parse/table/suggest/normalize/analyze/filter/export | Existing local ingestion and deterministic analytics; no student AI or persistence |
| Activity Log | Action/timestamp display | Activity recent | Existing allowlisted labels and timestamp sanitization; raw details excluded |

`application/` contains eight use-case services across focused modules, plus
contracts, errors and a composition root. It has no Streamlit, direct Ollama or
Chroma-client dependency. Imports and construction do not open databases, load
embeddings or initialize vector clients. `initialize_local_storage()` is an
explicit compatibility startup operation used by the current Streamlit entry
point, never an import/factory side effect. Runtime tests use isolated paths.

Transport-neutral dataclasses add `KnowledgeRequest`, `MaterialUpload`,
`AssistantPreview`, and `StudentAnalysis`; strong domain types (AssessmentSpec,
DocumentRequest/Versions, ActionPlan, QAResult, GenerationDiagnostic) are reused.
Exports return bytes, not file handles. StudentAnalysis keeps the existing local
DataFrame but offers an explicit JSON-safe records/summary conversion with missing
nonfinite values represented as null. Other domain dataclasses can be serialized
by a future transport adapter; no HTTP serializer or endpoint is introduced.
Material results retain their established dictionary/count/partial-failure contract.
No UI components, DB cursors or Chroma clients are returned.

Expected domain failures map to stable application errors: validation, not found,
conflict, insufficient evidence, unsupported operation, provider unavailable and
storage error. Public code/message and existing safe generation diagnostics contain
no raw responses, paths, SQL or private values. Only allowlisted constant student
file-format and material extraction/OCR errors retain their detailed wording. Exception causes remain available
to developers; future HTTP handlers must serialize only the public contract, not
exceptions/tracebacks. Material partial-failure counts and success flags are retained;
raw legacy rollback/client errors are replaced with safe review guidance. Unexpected
developer errors are not swallowed. Existing validators remain authoritative.

Factory arguments accept configured service instances. Service constructors accept
simple module/callable dependencies for domain agents, retrieval, repositories,
exports, planner/executor and ingestion, plus managed upload/vector boundaries.
Defaults resolve at use rather than import, preserving lazy resources and existing
mock seams. Dashboard workspace queries return current summary, materials, courses
and saved-draft metadata without generation or invented pending workflow state.
AI-stack status remains the existing explicit inventory-only backend operation;
it is not automatically called while rendering the Dashboard.

REMAINING_UI_COUPLING (intentional incremental boundary):

- UI still constructs validated domain request/specification/mapping dataclasses and
  uses pure hierarchy/template/diff helpers, domain constants and safe diagnostics.
- Session fingerprints, selection invalidation, explicit plan confirmation/retry and
  document editor/version presentation remain in Streamlit. Document refinement UI
  uses two service calls rather than the combined `DocumentService.refine()` use case;
  the combined method is available to a future API caller.
- Student sheet selection/validation-report presentation and widget cleanup use the
  existing local domain objects/session cleanup helper. No student payload is sent
  to AI; application contracts do not accept Streamlit session state.
- Legacy unused agent callbacks/imports remain in the workspace presentation
  signature for compatibility. Active generation paths use application services.
- Current SQLite domain modules still resolve `db.DB_PATH` globally. Repository/agent
  injection is supported at boundaries, but concurrent professor-scoped transactions,
  serialization and resource lifetimes need a subsequent backend design. Do not
  treat this build as a multi-tenant or thread-safe deployment architecture.

A future FastAPI composition root can call the same factory with configured services
and serialize the existing domain/application results. No FastAPI, authentication,
HTTP endpoints, new persistence schema, model routing or frontend rewrite is added.
`ProfessorContext` is an optional unset caller-identity contract only: it grants no
permissions, filters no rows and fabricates no professor identity. Authorization
must be implemented and tested separately before multi-professor deployment.
Build 17 profile and retrieval defaults are unchanged; no benchmark or live AI
calls are needed in this build. Production runtime storage and the locally excluded
nested accidental clone must remain byte-for-byte unchanged.

## Build 19 — identity and authorization foundation

Build 19 supersedes Build 18's optional identity placeholder. The default
`create_application_services()` returns protected services and denies missing
identity. Identity is passed explicitly on every operation, never stored as a
process-global current user. The current Streamlit composition explicitly selects
`development_legacy_context()`: this remains single-user development compatibility,
not authenticated or production multi-professor access. There is no login UI.

Future trusted authentication → ProfessorContext → repository-backed policy
→ protected application services → scoped repositories/retrieval → storage/provider.

Professor, institution, department and course identifiers are opaque UUIDs.
Repository-backed active status, roles and explicit course membership determine
access; names, filenames, document content and LLM output never grant permission.
Contexts are not credentials: a future backend must construct them from trusted
authentication, not accept claimed identity directly from request JSON.

PRIVATE resources are owner-only, including against administrators. COURSE reads
require explicit membership in the matching institution/department/course.
DEPARTMENT reads require the matching department; INSTITUTE reads require the
matching institution. There is no public scope or cross-institution administrator
bypass. Department/institute sharing requires the corresponding administrative
role. Shared-resource mutation permits the owner or the applicable scoped
administrator; private documents and preferences never become shared. Unknown,
inactive, malformed or contradictory identity/ownership defaults to denial.
Absent ownership records are legacy, not implicitly public or assigned to a
fabricated professor. Scoped lists exclude them; guessed inaccessible resource IDs
return the same not-found result as absent IDs for valid actors.

The lazy SecurityRepository has explicit additive, transactional, idempotent
initialization for professor/course/membership/ownership/audit companion tables.
No production database migration or backfill is performed in this build. Trusted
offline bootstrap provisions the first administrator; subsequent identity and
membership administration is policy-controlled. Material, document and preference
creation registers ownership in the existing SQLite transaction. The security
repository and domain repository must use the same SQLite unit of work. Existing
Build 18 classes and low-level repositories remain trusted internal compatibility
adapters; future external interfaces must use the protected composition root.

Material lists are SQL-scoped. Retrieval obtains authorized material IDs before
querying Chroma and adds a mandatory material-ID allowlist to the query filter.
Legacy/unowned chunks are excluded. Returned IDs and permission revocation are
checked before provider use; the existing deterministic no-evidence gate remains.
New chunks include owner/institution/department/course/scope metadata alongside
material ID and course/semester/subject/unit. SQLite ownership is authoritative.
Explicit sharing changes that registry with a compare-and-swap update, without
rewriting existing vectors. Vector scope labels describe creation-time metadata
and can be stale after sharing; they never independently grant access.

Document bodies, versions, confirmed facts, feedback and provenance inherit private
document ownership. Approved preferences are SQL-scoped and only the authorized
preference tuple reaches generation. Assessment evidence uses the same authorized
retrieval boundary; generated assessment workspaces are private and ephemeral.
Assistant actions are individually authorized through the fixed service registry.
Confirmation, dependencies, refusal, bounded retries and partial failures remain
intact; retained retrieval evidence is reauthorized before retry reuse. Student
workspaces are owner-bound, local and ephemeral; records do not enter the planner,
provider, Chroma or new persistence. Audit entries contain approved action labels,
actor/resource identifiers and timestamps only, never prompts, bodies, facts,
preferences, student records or arbitrary details.

Security invariants:

1. Missing context never falls back to development compatibility.
2. Repository-backed active identity is required before protected reads or writes.
3. Unknown or inconsistent ownership grants no access.
4. Private ownership has no administrator bypass.
5. Membership is explicit, not inferred from academic labels.
6. Permission filtering precedes retrieval and generation.
7. Documents and preferences remain private across lifecycle operations.
8. Each assistant action and retained evidence is reauthorized.
9. Student data remains deterministic and local.
10. Imports, factories and tests do not initialize or migrate production storage.

Remaining boundaries: this is not authentication or a production multi-tenant
backend. Existing SQLite domain modules still use DB_PATH; trusted composition
must configure a consistent repository. Authorization and cross-storage writes
cannot eliminate every concurrent revocation window without stronger transaction
and locking design. Domain workspace objects must remain trusted server-owned
objects, not deserialize unchecked ownership claims from clients. Global file-hash
deduplication is preserved; inaccessible matches reveal only a generic duplicate
outcome, not another professor's filename/ID. Legacy adoption/backfill needs a
separate explicit, auditable workflow. No Chroma reindex, ranking/model change,
HTTP API, deployment or model inference is introduced.

## Build 20 — versioned local web backend foundation

Browser → FastAPI → session authentication → trusted ProfessorContext
→ Build 19 authorization → application services → domain / storage / AI.
Streamlit remains an independent presentation adapter using explicit single-user
development compatibility; it does not call FastAPI. No frontend or deployment
is introduced.

`api.create_api_app()` supports injected services, sessions, settings and ephemeral
workspaces. Import/factory creation does not create databases, sessions, Chroma
clients, embeddings, models or servers. All HTTP resources live under `/api/v1`.
Development OpenAPI is `/api/v1/openapi.json`, interactive docs `/api/v1/docs`.
Request/response Pydantic v2 schemas forbid extra request fields. Domain validators
remain authoritative, including Qwen normalization, evidence checks and fact
continuity. Responses use allowlisted projections, never recursive serialization
of internal domain dataclasses, prompts, rejected output, provenance or paths.

### DEVELOPMENT AUTH ONLY

This is a controlled seeded-identity selector, not production authentication or
institutional SSO. Development authentication requires **both** explicit
`EDUAGENT_API_MODE=development` and `EDUAGENT_DEV_AUTH=true`, a configured alias
allowlist and a private random `EDUAGENT_DEV_ACCESS_KEY` of at least 32 characters.
Login requires `X-Development-Key`. The frontend developer must obtain that key
out-of-band; do not embed it in distributable frontend assets, commit it or put it
in localStorage. This mechanism is only suitable for trusted local development.
Production/institutional modes refuse development login, and enabling dev auth in
those modes is a configuration error. No password database or fake production
identity provider exists. Future institutional authentication must issue the same
server-side principal through a separately implemented, reviewed provider.

Explicit offline provisioning uses **separate** development runtime storage:

```sh
.venv-rebuild/bin/python -m api.bootstrap --database .runtime/api-development.sqlite3
```

The output contains aliases and opaque IDs only. Configure that JSON privately as
`EDUAGENT_DEV_IDENTITIES`, generate a private development access key with standard
secure randomness, and set the two development flags above. Do not use the original
`eduagent.db`, `uploads/` or `chroma_db/`. Defaults are separate `.runtime/` SQLite,
upload and Chroma paths; `.runtime/` is ignored. API path overrides are
`EDUAGENT_API_DB`, `EDUAGENT_API_UPLOADS`, `EDUAGENT_API_CHROMA`. No vector ownership
backfill or reindex occurs. Bootstrap is explicit and never performed on startup.
Repeated bootstrap creates additional fictional identities rather than assigning
ownership to existing data.

Start the local backend after explicit provisioning/configuration:

```sh
.venv-rebuild/bin/uvicorn api.app:create_api_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Use one process: ephemeral workspaces are deliberately process-local. Development
reload is optional and discards these workspaces. No server is started by tests.

### Sessions, cookies and CSRF

`POST /api/v1/auth/dev-login` accepts a configured alias, never arbitrary trusted
professor/role/institution claims. The server verifies an active repository
identity and issues a cryptographically random session token. SQLite stores only
its SHA-256 digest and a separate CSRF-token digest, professor ID, creation/expiry
and revocation timestamps. Tokens are opaque, not JWTs. A session lasts one hour
by default; expiration, logout and inactive/unknown professors are rejected.
Authorization reloads repository metadata; permissions are not cached in cookies.
Login rotates an existing valid session; logout revokes it and clears workspaces.

The session cookie is HttpOnly, SameSite=Strict, scoped to `/api/v1`, with bounded
Max-Age. Secure is enabled outside local development; local HTTP does not provide
TLS security. The session token is never returned in JSON. Login returns a
session-bound CSRF token for in-memory browser use. Protected POST/PUT/PATCH/DELETE
require `X-CSRF-Token`; reads do not. `GET /auth/csrf` rotates the mutation token.
Login itself requires JSON and a private custom header and rejects browser origins
outside the configured allowlist. CORS is restrictive by default; configure exact
`EDUAGENT_API_ORIGINS` values separated by commas, without trailing slashes.
Wildcard credentialed CORS is forbidden. No JavaScript-visible auth localStorage.

### API surface and private transient state

- Authentication: development login, current safe profile, CSRF rotation, logout.
- System: process health, configuration readiness and authenticated AI profile.
  Readiness explicitly does not probe/open storage and does not claim production
  readiness. AI status reports configured settings; effective model/fallback are
  unknown until actual provider use, and no inference/inventory call is performed.
- Materials: authorized list/get/hierarchy/upload/hierarchy update/cross-storage
  deletion. Uploads are private; ownership is not accepted from request JSON.
- Knowledge: grounded answer and authorized source references. Chunk text and raw
  retrieval distances are not returned by the retrieval endpoint.
- Assessments: validated quiz/paper generation, session-owned PYQ guidance and clean
  PDF/DOCX export. PYQ handles cannot cross sessions.
- Documents: private list/load/generate/edit/save/refine/version metadata/restore,
  explicit confirmed facts and conflict resolution, feedback/preferences, exports.
  Failed edits/refinements do not replace the valid workspace.
- Students: bounded ephemeral CSV/XLSX upload, explicit mapping/normalization,
  deterministic analysis/filtered CSV export and clear. Raw workbooks are discarded
  after successful normalization; clearing a dataset invalidates dependent plans.
  Student records never enter AI or new persistence.
- Assistant: server-stored plan, preview and explicitly confirmed execution/retry.
  Clients send handles, not executable plan JSON or ownership dataclasses. Each
  action still passes Build 19 authorization and fixed registry validation.
  Execution responses contain safe statuses; generated action payloads remain in
  the server-side report in this initial API (artifact handoff is future work).
- Dashboard/activity: deterministic authorized summaries and actor-safe events.

Ephemeral handles are tied to a session, expire with it, and are bounded (100 per
process). They are not persistent artifact IDs. Per-workspace locks serialize edits
without holding one global lock during all model operations. Logout/expiry clears
state; this is not a distributed session/artifact cache. Confirmed private facts
are returned only by their explicit owner-authorized workflow, never generic logs.
Exports contain professor-approved content, not generation diagnostics/model IDs.

### Transactions and concurrency

SQLite connections are opened/closed per operation. A ContextVar selects the
request's database; it does not mutate the Streamlit DB_PATH or share a connection
between threads. API domain calls enter that context on the same worker thread.
The security/session repository uses the same explicit database path. Foreign keys
are enabled and busy timeout is bounded at five seconds. WAL is intentionally not
enabled: no persistent journal-mode change is needed for this foundation.

Sensitive professor writes, membership read/modify/write, ownership sharing,
material registration and document save obtain explicit SQLite write transactions.
Creation and its ownership/audit registration commit together; audit failure rolls
back registration. Membership and sharing audits commit with those changes.
Existing cross-storage vector/file rollback and deletion partial-failure behavior
remain authoritative; SQLite cannot transactionally commit Chroma/filesystem work.
Saved document histories retain existing immutable-version checks. There are still
short cross-operation authorization/revocation windows: this is not serializable
cross-storage multi-tenant deployment. Future external administrative endpoints
need equivalent transaction-scoped authorization, not direct repository access.

### Errors, logging, headers and future seams

Responses use `{error: {code, message, request_id}}` with sanitized 401/403/404/409/
422/503 and unexpected 500 handling. Validation errors never echo submitted input,
SQL, paths or raw model output. Every request receives a generated UUID correlation
ID; client-provided IDs are not trusted. Bodies are capped at 11 MiB before parsing,
with 10 MiB application upload limits. There is no custom payload/credential logging;
keep development access logging disabled. Operators must configure future proxies
and observability so credentials, cookies, query content and private data are not
captured.

Baseline headers: nosniff, no-referrer, frame denial and no-store. Production CSP,
HSTS/TLS, proxy trust, institutional authentication and deployment remain deferred.
Rate-control seams are API route groups/dependencies: development login, uploads,
generation, exports and assistant execution require rate limits before deployment.
No in-memory limiter is claimed to be production-safe. Long-running operations are
synchronous worker calls; future SSE/job APIs should wrap application results with
cancellation and safe status contracts. No background workers, token streaming,
Redis, frontend, production SSO, model routing or deployment is introduced.

## Build 21: professor web workspace

`frontend/` is a separate Next.js App Router application (React, strict TypeScript,
Tailwind and Lucide). FastAPI remains the authority for authorization, persistence,
retrieval and generation. Streamlit remains the reference workflow for features
marked Upcoming in the web workspace. No backend contract changed in this build.

### Local setup

Use an existing supported Node environment and run `npm ci` inside `frontend/`.
Copy `frontend/.env.example` to the ignored `frontend/.env.local`; configure the
backend origin and permitted development identity aliases. Start the existing
FastAPI development bootstrap with an isolated/local development identity mapping,
then `npm run dev` in `frontend/`. Use `http://127.0.0.1:3000` consistently and permit
that exact Origin in backend CORS. Do not mix localhost and 127.0.0.1 for cookies.
The development key must match the backend and remain server-only; never use a
NEXT_PUBLIC key. The alias selector is local development authentication, not
institutional authentication. Production builds disable this sign-in route even
if development flags are supplied. Institutional login remains future work.

The Next server proxies `/api/v1` to FastAPI. Its development-login route checks
same-origin JSON and configured aliases, injects the server-only development key,
and forwards the backend HttpOnly cookie. Other mutations use an in-memory CSRF
token fetched from the backend. No identity/token/question/answer is stored in
localStorage or sessionStorage. Session verification gates protected routes and
backend 401 responses clear the client authentication state. Backend authorization
is mandatory regardless of client filtering.

### Product scope and operation contracts

Home reads real dashboard counts, recent material/activity and saved-document
metadata. The library is read-only and filters authorized material hierarchy.
Knowledge supports hierarchy/material scope, loading, no evidence, safe failures,
plain-text escaped answers and source references. Saved-document metadata currently
has no title; generic labels describe entries rather than inventing document titles.
Assessment, documents, student analytics, assistant and activity navigation explicitly
identify forthcoming web workflows; they do not pretend to execute operations.

Knowledge generation remains synchronous. Stop waiting aborts the browser request;
it does not claim to cancel backend inference. Failed generation is never retried
silently. A future asynchronous operation requires a backend-owned operation ID,
authorized status/cancellation contract and explicit timeout semantics.

Future Assistant artifact handoff should use an authorized server-owned artifact
handle and typed destination (assessment/document), not client-supplied executable
function names or raw content in URLs. This build does not implement that handoff.

### Verification

Run `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` in frontend.
Tests mock API boundaries and cover auth, CSRF, safe errors, route protection,
dashboard, library, Q&A and development-login secrecy. Axe component checks cover
semantics; jsdom cannot verify rendered color contrast. An additional Chrome smoke
used an isolated FastAPI service with synthetic material and mocked generation,
checking real cookies, CSRF, source rendering, mobile drawer/Escape, overflow and
logout. Production storage was not used. No live model calls were needed.

Pinned dependencies and package-lock make installation reproducible. npm currently
reports five high advisories in the development ESLint transitive braces/micromatch
chain; its proposed fix downgrades the Next lint configuration across major versions.
Do not force that downgrade. Track an upstream compatible fix. Production dependency
audit is checked separately. Build output, node_modules and private env files stay
ignored. This frontend is not a deployment or an institutional authentication rollout.

## Build 22: course and material workspace

The web frontend now has real `/courses`, `/courses/[course]`, `/library`,
`/library/upload` and `/library/[identity]` workflows. Course projections derive
solely from authorized material metadata; an empty course is not invented, and
coverage is registered material coverage rather than enrollment or learning progress.
Semester/Subject/Unit groups use collapsible semantic navigation. Course names are
encoded in routes and decoded once; material operations always use stable IDs.

The library searches metadata, cascades Course → Semester → Subject → Unit filters,
and pages the authorized response in deterministic groups of 20 (timestamp descending,
material ID tie-break). This is client pagination: the API still returns the complete
authorized list. Server pagination is deferred until library scale justifies it.
Mobile tables omit the upload-date column, retain academic placement/actions and fit
the page; complete metadata remains on material detail.

Upload uses the existing protected multipart endpoint for PDF, PNG, JPG and JPEG.
The displayed state is Processing material, not invented ingestion phases or byte
percentages. The API file cap is 10 MiB and configured lifecycle limits may be lower.
Frontend extension/size checks are convenience only. Local PDF/OCR extraction and
managed UUID/hash ingestion remain authoritative. Exact-content duplicates do not
create a second material. Failure feedback does not imply successful registration.
New uploads remain PRIVATE; this build adds no sharing administration.

Placement controls offer scoped existing values and allow new text. Whitespace is
trimmed and known values are canonicalized case-insensitively in parent-first order.
Backend validation remains authoritative; this is not a curriculum normalization
migration. Direct callers can still supply case variants supported by older APIs.

Material detail presents filename, hierarchy, upload date, type, safe visibility
and management availability. Updates/deletions wait for confirmed backend results.
Deletion uses a native modal dialog with safe initial focus, Escape and explicit
confirmation naming the material. Partial failure remains a warning requiring local
storage review; no broad cleanup or automatic destructive retry is introduced.

### Minimal API contract changes

GET `/api/v1/materials/{identity}` adds `visibility` and `can_manage`, derived by the
existing scoped application service after READ authorization. It exposes no ownership
IDs, chunk IDs, hashes or paths. Backend policy remains authoritative for mutations.
PATCH of that resource returns `status` and `success`: incomplete lifecycle updates
no longer falsely return an unconditional updated status. Existing successful callers
continue to receive `status: updated`. Other material endpoints and RAG defaults are
unchanged. No storage migration is required.

### Knowledge handoff and verification

Course, subject, unit and material actions pass only structured scope metadata/IDs
in URLs. Knowledge shows Current scope and Clear scope, resets on URL handoff, and
loads options from authorized material metadata. Scope controls are disabled while
metadata loads. Backend permission/relevance gates remain unchanged. No evidence
provides scope/question guidance and a real upload link; no ungrounded fallback occurs.

Run frontend tests/lint/typecheck/build and the complete isolated Python suite.
Frontend synthetic tests cover course projections, pagination/filter reset, multipart
CSRF, duplicates, failures, edit, confirmation/partial deletion, scope and accessibility.
HTTP tests cover safe detail metadata, private isolation, course membership, read-only
management denial, truthful lifecycle outcomes and browsing without vector/AI loading.
A Chrome smoke used a real synthetic PDF, isolated SQLite/uploads and in-memory vector
fixtures with mocked inference: login → upload → course/material → unit-scoped answer
→ edit Unit → updated library filter → confirm deletion → empty course/library → logout.
It checked mobile page overflow and native dialog focus/Escape. Production storage and
the locally excluded nested clone remain untouched. Temporary test servers are stopped.

Assessment Studio frontend remains the next build; Streamlit reference workflows
and unrelated frontend Upcoming destinations are preserved.
