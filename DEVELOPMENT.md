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
