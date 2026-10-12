# Build 13 AI stack selection: measured pilot, no production upgrade

## Decision

**D — insufficient evidence; keep the current stack and expand benchmark coverage.**
Production remains llama3.2:3b, all-MiniLM-L6-v2, candidate K=15, final K=5,
maximum cosine distance=0.65, without reranking or task routing.

## Reproducibility and resources

Executed 4 October 2026 on ARM64 Mac14,2, macOS 27.0.1, 8 GiB RAM,
Python 3.12.6 and Ollama 0.34.1. MPS was available; baseline Ollama residency
was observed at approximately 2.5 GB / 100% GPU / context 4096. Observed
residency is not a peak-memory measurement. Python peak RSS excludes Ollama.
Memory pressure and swap changed across the paused/resumed run; timings are
pilot observations rather than controlled laboratory comparisons.

Disk gates retained a 15 GiB reserve and estimated download overhead. Models
were evaluated sequentially. BGE-M3 and BGE-reranker-v2-m3 were deferred for
this 8 GiB machine. No user assets/models were deleted. A stalled BGE-small
HF-Xet transfer was interrupted, then completed through documented per-process
HTTP fallback; no generation results were selectively retried.

Fixtures contain 18 newly authored chunks and 15 retrieval queries. Current
application prompts were captured with synthetic evidence/preferences only.
There were six planner, three Q&A, two assessment and two document cases.
Structured cases ran twice; Q&A once: 23 calls per model, 69 component calls,
plus six actual Q&A pipeline calls. Temperature 0, seeds 17/18, context 4096,
output cap 1536, thinking disabled, timeout 60 seconds. Production settings
were not changed. Raw outputs, prompt fingerprints, model metadata, timings
and blank human-review sheets remain in ignored benchmarks/results/.

## Generative results

| Model | Planner JSON | Valid plans | Valid assessments | Document JSON | Valid documents |
|---|---:|---:|---:|---:|---:|
| llama3.2:3b | 10/12 | 4/12 | 4/4 | 0/4 | 0/4 |
| qwen3:1.7b | 8/12 | 0/12 | 0/4 | 4/4 | 2/4 |
| qwen3.5:0.8b | 12/12 | 0/12 | 0/4 | 4/4 | 4/4 |

There were zero provider failures/timeouts, but **46 of 60 structured outputs
were invalid**. Transport success does not imply a valid application result.
Baseline refusal/privacy cases passed the strict contract; neither Qwen
candidate produced valid refusal plans. No real student records were supplied.
Baseline assessments passed exact counts, difficulty/Bloom distributions, MCQ
structure, key structure and evidence-reference checks in this small pilot.
Answer correctness and groundedness still require human review.

Qwen3.5 produced valid document structures and metadata in 4/4 trials, but
required numeric facts were present in the body in only 2/4. Metadata validity
alone cannot establish factual preservation. All models met the limited Q&A
lexical checks (2/2) and no-evidence phrase proxy (1/1); these do not establish
semantic groundedness or exclude additional unsupported claims.

| Model | Planner median s | Q&A median s | Assessment median s | Document median s |
|---|---:|---:|---:|---:|
| llama3.2:3b | 4.354 | 1.496 | 33.182 | 9.415 |
| qwen3:1.7b | 2.870 | 1.865 | 45.911 | 13.234 |
| qwen3.5:0.8b | 1.769 | 1.421 | 7.819 | 2.526 |

Non-streaming completion latency was measured; first-token latency was not.
Load/token metadata is retained when provided. No corrective generation retries.

## Retrieval and reranker

The same synthetic corpus and known hierarchy filters were injected into the
existing retrieval API through an in-memory cosine store. CPU, two threads.
First comparisons used unchanged 15/5/0.65 settings for both embeddings.

| Embedding | Hit@1 | Hit@3 | Hit@5 | Recall@5 | MRR | No-evidence false positives | Scope correct |
|---|---:|---:|---:|---:|---:|---:|---:|
| MiniLM | 9/11 | 11/11 | 11/11 | 1.000 | 0.909 | 0/4 | 100% |
| BGE-small-en-v1.5 | 10/11 | 11/11 | 11/11 | 1.000 | 0.955 | 4/4 | 100% |

Distance thresholds do not transfer between embedding families. Calibration
used only five positive/two negative questions; held-out data comprised six
positive/two negative questions. Selected cutoffs: MiniLM 0.60, BGE-small 0.35.
Both achieved held-out Hit@1/3/5, Recall@5, MRR=1 and false positives=0/2.
These tiny samples do not justify changing production embeddings or threshold.
First-pass median query times were approximately 8.8 ms / 14.3 ms respectively.
Peak Python RSS was approximately 492 MB / 442 MB.

BGE-reranker-base added **no held-out quality gain** over calibrated BGE-small:
both already scored perfectly on six positive/two negative cases. Reranked
positive-query median was approximately 68 ms, with first cold query 1.06 s;
process peak RSS approximately 838 MB. Query embeddings were cached during
cutoff/reranking comparisons. No production reranker is recommended.

## Actual Q&A pipelines

Each stack ran two positive held-out questions and one no-evidence question
through the current Q&A service. Calls were [1,1,0] in all three stacks: the
application abstention gate correctly avoided model generation without evidence.
Sources remained scoped. Semantic quality requires human review.

| Stack | Positive question 1 s | Positive question 2 s | No evidence s |
|---|---:|---:|---:|
| llama3.2:3b + MiniLM .65 | 5.542 | 0.662 | 0.020 |
| qwen3.5:0.8b + MiniLM .65 | 3.616 | 3.336 | 0.019 |
| qwen3.5:0.8b + BGE-small .35 | 0.914 | 3.230 | 0.029 |

Later Qwen runs benefited from warm residency; these are not comparable cold
start speed rankings. No reranked pipeline was warranted by component evidence.

## Selection and next phase

| Role | Evidence-based recommendation |
|---|---|
| Current baseline | Keep llama3.2:3b + MiniLM, no reranker |
| Local speed | Qwen3.5:0.8b fastest observed component medians, not approved |
| Local overall quality | NO CHANGE RECOMMENDED YET |
| Planner | Baseline best observed valid rate, but 4/12 is inadequate |
| Grounded Q&A | No semantic winner established; human review needed |
| Assessment | Baseline best observed contract results; only four trials |
| Documents | Qwen3.5 promising structure/speed; body facts insufficient |
| Embeddings | Keep MiniLM; BGE-small requires its own threshold |
| Reranker | Do not activate; no demonstrated quality gain |

Build 14 should first expand adversarial/multilingual/long-context/no-evidence
coverage and conduct professor review. Prospective promotion gates require at
least 20 trials/category, >=95% critical deterministic success, median <=30 s,
human factual/privacy approval and resource headroom. No tested model meets all
of these gates. Keep all production task assignments on llama3.2:3b for now.
Task-specific routing is an evaluation hypothesis, not an approved architecture.
A future fallback must use an explicitly tested alternative, validate its output,
and otherwise return a controlled error; no fallback was implemented here.

For future NIT/GPU hardware, evaluate Qwen3.5:4b/9b with BGE-M3 and optionally
BGE-reranker-v2-m3. These are **untested targets**, not a proven winning stack.

New machine-local downloads: Qwen3:1.7b (~1.4 GB), Qwen3.5:0.8b (~1.0 GB),
BGE-small (~134 MB), BGE-reranker-base (~1.1 GB). Keep the 0.8b candidate and
BGE-small for further study; 1.7b and reranker are optional cleanup candidates
only after the owner decides. Nothing is automatically removed.

Sources: [Qwen3 1.7b](https://ollama.com/library/qwen3:1.7b),
[Qwen3.5 0.8b](https://ollama.com/library/qwen3.5:0.8b),
[BGE-small](https://huggingface.co/BAAI/bge-small-en-v1.5),
[BGE-reranker](https://huggingface.co/BAAI/bge-reranker-base),
[BGE-M3](https://huggingface.co/BAAI/bge-m3),
[HF transport configuration](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).
