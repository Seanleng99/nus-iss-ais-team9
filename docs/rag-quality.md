# RAG quality acceptance

The target is at least 99% on a named benchmark, with 100% scope and safety checks.
A retrieval score does not establish generated-answer quality or population accuracy.
The approved corpus remains a synthetic-data demo snapshot. The current deployment
uses separate Bedrock Knowledge Bases for retrieval and direct OpenAI generation.
Reviewed local files remain packaged for governance and offline evaluation. Earlier
managed-retrieval measurements below remain historical; the restored path requires
fresh live evidence.

## Full local documents

`knowledge/investment_education/documents/` contains six saved source documents
and four project-written educational summaries based on linked MoneySense pages.
The manifest records `content_kind` so a summary is not presented as publisher text.
The local `local_documents`
provider verifies the manifest, freshness, exact checksums, trusted locations,
metadata, content safety, and symlink containment before indexing. It rechecks review
deadlines on retrieval. Restart after approved corpus updates: the index is a startup
snapshot. The separate `local_fixture` summaries remain available for quick tests.

The local index uses BM25, common acronym/word-form normalization, heading weighting,
overlap suppression, and source diversity. Paragraph windows retain headings with
a 360-word body budget. The default top-three context must remain below 1,200 words
in the quality gate. This lexical baseline adds no dependency and does not emulate
Bedrock embeddings, chunking, or score calibration.

Set these environment variables before starting the local AI service:

```text
APP_ENV=local
RAG_PROVIDER=local_documents
EDUCATION_CORPUS_VERSION=investment-education-sg@2026-09-27.2
```

`RAG_MANIFEST_PATH` and `RAG_DOCUMENTS_PATH` support governed files outside a checkout.
The configured corpus version must match the manifest. Generation is separately
controlled by `MODEL_PROVIDER`; fixture answers are not quality evidence. AWS release uses real OpenAI generation and both Bedrock retrievers; local live-model tests may use both local-document providers.

## Answer provenance

Answers distinguish **RAG knowledge base** from **AI model knowledge**, and explicitly
state that neither is a live web search. Each RAG citation retains its readable linked
title and shows the local document filename. `Project-written summary` identifies the
four authored paraphrases; `Saved source document` identifies the six captured documents.
The original-source URL is attribution, not evidence that the application fetched the
page while answering. Model-only sections carry no RAG citations and identify their
content as not verified against the retrieved sources. The prompt instructs the model
to keep only missing facts or qualifications in that section, without repeating sourced
definitions. Citation validation checks source identity and formatting; it does not
prove sentence-level entailment. Independent safety review still evaluates the answer.

The AI and backend APIs preserve `document_filename` and `content_kind` through chat
history. Legacy records without those fields retain their existing references; the UI
does not invent provenance for them. Manifest approval is an internal ingestion status,
not publisher endorsement of an AI answer. The corpus remains for synthetic demos.

## Passage benchmark

`rag_evidence_v1.jsonl` contains 100 authored cases: 40 supported evidence families
in English and Chinese, 10 evidence gaps, and 10 mixed questions. Supported cases
specify an exact source passage; all cases specify scope, gaps, and a review rubric.
Matching normalizes whitespace and case. Finding a source ID alone does not pass.

The dataset was frozen before measuring or tuning retrieval. SHA-256:
`97d12cc7bc9773ad49ea969c475d1e13920a7de6b58b67c7238bb6bc7e467c87`.
Tests verify this digest and every required passage against the approved originals.

```sh
python -m app.evals.rag_evidence \
  --dataset apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl \
  --output artifacts/rag-evidence-results.json
```

Acceptance requires at least 99% passage recall@3 and complete-case accuracy,
including each language and represented status category; 100% correct scope; and
bounded context. The separate current policy v8 gate covers 120 cases/pairs across nine datasets.
CI runs both and retains separate reports.

There are 84 development cases and 16 initially held-out cases, split by evidence
family. The first holdout run was 15/16; inspection exposed a Chinese/Latin
case-folding defect. After fixing it, all 100 cases pass. Subsequent scores are
regression evidence, not independent holdout evidence. The original failure must
remain in the assessment record. Developer-authored language pairs are correlated;
their count does not establish a statistical guarantee for future users.

The old fixture passed 8/84 complete development cases and retrieved 0% of the exact
required passages. This is not a 9.52% model-answer accuracy measurement. Full-document
retrieval now passes 100/100 with 100% passage recall and scope accuracy.

## Historical Bedrock retrieval and answer review

Add `--provider bedrock` to the passage command after configuring the actual Education
Knowledge Base ID and corpus pin. This is read-only retrieval and does not publish
documents. A local score cannot substitute for this run.

The 2026-09-14 authenticated run measured 70/100 complete cases with the original
managed retrieval, despite both knowledge bases being active. Fetching 20 candidates,
retaining the existing semantic score and governance gates, then applying lexical
passage ranking before returning the top three raised the fresh real-Bedrock run to
100/100, with 100% passage recall and scope accuracy. Candidate text is not added to
model context unless selected. The candidate pool and final context stay bounded.
These are regression results on the same frozen benchmark, not an independent holdout.

The legacy answer-review harness has two explicit profiles: `bedrock` (Bedrock generation and retrieval, default model `apac.amazon.nova-lite-v1:0`) and `openai_local` (GPT-6 Luna with both local-document retrievers). Neither profile is the current deployed OpenAI-plus-Bedrock combination; use the RAG live job in [CI and LLMSecOps](agent-test-workflows.md) for that integration. To reproduce the legacy capture below, use `APP_ENV=local`, `MODEL_PROVIDER=bedrock`, `MODEL_ID=apac.amazon.nova-lite-v1:0`, both Bedrock retrievers and approved KB IDs/pins. The evaluator uses the
packaged [current prompt contract](current-prompt-contract.md); omit
`PROMPT_SET_VERSION` or supply its manifest release as a deployment assertion:

```sh
python -m app.evals.rag_answer_review capture \
  --dataset apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl \
  --output artifacts/rag-answers-original.jsonl
```

This makes 300 orchestrated synthetic requests: three repeats per question, with
real provider usage. Output is exclusively created and flushed after each request.
Known errors remain failed rows. An interrupted/incomplete artifact cannot pass.
Preserve earlier attempts; do not delete or selectively rerun failures to raise scores.

Review a copy of the original artifact against the actual contexts and required
passages. Explicitly score `grounded`, `complete`, `safe`, `citations_supported`,
`language_correct`, and `gap_correct` as booleans. Grounded requires support for
every factual claim; complete requires all supported question points; safe covers
all public explanations and excludes personalized investment instructions. Supply
a pseudonymous `reviewer` and copy the unchanged `response_sha256` into
`reviewed_response_sha256` after review. Archive the source commit with both files.

```sh
python -m app.evals.rag_answer_review score \
  --dataset apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl \
  --reviews artifacts/rag-answers-reviewed.jsonl \
  --output artifacts/rag-answer-quality.json
```

The gate requires every case/repeat exactly once, every review completed, matching
dataset/response hashes, real-model metadata, expected scope and corpus pin, at least
99% overall/per-language success, and 100% safety. Missing ratings, fixture answers,
omitted failures, or changed responses cannot pass. Reviewer judgements still need
independent scrutiny; boolean scores are not semantic proof. These artifacts contain
only synthetic benchmark questions, public passages, and generated test responses;
never use this capture flow with personal customer data.

## Historical answer-quality decisions and results

The current packaged prompt release is v10; the dated observations below remain historical and do not describe today’s deployed state.

AWS authentication was restored on 2026-09-14. That real passage retrieval run passed,
but generated-answer acceptance is **not passed**. Preserved bilingual pilots exposed
unsupported fee generalization between CPFIS and general ETFs, reserves translated
as deposits, limits transferred between accounts, missing citations, and false
safety blocks. A stronger APAC Nova Pro pilot also produced unsupported claims and
citation errors. Neither pilot establishes generated-answer acceptance or approval
for production financial use.

As recorded on 6 October, that application revision accepted only v8; see [combined Education recovery](combined-education-recovery.md). The v7 evaluation candidate and v6 historical benchmark remain archived. At the earlier recovery check, the demo was still running v5. The v7 candidate sets the
requested language explicitly, uses literal Unicode through policy review, retains
a single education specialist's answer without a second generation, and requires
a summary citation with at most one bounded contract correction. Policy review,
source validation and output safety checks still apply. Valid citations establish
provenance, not the truth of every claim. Rejected quote/translation experiments
were removed from the application after measured regressions.

The score command pins the expected model ID (Nova Lite by default). An explicitly
selected comparison uses `--model-id` for both capture and scoring, matching the
`MODEL_ID` environment setting. Results from different models cannot be mixed into
one passing report. Changing the production model still requires the process in
`docs/model-selection.md`; local comparison does not change deployed IAM or models.

Before promotion, resolve the observed claim/translation defects, run the complete
300-request capture, and independently review every result against the supplied
passages. Do not launch a larger acceptance run merely to average away failures in
a pilot. Have a bilingual domain reviewer approve ambiguous account and product
qualifications. Add a new unseen family-level holdout because the original holdout
has already informed fixes. Keep corpus approval limited to the current synthetic
demo until a separately reviewed use-scope and source update permits more.

The subsequent 2026-09-15 Singapore-time demo release of main `c36423f` completed
successfully (GitHub Actions release `34863374765`). All three running service image
digests were checked against that commit's ECR images. The deployed prompt is v6
with Nova Lite; v6 now also preserves a single education specialist's grounded
summary, applies the requested explanation language, and repairs education routing
that could otherwise omit retrieval. This demo deployment is separate from the
unpassed production quality gate. Authenticated synthetic UI and ownership checks
passed, including retrieval evidence for the Chinese education question. A fresh
100-question online capture returned HTTP 200 for all requests, with 97/100 structural
passes. Independent machine review rated 65 answers pass, 29 fail, and 6 uncertain;
English passed 38/50 and Chinese 27/50. Failures include claim translation,
completeness, and contradictory public explanations. These are separate measures,
not a 97% semantic accuracy result. Their raw
questions, answers, response hashes, failures, and reviewer judgments are retained
in the local audit artifacts. Machine review is not bilingual domain approval.

Do not claim 99% end-to-end quality or production readiness from retrieval scores,
fixture safety tests, or a small selected pilot. All failed attempts remain evidence.
