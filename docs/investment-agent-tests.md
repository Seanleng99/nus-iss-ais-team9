# Investment Agent Tests

The investment-agent evaluation covers 13 prompt-injection and benign request scenarios, with 15 application requests when real-provider evaluation is enabled. Nine attack cases are blocked before model generation. Exact offline fixtures and regression cases are in [`test_manual_investment_injection.py`](../apps/ai-service/tests/test_manual_investment_injection.py); the offline suite also exercises guardrail and compliance behavior. The live evaluation uses the checked-out production model configuration: OpenAI `gpt-6-luna` with low reasoning effort and the reviewed Education and Policy corpora.

Run the offline suite from the repository root:

```sh
python -m pip install -e "apps/shared" -e "apps/ai-service[dev]"
mkdir -p artifacts
python -m pytest -vv --investment-report \
  apps/ai-service/tests/test_manual_investment_injection.py \
  apps/ai-service/tests/test_guardrails.py \
  apps/ai-service/tests/test_risk_compliance.py \
  apps/ai-service/tests/test_investment_live_contract.py \
  --junitxml=artifacts/investment-agent-offline.xml
python infra/scripts/summarize_investment_tests.py \
  artifacts/investment-agent-offline.xml \
  --output artifacts/investment-agent-offline-summary.md \
  --title "Offline investment safety test results"
```

## Functional investor tests

The functional suite adds 10 questions for each of three investor levels: beginner, intermediate, and senior specialist. It uses the local fixture model and the standard `LocalEducationRetriever` fixture passages to check workflow routing, evidence use, response output, and transparent limits. These offline checks verify application behavior; they do not measure live model answer quality or use full production retrieval content.

Run one level from the repository root (install dependencies as shown above):

```sh
mkdir -p artifacts
python -m pytest -k test_beginner_investor_functional -vv --investment-report \
  apps/ai-service/tests/test_investment_functional.py \
  --junitxml=artifacts/investment-agent-functional-beginner.xml
python infra/scripts/summarize_investment_tests.py \
  artifacts/investment-agent-functional-beginner.xml \
  --output artifacts/investment-agent-functional-beginner-summary.md \
  --title "Functional tests — Beginner investor (offline)"

python -m pytest -k test_intermediate_investor_functional -vv --investment-report \
  apps/ai-service/tests/test_investment_functional.py \
  --junitxml=artifacts/investment-agent-functional-intermediate.xml
python infra/scripts/summarize_investment_tests.py \
  artifacts/investment-agent-functional-intermediate.xml \
  --output artifacts/investment-agent-functional-intermediate-summary.md \
  --title "Functional tests — Intermediate investor (offline)"

python -m pytest -k test_specialist_investor_functional -vv --investment-report \
  apps/ai-service/tests/test_investment_functional.py \
  --junitxml=artifacts/investment-agent-functional-specialist.xml
python infra/scripts/summarize_investment_tests.py \
  artifacts/investment-agent-functional-specialist.xml \
  --output artifacts/investment-agent-functional-specialist-summary.md \
  --title "Functional tests — Senior specialist investor (offline)"
```

## Live safety evaluation

For a local live run of the safety scenarios, set `OPENAI_API_KEY` in a private shell environment, then run:

```sh
mkdir -p artifacts
RUN_LIVE_INVESTMENT_TESTS=1 \
INVESTMENT_TEST_REPORT=artifacts/investment-agent-live.json \
python -m pytest -vv --investment-report \
  apps/ai-service/tests/test_investment_agent_live.py \
  -m live_model --tb=short \
  --junitxml=artifacts/investment-agent-live.xml
python infra/scripts/summarize_investment_tests.py \
  artifacts/investment-agent-live.xml \
  --output artifacts/investment-agent-live-summary.md \
  --title "Live investment test results"
```

The test has bounded timeouts and fails on request errors. The test runner does not rerun failed scenarios; runtime model calls retain their bounded retry behavior. It writes its safe summary to `artifacts/investment-agent-live.json` when `INVESTMENT_TEST_REPORT` is set. Keep credentials out of command arguments, shell history, logs, and reports.

GitHub Actions runs the offline safety suite and three independent functional jobs for matching pull requests and pushes. Each functional job publishes a test table with the method, question, captured response, and result in the Actions run summary, and uploads its Markdown summary and JUnit XML. The paid evaluation is manual, defaults to off, and runs only when dispatched from `main`. It runs only after the offline safety and functional jobs pass, and uses short-lived GitHub OIDC credentials to read the existing API-key secret. Create the dedicated role from [`investment-agent-tests-oidc.yaml`](../infra/aws/investment-agent-tests-oidc.yaml), passing the existing OpenAI secret's exact ARN. Confirm the ARN with `aws secretsmanager describe-secret` and record only its metadata, never its value. Then set the returned role ARN and secret ID as repository variables:

```sh
gh variable set AWS_INVESTMENT_TEST_ROLE_ARN --body '<role ARN from CloudFormation>'
gh variable set INVESTMENT_TEST_OPENAI_SECRET_ID --body '<existing secret name or ARN>'
```

Do not add the model key as a GitHub secret. A push to `main` can trigger the existing release workflow; this workflow has no deploy job, and its live evaluation is not a release gate.

## Viewing test results

Open a GitHub Actions run's **Summary** tab to read each safety or functional Markdown table, captured agent responses, and actual pass, fail, error, and skip counts. Expand the corresponding publish step in a job log to see each question and captured response on prefixed lines. The Markdown summaries and JUnit XML files are also included under the run's **Artifacts** section.

The workflow passes `--investment-report` to pytest. It adds question and response properties to JUnit only when enabled. Explicit `test_questions` markers cover inputs exercised inside unparameterized methods. For parameterized tests, string parameters named `question`, `message`, `prompt`, `attack`, `instruction`, or `text` are included.

Application scenarios in the manual, functional, and live suites capture the final user-facing reply before checking assertions. Reports label each response as a mocked offline workflow, a deterministic safety response, or a live workflow. Multi-turn tests show captured question/response pairs in execution order; if a test stops early, later turns have no captured reply. Low-level checks and skipped tests without replies show `No agent response recorded`.
