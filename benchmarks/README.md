# EduAgent Build 13: isolated AI stack evaluation

This is an opt-in pilot harness, not a production router. Application startup does not import or run it. Production defaults remain llama3.2:3b, all-MiniLM-L6-v2 and retrieval 15 candidates / 5 final / maximum cosine distance 0.65. No production Chroma client, student sessions or private documents are used.

## Synthetic fixtures and protocol

`fixtures/synthetic_v1.json` contains 18 authored academic chunks, 15 retrieval questions with exact relevant IDs and hierarchy, and six planner cases. Retrieval has seven calibration queries (five positive, two no-evidence) and eight held-out queries (six positive, two no-evidence). The English pilot is deliberately small: it cannot establish multilingual/long-document quality or statistically robust no-evidence rates.

Generative prompts come from current application services: strict Assistant SYSTEM, captured Q&A prompt with synthetic evidence, Assessment Studio slots/evidence and Document Studio with synthetic approved paragraph-length guidance. Prompt capture patches provider, evidence retrieval and preference access; it never reads SQLite or Chroma. There are six planning, three Q&A, two assessment and two document cases. Structured cases run twice, Q&A once: 23 attempted responses/model. No model gets selective corrective retries. Model identity/digest, options, prompts' SHA-256 fingerprints, fixture version, date, platform, Python and observed metrics are recorded. Temperature 0, seeds 17/18, context 4096, output cap 1536, thinking disabled, non-streaming, 60-second client timeout. These are benchmark-only controls; current production inference options are unchanged.

Examples (from repository root, existing environment):

```sh
.venv-rebuild/bin/python -m benchmarks.runner --model llama3.2:3b --output benchmarks/results/baseline --repeats 2
.venv-rebuild/bin/python -m benchmarks.runner --model qwen3:1.7b --output benchmarks/results/qwen --repeats 2
.venv-rebuild/bin/python -m benchmarks.embedding_runner --model sentence-transformers/all-MiniLM-L6-v2 --output benchmarks/results/minilm
.venv-rebuild/bin/python -m benchmarks.embedding_runner --model BAAI/bge-small-en-v1.5 --output benchmarks/results/bge-small --allow-download
```

Normal tests never run these live commands. Models are not downloaded by generative runner. Embedding/reranker commands default to offline cache access; `--allow-download` is explicit and applies a 15 GiB free-space reserve plus download overhead. Large multilingual BGE-M3 components are intentionally deferred under this 8 GB Mac audit. Candidate model/license/size/source references are in `models.py`. Use actual free disk/memory pressure before every live experiment; estimates are not guarantees. Never delete user assets automatically. CLI output within the repository is restricted to ignored `benchmarks/results/`. Model weights stay in machine-local Ollama/Hugging Face caches outside the repository.

## Scoring and review

Separate metrics cover JSON, plan schema/parameters/actions/dependencies/refusal/clarification, exact assessment counts/distributions/structure/evidence references and document schema/factual metadata. Numeric-token presence and paragraph counts are limited proxies; neither proves semantic factual restraint or professionalism. Q&A lexical term presence is a proxy, not a groundedness score. The no-evidence stress phrase check is a limited proxy that cannot exclude accompanying hallucinations. The stress prompt deliberately probes the model directly; production Q&A instead returns a deterministic abstention without generation. Pipeline tests measure that application gate separately.

Human groundedness, unsupported claims, answer-key correctness, instruction adherence, professionalism and usefulness remain REQUIRES_HUMAN_REVIEW. Generated `human_review.csv` has blank scoring columns and an explicit rubric. No model judge or invented human scores are used. No composite popularity/quality score is hidden behind the raw metrics. Availability/provider errors/timeouts remain attempts in results and do not disappear from success denominators. Median is the mathematical median; Ollama token/duration metadata is recorded when supplied. Non-streaming total response latency is available, first-token latency is not. Python peak RSS excludes the separate Ollama process/device memory. Per-run Ollama residency snapshots are observed estimates, not true peaks. Baseline's observed CLI residency is documented separately.

Pilot promotion gates require at least 20 trials/category, critical deterministic rates >=95%, median latency <=30 seconds, professor factual/quality/privacy review and adequate resource headroom. These are prospective conservative gates, not a claim of statistical certainty; the current pilot deliberately lacks sufficient promotion coverage. A successful syntax/schema result alone cannot justify production replacement.

## Retrieval and reranking

`retrieval.py` implements an in-memory normalized cosine collection injected into the unchanged Build 6 retrieval API. Every query uses its exact known course/semester/subject/unit. Corpus/model encoding is explicit; nothing initializes production Chroma. The first comparison uses 15/5/0.65 for both embeddings. BGE v1.5 uses its model-card query instruction; document vectors are unchanged. Embedding inference is CPU with two PyTorch threads for comparable local latency and conservative memory use.

Hit@1/3/5, Recall@5, MRR and no-evidence false-positive rate are separate. Positive-query metrics exclude no-evidence cases; false positives use all negative queries. Hierarchy correctness checks every returned record's metadata. Threshold calibration searches a documented cutoff grid on calibration data only, maximizing balanced relevant hit/no-evidence rejection and preferring lower cutoff on ties. Held-out questions never select the threshold. A threshold is model-specific and is never written to production configuration.

Reranker support compares the same embedding candidate pool (up to 15), embedding threshold and final 5, then orders by cross-encoder score. It does not incorrectly treat a raw cross-encoder score as a calibrated probability/distance. If disk/RAM cannot support a live reranker, report it as skipped, not as an improvement. Query embeddings are cached within one synthetic evaluation: first-pass latency includes encoding; later cutoff/reranker measurements disclose cache reuse. Do not compare those timings as cold-start equivalents. Load/corpus-encode timings are separate.

`pipeline.py` exercises the actual Q&A service with the synthetic store, an explicit benchmark-only model override and two positive/one no-evidence held-out questions. Pipeline outputs retain sources and measured model calls. They are pilot observations, not evidence for automatic production routing.

## Results and reproduction

Each generative run produces ignored JSON, metric CSV, Markdown summary and blank human-review CSV. Retrieval produces ignored JSON with raw rankings/distances, cutoff curve and held-out metrics. Progress files preserve finished attempts during a failed process. Run outputs may contain hallucinated names/text even though inputs are synthetic; review before sharing. Do not commit large or unreviewed generated responses.

The versioned selection report contains only aggregate results, resource decisions and limitations. Framework tests mock generation/embeddings/rerankers and use temporary output; the complete existing runtime sentinel checks production byte-for-byte safety. Build 14 should be driven by measured gates and human review, not model popularity. No fallback/routing, default model change, embedding replacement or reindex is implemented here.
