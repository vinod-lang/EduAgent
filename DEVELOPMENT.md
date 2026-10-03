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
