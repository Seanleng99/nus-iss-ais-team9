# Risk & Compliance Agent Tests

All model-assisted blocking decisions require `block_categories` and a brief policy explanation, including ordinary Budget/Goal reviews. One bounded correction is allowed for an invalid verdict; exhausted correction withholds the draft as `review_contract_unverified`. Tests distinguish this failure from a valid `model_review` block, preserve fixed categories in privacy-safe traces and verify that optional Education gaps do not invalidate qualified Budget/Goal arithmetic. Saved-budget read tests provide the actual scoped record evidence to Compliance and reject mutation fields in read commands.

The **Risk & Compliance Agent Tests** workflow
(`.github/workflows/risk-compliance-agent-tests.yml`) checks the compliance
agent offline. CI and LLMSecOps calls it for AI checks and every selected
application release; manual runs remain available. It never calls a paid model
and uses no secrets. See [all agent workflows and release integration](agent-test-workflows.md)
for triggers, test-file mappings and the required release gate.

| Job | What it shows | Tests |
| --- | --- | --- |
| Offline compliance safety tests | Rule-level checks of the agent and request guardrails | `tests/test_risk_compliance.py`, `tests/test_guardrails.py` |
| Functional — Blocks unsafe requests | Regulated advice and cross-user requests are refused without a model review; prompt injection is stopped at the boundary with no model call | `test_blocks_unsafe_request_*` |
| Functional — Withholds unsafe answers | Unsafe drafts, a blocking review, missing policy evidence and unapproved citations never reach the user | `test_withholds_unsafe_answer_*` |
| Functional — Allows safe answers | Education and budgeting answers are released with sources and without over-blocking | `test_allows_safe_answer_*` |

Functional tests run the whole `AgentOrchestrator` with the local fixture model
and policy corpus. They prove the workflow's routing and compliance decisions;
they do not measure the wording quality of a live model.

## Reading the results

Each job writes a table to its GitHub Actions job summary: the scenario, the
question asked, the result, a truncated agent answer and
any failure reason. The JUnit XML and the summary are uploaded as artifacts and
kept for 30 days.

## Running locally

From `apps/ai-service`:

    pytest tests/test_risk_compliance.py tests/test_guardrails.py
    pytest tests/test_risk_compliance_functional.py -k test_blocks_unsafe_request
    pytest tests/test_risk_compliance_functional.py -k test_withholds_unsafe_answer
    pytest tests/test_risk_compliance_functional.py -k test_allows_safe_answer

On Windows, add `-X utf8` after `python` (`python -X utf8 -m pytest ...`).

## Known gaps

With the offline fixture reviewer, which always approves, these unsafe drafts
are released because no deterministic rule catches them in the full workflow.
They are not asserted either way and are tracked for a decision by the agent
owners:

- an imperative trade instruction in a generated answer, for example
  "Sell your stocks today and buy the ETFs listed above.";
- another user's financial data in a generated answer, for example
  "Another user DEMO_USER_B saves SGD 2000 a month."
