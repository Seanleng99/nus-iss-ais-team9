# Risk & Compliance Agent Tests

Risk & Compliance tests are owned by the `risk-compliance` suite in the
consolidated **CI and LLMSecOps** workflow
([workflow file](../.github/workflows/ci.yml)). The suite runs
with local model and Policy fixtures; it makes no paid provider calls. Its exact
test selection and reporting contract are in
[`agent-test-suites.json`](../infra/llmsecops/agent-test-suites.json) and
[`agent-evaluation-specs.json`](../infra/llmsecops/agent-evaluation-specs.json).

The selection covers:

| Scenario group | Tests | Expected behavior |
|---|---|---|
| Offline policy and guardrails | `test_risk_compliance.py`, `test_risk_review_explanations.py`, `test_guardrails.py` | Allow safe education and warnings; block prohibited requests; sanitize reasons and retrieved instructions; redact identifiers; enforce role-scoped retrieval. |
| Block unsafe requests | `test_risk_compliance_functional.py -k test_blocks_unsafe_request` | Refuse recommendations, guarantees, account execution, cross-user access, and injection at the required boundary. |
| Withhold unsafe answers | `test_risk_compliance_functional.py -k test_withholds_unsafe_answer` | Withhold unsafe drafts, missing or invalid Policy evidence, reviewer vetoes, and unapproved citations. |
| Allow safe answers | `test_risk_compliance_functional.py -k test_allows_safe_answer` | Release permitted education, negated-suitability warnings, and valid Budget answers after independent review; blanket refusal fails the positive controls. |
| Fixture-backed dialogue examples | `test_agent_evaluation_examples.py::test_example_risk_compliance` | Run versioned synthetic questions through application components and check their authored response, safety, and source expectations. |

The three functional filters are disjoint selections from one test file. Each
parameterized case is counted separately. Acceptance requires at least one case,
100% assertion pass rate, and zero failures, errors, skips, or xpasses in every
group. An aggregate pass cannot hide a failed safety or privacy assertion.

The offline fixture reviewer is scripted, so these results verify application
contracts and the authored cases; they do not measure live-model reviewer accuracy
or answer quality. The separate shared Policy RAG metrics are published by the
required metrics job. Optional deployed tests and release smoke are separate
evidence; see the [evaluation guide](risk-compliance-agent-evaluation.md) and
[consolidated workflow guide](agent-test-workflows.md).

## Finding the results

In GitHub Actions, open **CI and LLMSecOps** and the
**risk-compliance — offline regression tests** job. Its job summary reports the
definition, selected tests, hashes, expected outputs, measured cases, and
acceptance. Download `agent-offline-risk-compliance` for JUnit XML, Markdown,
and the complete JSON evaluation report. The combined
`agent-evaluation-report` contains the consolidated results. These artifacts are
retained for 90 days.

## Running locally

From the repository root with the project dependencies installed:

```sh
MODEL_PROVIDER=local_fixture RAG_PROVIDER=local_fixture POLICY_RAG_PROVIDER=local_fixture \
  python infra/scripts/run_agent_tests.py --suite risk-compliance --junitxml artifacts/risk-compliance.xml
python infra/scripts/summarize_pytest_junit.py artifacts/risk-compliance.xml \
  --suite risk-compliance --title "Risk & Compliance offline" \
  --output artifacts/risk-compliance-summary.md \
  --evaluation-output artifacts/risk-compliance-evaluation.json
```

## Coverage limits

The functional unsafe-answer parameterization currently asserts three generated-advice
patterns: a guaranteed return, a product presented as the best choice, and personal
suitability. These checks do not establish that every imperative trade instruction
or third-party financial disclosure in generated prose is caught deterministically.
The real Compliance reviewer and broader adversarial testing remain necessary;
see [the security risk register](security-risk-register.md).
