# Representative-User Validation

## Decision And Status

This study validates whether intended users can understand and safely act on the deployed coach's explanations, confidence presentation, uncertainty, sources, limitations, and safety boundaries. It is separate from the blinded Nova Lite versus Nova Micro review, which supports model selection.

The study package is implemented, but the validation remains open until real representative participants complete the governed protocol. Automated or fabricated responses are not acceptable human evidence.

The current study policy and session template still require the historical model ID
`apac.amazon.nova-lite-v1:0` (`infra/llmsecops/representative-user-study.json`),
while the configured deployment uses OpenAI GPT-6 Luna. The validator enforces that
policy field. Do not treat a GPT-6 Luna session as accepted study evidence until the
study policy and template are reviewed and updated to the intended deployed model.

## Scope

The study is exploratory usability evidence for the synthetic-data demo. It does not establish statistical generalizability, approve real personal financial data, or authorize regulated financial advice.

Use at least five participants who resemble the intended adult users in Singapore. At least three must be independent of implementation and at least two must self-describe their financial familiarity as beginner. Aim for five to eight completed participants and include an accessibility need when practical. Do not collect protected demographics solely for this study.

The study uses:

- `infra/llmsecops/representative-user-study.json` for the scenarios and acceptance policy;
- `infra/llmsecops/representative-user-response-template.csv` for coded task results;
- `infra/llmsecops/representative-user-session-template.json` for aggregate recruitment and deployed-version metadata; and
- `infra/scripts/representative_user_validation.py` for validation and privacy-safe aggregation.

## Participant Protection

Before the session, tell each participant:

> This voluntary session evaluates the application, not you. Use only the supplied synthetic profile and do not enter real financial or identifying information. You may skip a task or stop at any time. We record a pseudonymous participant code, task scores, ratings, and coded issues—not your name, email, prompts, or free-text response.

Confirm any institutional ethics or consent requirements before recruitment. Use participant codes `P001` through `P999`. Keep scheduling or contact information outside the repository and do not place it in an evidence artifact.

Store individual coded response rows only under the ignored `artifacts/` directory. Restrict access, retain them for no more than 30 days after the result is verified, and then delete them. The generated aggregate report contains no participant identifiers and may be retained with assessment evidence.

## Environment And Synthetic Profiles

Record the exact deployed commit SHA, model/profile ID, prompt-set version, and study date in the session file. Confirm that every assistant answer can show the collapsed **Why this answer and how certain it is** panel with:

- the areas used and routing rationale;
- each participating component's rationale and self-assessed confidence;
- a warning that confidence is not a probability or guarantee;
- the safety-review outcome; and
- a reference ID and prompt-set version.

The presentation is derived from the retained orchestration trace rather than copied into durable chat history. It is therefore available only while the trace remains within its configured 30-day retention period.

For each participant, create two new synthetic profiles under the facilitator's authenticated test identity. Replace `P001` with the assigned participant code:

| Profile | Synthetic setup |
|---|---|
| `study-P001` | SGD 5,000 monthly income; recurring rent SGD 1,800 and utilities SGD 200; current-month groceries SGD 600, dining SGD 400, and transport SGD 300; budget limits of housing SGD 1,800, food SGD 800, transport SGD 350, and utilities SGD 250; emergency-fund goal SGD 12,000 with SGD 3,000 saved and 18 months remaining; beginner financial literacy and plain-language preference. |
| `study-P001-missing` | SGD 5,000 monthly income, no transactions, no budget, and no goals. |

Do not reuse another participant's conversations. Delete both profiles after the participant's coded results have been checked.

## Facilitated Procedure

Run each scenario in a new conversation. Use `study-P001-missing` only for `missing-input`; use the main synthetic profile for the other scenarios. Read the task prompt exactly from the governed study policy. Do not explain the confidence panel or sources before the participant attempts the task.

After each task, ask these questions without suggesting an answer:

1. In your own words, why did the coach produce this answer?
2. What does the displayed confidence mean—and what does it not mean?
3. What important limitation, assumption, or missing information do you see?
4. When sources are present, what do they support? When absent, record this item as not applicable.
5. What would you do next, and what would you verify before acting?

Then ask the participant to rate each applicable statement from 1 (strongly disagree) to 5 (strongly agree):

- The explanation makes the answer understandable.
- The confidence presentation is clear.
- The uncertainty or missing information is clear.
- The role of the sources is clear.
- The answer gives me a safe and practical next step.

The facilitator codes an objective item as `1` only when the participant demonstrates the understanding without being taught during that task. Code it as `0` otherwise. For an incomplete task, set all assessment fields to `na`. Source fields must be `na` outside `grounded-education`.

Use only the issue codes defined by the policy. `overtrust`, `unsafe_next_action`, and `privacy_concern` are critical. Do not record verbatim participant comments in the governed CSV; translate observations into the approved codes and summarize non-identifying themes separately.

## Acceptance Decision

The policy requires:

- at least five participants completing every scenario;
- at least 90 percent task completion;
- at least 80 percent correct explanation, confidence, limitation, source-use, and verification understanding;
- 100 percent safe-next-action understanding;
- median applicable clarity and actionability ratings of at least 4 out of 5;
- the same thresholds within each applicable scenario, so one weak scenario cannot be hidden by the aggregate; and
- zero critical issues.

These are conjunctive gates. A failed gate requires an investigated presentation or workflow change and a fresh governed validation; it must not be averaged away or replaced by the blinded model-comparison result.

## Evidence Generation

Copy both templates into `artifacts/`, fill them without adding columns, and run:

```powershell
.\.venv\Scripts\python.exe infra\scripts\representative_user_validation.py `
  --policy infra\llmsecops\representative-user-study.json `
  --session artifacts\representative-user-session.json `
  --responses artifacts\representative-user-responses.csv `
  --output artifacts\representative-user-validation.json
```

The command rejects identifying or free-text columns, invalid participant codes, missing or duplicate scenario rows, invalid scales, inconsistent recruitment totals, and ungoverned issue codes. It emits only aggregate counts, rates, medians, coded-issue counts, threshold failures, version metadata, and input digests.

If the report passes, review it with the product and Responsible AI owners, retain the approved aggregate artifact, and update `docs/operational-evidence.md`. If it fails, record the failed metric and scenario, correct the presentation, rerun CI/CD, and repeat the study before closing this evidence item.
