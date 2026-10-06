# Build 14 final report — resource-safe continuation

**Decision F: more human review required before any production change. Keep the current production stack.**

Completed on 4 October 2026. Build 13 checkpoint: `7e1921372541de0c84294f9c11c10c96869c90ce`, branch `eduagent-rebuild`. Existing changes and completed measurements were preserved. No staging, commit or push.

## Resource safety and evidence coverage

The interrupted batch preserved **145 completed responses**, all from llama3.2:3b. One later in-flight response was interrupted and has no result; it is not scored as a completed success/failure. No additional live generation calls were made in this continuation, no models were downloaded, embeddings were not rerun and no reranker was loaded. Initial/final Ollama residency checks were empty.

The original planned matrix was 344 calls. Prompt-only Llama completed 30 planner, 20 assessment, 20 document and 16 Q&A cases; constrained Llama completed 30 planner, 20 assessment and 9 document cases. Remaining cases, Qwen V2, strict-contract pilot and supplementary live scenarios are **NOT RERUN FOR RESOURCE SAFETY**. Their unit tests/fixtures exist; they have no live quality result. Build 13 Qwen measurements remain historical V1 evidence, not V2 observations.

Observed during the earlier run: 8 GiB fanless M2-class Mac, approximately 2.5 GB Llama residency at context 4096 / 100% GPU, memory-free percentage 21%, swap approximately 5.5 GB. The owner stopped sustained inference for excessive thermal/memory/swap pressure. Thermal sensors were not measured. Regression and retrieval work overlapped parts of that earlier batch; timings are resource-constrained observations, not clean laboratory speed rankings.

## Structured output architecture

Production defaults and validators are unchanged. Only the measured-provider API accepts opt-in response_format schemas. Ordinary generate_chat calls do not request a schema. There are no repair retries, automatic routing, default-model changes, reindex or production retrieval changes.

Envelope-schema inference was actually tested. A stricter generic schema additionally encodes per-slot assessment fields/ABCD options, document metadata and closed planner parameter shapes. This stricter mode has mock/schema tests only; its Ollama support/quality is unverified and it must not be promoted based on envelope results. Bounded single-object extraction accepts only exact JSON, a JSON fence or one fixed harmless prefix; it is not enabled in production and does not bypass validation.

## Reliability and latency

| Mode | Task | Attempts | JSON valid | Schema valid | Exact plan / usable body facts | Median s | P95 s |
|---|---|---:|---:|---:|---:|---:|---:|
| prompt_only | assessment | 20 | 1/20 | 0/20 | 0/20 | 24.880 | 39.185 |
| prompt_only | document | 20 | 0/20 | 0/20 | 0/20 | 9.206 | 10.634 |
| prompt_only | planner | 30 | 28/30 | 3/30 | 3/30 | 2.679 | 10.238 |
| prompt_only | qa | 16 | N/A | N/A | Human review pending | 1.879 | N/A (<20 samples) |
| schema_constrained | assessment | 20 | 20/20 | 4/20 | 4/20 | 24.631 | 31.925 |
| schema_constrained | document | 9 | 9/9 | 7/9 | 0/9 | 9.643 | N/A (<20 samples) |
| schema_constrained | planner | 30 | 30/30 | 22/30 | 11/30 | 7.788 | 22.234 |

Planner: actions/parameters 3/30 in prompt-only versus 15/30 constrained; clarification 3/30 versus 13/30; valid service parameters 3/30 versus 13/30; refusal correctness 3/7 versus 4/7. One synthetic privacy-refusal case passed in both modes (1/1), insufficient to establish broad privacy safety. Existing deterministic student-filter and identity-preflight tests also pass without provider calls.

Assessment: prompt-only JSON 1/20 and contract 0/20; constrained JSON/counts/type/difficulty/Bloom/evidence-reference checks 20/20 but contract only 4/20. MCQ structure passed 8/13 applicable constrained cases; correct-answer structure 7/20. Descriptive-only cases are not counted as failed MCQ cases. Semantic answer correctness, difficulty appropriateness and usefulness require review.

## Document facts are separate from schema

Prompt-only prose was not usable structured JSON (0/20), but raw text retained exact dates/references/named entities in 20/20, numeric tokens in 15/20, with no detected new numeric tokens. This does not make the prose a valid DocumentDraft.

Constrained documents: JSON 9/9, product schema 7/9; required body numeric/date/reference checks 1/9 each, named entities 0/9, complete usable body facts 0/9. No unsupported numeric tokens were detected; omissions still make these outputs unsafe to promote. Paragraph-count proxy 5/9, or 3/9 when also requiring a valid draft. Non-numeric inventions and semantic date/name equivalence require human review.

## Deterministic failure distributions

Counts are multi-label and may exceed failed-output counts. Typed-plan schema and service/expected-plan correctness are separate. Fact tags are based on independently missing controlled facts, not JSON failure alone.

- prompt_only / assessment: extra_forbidden_fields=1, invalid_json=19, missing_required_fields=1, wrong_schema=1

- prompt_only / document: factual_preservation_violation=5, invalid_json=20

- prompt_only / planner: invalid_json=2, policy_refusal_failure=4, wrong_schema=25, wrong_type=25

- prompt_only / qa: No deterministic failure labels; semantic review pending.

- schema_constrained / assessment: duplicate_question=3, invalid_answer_key=13, invalid_mcq_structure=5, wrong_schema=16

- schema_constrained / document: factual_preservation_violation=9, wrong_schema=2

- schema_constrained / planner: clarification_failure=9, invalid_dependency=10, invalid_planner_parameters=10, policy_refusal_failure=3, wrong_action_selection=6, wrong_enum=3, wrong_schema=17, wrong_type=6

## Q&A

16 prompt-only responses: expected-term proxy 14/14, no-evidence phrase proxy 2/2. The latter are direct model stress probes; production Q&A instead deterministically avoids generation when retrieval is empty. These lexical proxies do not establish groundedness, citations, scope adherence or absence of unsupported claims. Supplementary synthesis/partial-evidence cases exist but were not run live.

## Final corrected retrieval artifacts

Only `build14-minilm-final/retrieval.json` and `build14-bge-final/retrieval.json` are used. Earlier pre-correction artifacts remain preserved but are superseded. Corpus: 60 chunks, 48 query IDs; 24 calibration and 24 held-out, each 21 positive / 3 no-evidence. Positive question text does not overlap between splits; held-out paraphrases share topics and several no-evidence prompts share wording. Most exact-unit searches have only five eligible chunks, making Recall@5 easier than in a large real collection.

| Embedding | Calibrated cutoff | Held-out Hit@1 | Hit@3 / Hit@5 / Recall@5 | MRR | No-evidence FP | Hierarchy |
|---|---:|---:|---:|---:|---:|---:|
| MiniLM | 0.75 | 17/21 | 21/21 | 0.897 | 0/3 | 100% |
| BGE-small | 0.45 | 16/21 | 21/21 | 0.865 | 0/3 | 100% |

Initial comparisons used production 15/5/0.65 before calibration. At .65, BGE-small accepted all six no-evidence queries; MiniLM accepted none. Calibration used no held-out outcomes. Cutoffs .75 / .45 differ from V1 .60 / .35: the small datasets do not justify a production threshold change. Three held-out negatives give weak confidence in false-positive safety.

## Production gates and decision

Planner requires >=95% schema validity, >=90% exact-plan success, 100% refusal/privacy correctness and human review. Observed constrained results 22/30, 11/30 and 4/7 fail. Assessments require >=95% contract validity; documents require >=95% schema and body-fact preservation plus review. No tested V2 result qualifies.

Retrieval switching requires meaningful held-out ranking improvement, no material recall loss, <=5% no-evidence false positives and broader negative coverage. BGE-small had lower held-out Hit@1 (16/21 versus 17/21), so no switch is justified. A reranker was not retested because this continuation explicitly prohibits loading it; preserve V1 no-measured-gain conclusion.

Keep llama3.2:3b, all-MiniLM-L6-v2, 15 candidates / 5 final / .65, no reranker/router. Do not implement Build 15 migration. First review preserved outputs and improve bounded contract reliability; any further inference needs a separately approved resource-safe plan. Future NIT/GPU models/retrieval components are untested evaluation targets, not approved winners.

## Human review and preservation

Ignored `benchmarks/results/build14-final/human_review.csv` contains 145 rows with prompt summaries, expected contracts/facts and raw-output references. Subjective scoring fields are blank and status is PENDING HUMAN REVIEW. Corresponding results.json retains original metrics and raw responses alongside derived corrected metrics, including SHA-256 of original progress. No original progress or V1 result was overwritten.

Offline corrections: missing student dataset correctly requires clarification; exact-plan success includes service-parameter validity; MCQ metrics exclude descriptive-only cases; fact checks distinguish usable structured body from raw-text fallback. No model output, latency or student record was repaired.

## Limitations

One run per scenario/mode; incomplete second pass; no Qwen V2 or strict-contract live data; pending subjective review; resource/thermal confounding; templated synthetic English retrieval and only three held-out negatives. Supplemental cases are implemented/tested only. Valid JSON is not semantic correctness. Production changes remain unapproved.
