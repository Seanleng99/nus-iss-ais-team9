# Investment Agent Safety Tests

The investment-agent evaluation covers 13 prompt-injection and benign request scenarios, with 15 application requests when real-provider evaluation is enabled. Nine attack cases are blocked before model generation. Exact offline fixtures and regression cases are in [`test_manual_investment_injection.py`](../apps/ai-service/tests/test_manual_investment_injection.py); the offline suite also exercises guardrail and compliance behavior. The live evaluation uses the checked-out production model configuration: OpenAI `gpt-6-luna` with low reasoning effort and the reviewed Education and Policy corpora.

Run the offline suite from the repository root:

```sh
python -m pip install -e "apps/shared" -e "apps/ai-service[dev]"
pytest apps/ai-service/tests/test_manual_investment_injection.py \
  apps/ai-service/tests/test_guardrails.py \
  apps/ai-service/tests/test_risk_compliance.py \
  apps/ai-service/tests/test_investment_live_contract.py
```

For a local live run, set `OPENAI_API_KEY` in a private shell environment, then run:

```sh
mkdir -p artifacts
RUN_LIVE_INVESTMENT_TESTS=1 \
INVESTMENT_TEST_REPORT=artifacts/investment-agent-live.json \
pytest apps/ai-service/tests/test_investment_agent_live.py -m live_model --tb=short
```

The test has bounded timeouts and fails on request errors. The test runner does not rerun failed scenarios; runtime model calls retain their bounded retry behavior. It writes its safe summary to `artifacts/investment-agent-live.json` when `INVESTMENT_TEST_REPORT` is set. Keep credentials out of command arguments, shell history, logs, and reports.

GitHub Actions runs the offline suite for matching pull requests and pushes. The paid evaluation is manual, defaults to off, and runs only when dispatched from `main`. It uses short-lived GitHub OIDC credentials to read the existing API-key secret. Create the dedicated role from [`investment-agent-tests-oidc.yaml`](../infra/aws/investment-agent-tests-oidc.yaml), passing the existing OpenAI secret's exact ARN. Confirm the ARN with `aws secretsmanager describe-secret` and record only its metadata, never its value. Then set the returned role ARN and secret ID as repository variables:

```sh
gh variable set AWS_INVESTMENT_TEST_ROLE_ARN --body '<role ARN from CloudFormation>'
gh variable set INVESTMENT_TEST_OPENAI_SECRET_ID --body '<existing secret name or ARN>'
```

Do not add the model key as a GitHub secret. A push to `main` can trigger the existing release workflow; this workflow has no deploy job, and its live evaluation is not a release gate.
