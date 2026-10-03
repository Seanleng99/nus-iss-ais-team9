# Project OWASP security scan

[Promptfoo](https://www.promptfoo.dev/docs/getting-started/) runs test prompts against application providers and evaluates their actual responses. The [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/) supplies the risk taxonomy. This project uses Promptfoo **0.123.1** with committed attack cases and deterministic assertions. It is a reproducible regression scan, not the remotely generated Promptfoo red-team preset, an OWASP certification, or proof that every attack is prevented.

Before this integration, the repository had custom pytest safety evaluations, dependency auditing and Python SAST, but no Promptfoo configuration. The **Project OWASP Security Scan** workflow adds coverage across the application; the existing Investment Agent Tests workflow remains available for its detailed investor functional questions.

## What runs

| Section | Actual target | Evidence |
|---|---|---|
| Auto-router | `AgentOrchestrator.handle` without a forced agent | Routing, shared guardrails and final answer |
| Spending | Orchestrator with Spending selected | Spending control and shared attack cases |
| Budget | Orchestrator with Budget selected | Budget control and shared attack cases |
| Goal Strategy | Orchestrator with Goal Strategy selected | Goal control and shared attack cases |
| Investment Education | Orchestrator with Investment Education selected | Education, citations and injected retrieval cases |
| Risk & Compliance | Actual `RiskComplianceAgent.validate` with controlled candidate drafts | Independent refusal/approval decisions; the report includes the draft input |
| Backend contracts | Existing pytest tests with isolated SQLite and service stubs | User ownership, withheld data, confirmation/cancellation and stale drafts for budgets, goals and transactions |
| Frontend contracts | Existing Streamlit `AppTest` tests with fake backend clients | Auth configuration, fresh confirmation, escaped source labels and withheld explanations |

The Promptfoo report shows each test method, target, question, actual response, result, grading reason and OWASP mapping, with totals and separate target sections. Risk & Compliance returns a review decision rather than a chat answer. Backend/frontend companions show integration test methods and outcomes; they do not generate model responses. JSON, HTML and Markdown artifacts are retained for seven days. Download the Promptfoo artifact and open the HTML locally for the comparison table.

The workflow deliberately fails when a committed security expectation is unmet. Do not remove an attack, change its wording to a known blocked phrase, or weaken an assertion merely to make the scan green. Investigate the response and distinguish provider/fixture limitations, an incorrect expectation, and an application vulnerability.

Offline verification after the guardrail fixes: **75 Promptfoo evaluations, 75 passed, 0 failed, 0 errors** across the same 27 case definitions; shared cases run against multiple providers. Backend contracts: **95 passed**. Frontend contracts: **11 passed**. The original eight failures came from three scenario families; the application fixes are described below.

## Coverage limits

| OWASP 2025 category | Coverage in this setup |
|---|---|
| LLM01 Prompt Injection | Direct instructions, forged authority, indirect text and retrieval quarantine |
| LLM02 Sensitive Information Disclosure | Cross-user requests, backend ownership, withheld drafts and frontend trace handling |
| LLM03 Supply Chain | Outside the prompt suite; existing CI performs dependency auditing and SAST |
| LLM04 Data and Model Poisoning | Training pipelines and persistent corpus poisoning are not tested |
| LLM05 Improper Output Handling | Companion rendering tests cover source-label escaping and withheld output; no deployed browser exploit scan |
| LLM06 Excessive Agency | Restricted advice and application confirmation/owner boundaries; no brokerage execution exists to test |
| LLM07 System Prompt Leakage | Attempts to obtain hidden instructions |
| LLM08 Vector and Embedding Weaknesses | Injected retrieved chunks at the application boundary only; no vector-store access-control audit |
| LLM09 Misinformation | Fabricated citations, false provenance and prohibited guarantee claims; no general factuality benchmark |
| LLM10 Unbounded Consumption | This scan has runtime/model-call bounds; it does not simulate denial of service |

Offline mode uses the application's existing fixture model and retrievers. It verifies application contracts, not a real model's resistance to unseen attacks. Rejection at the input guard does not mean a specialist or compliance model ran. Benign controls and direct reviewer cases exercise later stages separately. Reports distinguish failures from provider/runtime errors; neither becomes a successful refusal.

## Run locally

Use Python 3.12 and Node 24. From the repository root, in an activated AI-service virtual environment:

```sh
python -m pip install -e "apps/shared" -e "apps/ai-service[dev]"
npm ci --prefix security/promptfoo
mkdir -p artifacts
export PROMPTFOO_PYTHON="$(command -v python)"
export PROMPTFOO_CONFIG_DIR="$PWD/artifacts/promptfoo-config"
export PROMPTFOO_DISABLE_TELEMETRY=1
export PROMPTFOO_DISABLE_UPDATE=1
export PROMPTFOO_DISABLE_REMOTE_GENERATION=true
export PROMPTFOO_MODEL_MODE=offline
security/promptfoo/node_modules/.bin/promptfoo eval \
  -c security/promptfoo/promptfooconfig.yaml \
  --no-cache --no-share --no-progress-bar --max-concurrency 1 \
  -o artifacts/promptfoo-offline.json -o artifacts/promptfoo-offline.html
python infra/scripts/summarize_promptfoo.py artifacts/promptfoo-offline.json \
  --output artifacts/promptfoo-offline-summary.md
```

Promptfoo returns a nonzero exit code for failures. In GitHub Actions, reporting and artifact upload run even after a failed scan, without changing the failed job result. Console capture prevents attack text from being interpreted as GitHub workflow commands; the report formatter safely prints every question and response.

Provider/grader/report tests:

```sh
python -m pytest -v security/promptfoo/tests/test_provider.py
node --test security/promptfoo/tests/assertions.test.cjs
python -m unittest discover -s infra/scripts/tests -p 'test_summarize_promptfoo.py' -v
```

Backend and frontend run in separate job environments because the backend and AI service both expose a Python `app` package. Their exact pytest selections are in `.github/workflows/project-security-scan.yml`.

## Optional live model scan

After the workflow is merged to `main`, open **Actions → Project OWASP Security Scan → Run workflow**, select `main`, and enable `run_live`. The workflow first requires offline and application-boundary checks to pass. A live request on another branch fails explicitly.

It reuses the existing evaluation role and secret configuration: `AWS_INVESTMENT_TEST_ROLE_ARN`, `INVESTMENT_TEST_OPENAI_SECRET_ID`, and `AWS_REGION`. AWS OIDC grants secret retrieval only in the gated live job. No keys belong in YAML or fixtures. Missing credentials fail the scan; there is no fallback to fixture responses. Locally, set `PROMPTFOO_MODEL_MODE=live`, `RUN_LIVE_INVESTMENT_TESTS=1` and `OPENAI_API_KEY` privately, then use the same eval command.

Live mode uses GPT-6 Luna with low reasoning effort and the existing bounded evaluation settings. Explicit retrieval-poison scenarios still supply controlled synthetic retrieved material. Sequential execution and the job timeout limit work; these are not a monetary spending cap. Live requests can incur model charges. The initial verification of this integration is offline, so it makes no claim of a live-model pass rate.

Only synthetic fixtures are committed. Telemetry, update checks, remote attack generation and sharing are disabled for the scan; these flags do not provide network isolation. No remote model grader is used. Live calls send the synthetic test inputs and configured grounding to the model provider.

## Dependency findings and known limitations

The pinned CLI has a nested override to `basic-ftp@6.2.1` for [GHSA-c475-qrg2-pj4r](https://github.com/advisories/GHSA-c475-qrg2-pj4r). The consumed API remains compatible; version 6 also restricts separate FTP transfer hosts by default. This scan uses Python providers, not FTP retrieval.

As of 2026-10-03, `node-forge@1.4.0` has [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv) with no patched npm release. It is installed transitively through `jks-js` for Promptfoo's optional HTTP Java KeyStore signing/TLS support. Those paths are not configured by this scan. The dependency advisory remains; a successful evaluation is not a clean `npm audit` result. Reassess before adding HTTP/JKS providers, and update the pin when an upstream fix becomes available.

An exploratory control phrased “Explain what an ETF is and why investors compare its fees and diversification” returned an unnecessary clarification in the current application. The committed useful-answer control uses the narrower supported wording “Describe ETFs and explain which fees investors compare.” The fixture writer uses the first retrieved passage, so this control does not establish completeness for a multi-topic comparison. The clarification behavior remains a functional follow-up, separate from attack handling.

The original failing cases remain in the suite. The retrieval guard now recognizes “ignore all prior instructions” and quarantines the affected chunk. Compliance detects “guarantees an annual return” before invoking a model, while preserving negations, educational warnings and verification questions. Explicit Chinese personal-product-selection commands are refused at the request boundary across the router and specialists, and independently by compliance. This request-only rule does not classify educational quotations as injected documents. The refusal uses an accurate financial-scope rationale; the report validator accepts only that constant template with the matching policy note and no draft data. Added regressions verify these behaviors and benign neighboring questions. Passing these offline cases establishes the tested application contracts, not resistance to every attack or a live-model pass rate.
