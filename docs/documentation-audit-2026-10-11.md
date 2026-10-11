# Documentation and evidence audit — 11 October 2026

Reviewed the repository implementation at commit `ab20e2201ecca59ef6daec979622ad12bc6a208a` and the
documentation working tree, including the three existing untracked index/latest
v10 report/evidence files. The starting inventory contained **154
documentation, evidence and diagram assets**, including **107 Markdown files**.
**51 obsolete files were removed**; **103 starting assets were retained**.
This audit is additional to that inventory. The coverage tables below account for
every starting file. Application code, policies and governed corpus content were
preserved. External course briefing and original submission files remain source
material rather than current implementation guides.

## Source alignment

- Current dependency, prompt, Budget, chat, trace and logging guides now describe
  the implemented contracts. Migration `20261010_0018` adds shared Coach quota
  tables; earlier action-state and recurrence migrations retain their own roles.
- Evaluation guides match agent specification v4 and ownership specification v2,
  including platform/shared test ownership and xpass rejection. The current
  conjunctive offline policy has nine suites and 136 cases/pairs, including 19
  fairness pairs. Historical 87-case test results remain dated measurements.
- Release guidance preserves mandatory health/configuration acceptance and the
  snapshotted optional security, fairness and agent/RAG stages. Disabled stages
  are skipped, and enabled failed or incomplete stages reject acceptance. AWS
  Operational Validation currently covers infrastructure, edge and retention;
  standalone model/load harnesses remain separately available.
- Operational and security guides distinguish current alarm definitions, quota
  activation evidence, synthetic exchange logging exceptions, backup deletion
  limits and approved drift monitoring from historical rollout statements.
  Earlier failed captures and the current grading alert remain visible.
- Policy RAG retrieves every mandatory source before reviewer filtering, but
  reconstructed chunks do not prove full document coverage. Unsafe or oversized
  contexts may then be discarded; the reviewer only requires nonempty evidence
  and does not recheck mandatory-source coverage. This remaining implementation
  limit is recorded in governance, architecture, evaluation and security guides.
- Logical and AWS Mermaid source files now match the current architecture guide.
  Unreferenced exports describing Bedrock generation and scheduled ingestion, and
  the September ERD predating current tables, were removed. The current ORM and
  migrations remain the database authority.

## Retained evidence and limits

The latest retained browser retest remains build `7356713`, prompt v10:
**30/34 original turns, case 35 and 6/7 repeats passed**. Two withheld and three
incomplete answers remain failures. It does not validate later implementation
changes. The preceding v10 report and diagnosis remain necessary to explain the
local claim recovery. Original JSON, screenshot, CSV and report counts were not
rewritten to imply current acceptance.

All **20 retained files under `docs/evaluation-evidence/`** retain their
original bytes. Fairness fixtures, the blocked live run, review worksheet, drift
approval and failed capture records are retained. The release split record retains
distinct OIDC failure/readback history; optional-release verification describes the
current gate selection. Historical paths inside original JSON reports identify
prior artifacts, including retired v9 comparison inputs and mandatory-stage wiring.
Those identifiers remain recoverable from Git and are not current guide links.

The original Word proposal remains a requirements source. Its Angular/Spring and
Bedrock-generation design is historical. Governed Education/Policy Markdown and
manifest checksums remain unchanged. Reusable scenario protocols, ADRs, assessment
references, original failure evidence and deferred study requirements remain.

## Verification

- Checked **673 repository-local file and heading links across 81 Markdown files**;
  all targets resolve. The generated character inventory was
  refreshed after removal, with no Chinese characters in source code.
- Local governance preparation passed for **10 Education and 3 Policy documents**
  with no validation issues and no remote ingestion.
- Final-assessment inventory validation passed: **15 requirements, six demo
  scenarios, five deferred decisions and 111 integrity-hashed required files**.
  The validator measures inventory integrity, not overall assessment acceptance.
- The existing entry-logging inventory contract passed under UTF-8, verifying its
  678 implemented methods and unchanged inventory JSON. Whitespace validation
  passed. The two Mermaid sources match their architecture blocks exactly.
- Hash comparison confirmed unchanged retained evidence, governed source bytes
  and the original proposal. No new application release, paid model call, browser
  acceptance run or AWS mutation was performed for this documentation review.

Local check outputs are under ignored `artifacts/documentation-audit-2026-10-11/`.
The retained [index](README.md) is the entry point for current guides and evidence.

## Retained file coverage

| Starting file | Review outcome |
|---|---|
| [README.md](../README.md) | Updated against current source and cross-references |
| [SECURITY.md](../SECURITY.md) | Reviewed; retained within current or explicitly historical scope |
| [apps/ai-service/README.md](../apps/ai-service/README.md) | Updated against current source and cross-references |
| [diagrams/financial-coach-logical.mmd](../diagrams/financial-coach-logical.mmd) | Updated against current source and cross-references |
| [diagrams/financial-coach-physical.mmd](../diagrams/financial-coach-physical.mmd) | Updated against current source and cross-references |
| [docs/Project Proposal_Team 9.docx](<Project Proposal_Team 9.docx>) | Retained original requirements proposal; implementation differs |
| [docs/adr/0001-mcp-a2a-decision.md](adr/0001-mcp-a2a-decision.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/adr/0002-dynamic-agent-dependencies.md](adr/0002-dynamic-agent-dependencies.md) | Updated against current source and cross-references |
| [docs/adr/0003-cross-user-data-access-guardrail.md](adr/0003-cross-user-data-access-guardrail.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/agent-design.md](agent-design.md) | Updated against current source and cross-references |
| [docs/agent-reasoning-live-root-causes-2026-10-09.md](agent-reasoning-live-root-causes-2026-10-09.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/agent-reasoning-live-test-results-2026-10-09.md](agent-reasoning-live-test-results-2026-10-09.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/agent-reasoning-test-prompts-2026-10-07.md](agent-reasoning-test-prompts-2026-10-07.md) | Updated against current source and cross-references |
| [docs/agent-test-workflows.md](agent-test-workflows.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/ai-security-hardening-2026-10-10.md](ai-security-hardening-2026-10-10.md) | Updated against current source and cross-references |
| [docs/architecture.md](architecture.md) | Updated against current source and cross-references |
| [docs/aws-account-migration.md](aws-account-migration.md) | Updated against current source and cross-references |
| [docs/bedrock-kb-restoration-2026-10-09.md](bedrock-kb-restoration-2026-10-09.md) | Updated against current source and cross-references |
| [docs/budget-agent-evaluation.md](budget-agent-evaluation.md) | Updated against current source and cross-references |
| [docs/budget-browser-acceptance-20261001.md](budget-browser-acceptance-20261001.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/budget-planning.md](budget-planning.md) | Updated against current source and cross-references |
| [docs/budget-usability.md](budget-usability.md) | Updated against current source and cross-references |
| [docs/chinese-character-inventory.json](chinese-character-inventory.json) | Reviewed; retained within current or explicitly historical scope |
| [docs/chinese-character-inventory.md](chinese-character-inventory.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/cicd-pipeline.md](cicd-pipeline.md) | Updated against current source and cross-references |
| [docs/conditional-financial-dependencies.md](conditional-financial-dependencies.md) | Updated against current source and cross-references |
| [docs/container-security.md](container-security.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/current-prompt-contract.md](current-prompt-contract.md) | Updated against current source and cross-references |
| [docs/data-lifecycle.md](data-lifecycle.md) | Updated against current source and cross-references |
| [docs/demo-runbook.md](demo-runbook.md) | Updated against current source and cross-references |
| [docs/durable-decision-traces.md](durable-decision-traces.md) | Updated against current source and cross-references |
| [docs/evaluation-evidence/agent-reasoning-live-v10-2026-10-09-proof.jpg](evaluation-evidence/agent-reasoning-live-v10-2026-10-09-proof.jpg) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/agent-reasoning-live-v10-2026-10-09.json](evaluation-evidence/agent-reasoning-live-v10-2026-10-09.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/ai-security-hardening-2026-10-10.json](evaluation-evidence/ai-security-hardening-2026-10-10.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/ai-security-hardening-live-2026-10-10.md](evaluation-evidence/ai-security-hardening-live-2026-10-10.md) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/fairness-fixture-human-review-2026-10-11.csv](evaluation-evidence/fairness-fixture-human-review-2026-10-11.csv) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/fairness-local_fixture-2026-10-11-e3047345.json](evaluation-evidence/fairness-local_fixture-2026-10-11-e3047345.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/fairness-openai-2026-10-11-c741fef7.json](evaluation-evidence/fairness-openai-2026-10-11-c741fef7.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/fairness-verification-2026-10-11.md](evaluation-evidence/fairness-verification-2026-10-11.md) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/latest-live-failure-fixes-2026-10-09.json](evaluation-evidence/latest-live-failure-fixes-2026-10-09.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/model-drift-activation-2026-10-10.json](evaluation-evidence/model-drift-activation-2026-10-10.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/model-drift-activation-2026-10-11.json](evaluation-evidence/model-drift-activation-2026-10-11.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/model-drift-candidate-2026-10-10.json](evaluation-evidence/model-drift-candidate-2026-10-10.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/model-drift-human-review-2026-10-11.json](evaluation-evidence/model-drift-human-review-2026-10-11.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/model-drift-repair-2026-10-10.json](evaluation-evidence/model-drift-repair-2026-10-10.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/optional-release-live-verification-2026-10-11.json](evaluation-evidence/optional-release-live-verification-2026-10-11.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/orchestration-local-claim-recovery-2026-10-09.json](evaluation-evidence/orchestration-local-claim-recovery-2026-10-09.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/release-job-split-verification-2026-10-11.json](evaluation-evidence/release-job-split-verification-2026-10-11.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/risk-compliance-review-update-2026-10-09.json](evaluation-evidence/risk-compliance-review-update-2026-10-09.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-evidence/test-organization-verification-2026-10-11.json](evaluation-evidence/test-organization-verification-2026-10-11.json) | Retained original evidence; scope/failures preserved |
| [docs/evaluation-plan.md](evaluation-plan.md) | Updated against current source and cross-references |
| [docs/fairness-testing.md](fairness-testing.md) | Updated against current source and cross-references |
| [docs/final-assessment.md](final-assessment.md) | Updated against current source and cross-references |
| [docs/goal-agent-evaluation.md](goal-agent-evaluation.md) | Updated against current source and cross-references |
| [docs/investment-agent-evaluation.md](investment-agent-evaluation.md) | Updated against current source and cross-references |
| [docs/investment-agent-live-evaluation.md](investment-agent-live-evaluation.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/investment-call-logging.md](investment-call-logging.md) | Updated against current source and cross-references |
| [docs/investment-entry-logging.json](investment-entry-logging.json) | Reviewed; retained within current or explicitly historical scope |
| [docs/language-support.md](language-support.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/latest-live-failure-fixes-2026-10-09.md](latest-live-failure-fixes-2026-10-09.md) | Updated against current source and cross-references |
| [docs/model-drift-monitoring.md](model-drift-monitoring.md) | Updated against current source and cross-references |
| [docs/model-selection.md](model-selection.md) | Updated against current source and cross-references |
| [docs/operational-alert-runbook.md](operational-alert-runbook.md) | Updated against current source and cross-references |
| [docs/operational-evidence.md](operational-evidence.md) | Updated against current source and cross-references |
| [docs/operations.md](operations.md) | Updated against current source and cross-references |
| [docs/orchestration-current-implementation-2026-10-07.md](orchestration-current-implementation-2026-10-07.md) | Updated against current source and cross-references |
| [docs/orchestration-local-claim-recovery-2026-10-09.md](orchestration-local-claim-recovery-2026-10-09.md) | Updated against current source and cross-references |
| [docs/policy-rag-governance.md](policy-rag-governance.md) | Updated against current source and cross-references |
| [docs/post-deployment-acceptance.md](post-deployment-acceptance.md) | Updated against current source and cross-references |
| [docs/project-security-scan.md](project-security-scan.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/rag-quality.md](rag-quality.md) | Updated against current source and cross-references |
| [docs/rag-source-governance.md](rag-source-governance.md) | Updated against current source and cross-references |
| [docs/rag_arch.md](rag_arch.md) | Updated against current source and cross-references |
| [docs/representative-user-validation.md](representative-user-validation.md) | Updated against current source and cross-references |
| [docs/requirements-summary.md](requirements-summary.md) | Updated against current source and cross-references |
| [docs/requirements-traceability.md](requirements-traceability.md) | Updated against current source and cross-references |
| [docs/responsible-ai.md](responsible-ai.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/risk-compliance-agent-evaluation.md](risk-compliance-agent-evaluation.md) | Updated against current source and cross-references |
| [docs/risk-compliance-agent-tests.md](risk-compliance-agent-tests.md) | Updated against current source and cross-references |
| [docs/risk-compliance-review-update-2026-10-09.md](risk-compliance-review-update-2026-10-09.md) | Updated against current source and cross-references |
| [docs/security-guardrails.md](security-guardrails.md) | Updated against current source and cross-references |
| [docs/security-risk-register.md](security-risk-register.md) | Updated against current source and cross-references |
| [docs/session-context.md](session-context.md) | Updated against current source and cross-references |
| [docs/spending-agent-evaluation.md](spending-agent-evaluation.md) | Updated against current source and cross-references |
| [docs/test-organization.md](test-organization.md) | Reviewed; retained within current or explicitly historical scope |
| [infra/aws/README.md](../infra/aws/README.md) | Updated against current source and cross-references |
| [infra/llmsecops/conversational-evaluation.md](../infra/llmsecops/conversational-evaluation.md) | Updated against current source and cross-references |
| [knowledge/investment_education/documents/cpf_beginner_investing.md](../knowledge/investment_education/documents/cpf_beginner_investing.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/cpf_investment_scheme.md](../knowledge/investment_education/documents/cpf_investment_scheme.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_compound_interest.md](../knowledge/investment_education/documents/moneysense_compound_interest.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_guide_to_etfs.md](../knowledge/investment_education/documents/moneysense_guide_to_etfs.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_investment_risk.md](../knowledge/investment_education/documents/moneysense_investment_risk.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_investment_scams.md](../knowledge/investment_education/documents/moneysense_investment_scams.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_managing_debt.md](../knowledge/investment_education/documents/moneysense_managing_debt.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_managing_money.md](../knowledge/investment_education/documents/moneysense_managing_money.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_types_of_investments.md](../knowledge/investment_education/documents/moneysense_types_of_investments.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/investment_education/documents/moneysense_what_is_investing.md](../knowledge/investment_education/documents/moneysense_what_is_investing.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/policy_controls/documents/advice_boundary.md](../knowledge/policy_controls/documents/advice_boundary.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/policy_controls/documents/evidence_and_citation.md](../knowledge/policy_controls/documents/evidence_and_citation.md) | Retained governed corpus; approved bytes unchanged |
| [knowledge/policy_controls/documents/instruction_security.md](../knowledge/policy_controls/documents/instruction_security.md) | Retained governed corpus; approved bytes unchanged |
| [docs/agent-reasoning-live-test-results-2026-10-09-post7356713.md](agent-reasoning-live-test-results-2026-10-09-post7356713.md) | Reviewed; retained within current or explicitly historical scope |
| [docs/README.md](README.md) | Updated evidence index and retention guidance |
| [docs/evaluation-evidence/agent-reasoning-live-v10-2026-10-09-post7356713.json](evaluation-evidence/agent-reasoning-live-v10-2026-10-09-post7356713.json) | Retained original evidence; scope/failures preserved |

## Removed file coverage

All removed files were tracked and remain recoverable from Git. None are required
by the final-assessment manifest. Current guide links were updated in the same review.

| Retired file | Reason |
|---|---|
| `apps/ai-service/prompts/v1/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v2/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v3/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v4/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v5/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v6/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v7/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v8/README.md` | Retired prompt notes; current catalog and Git history retained |
| `apps/ai-service/prompts/v9/README.md` | Retired prompt notes; current catalog and Git history retained |
| `diagrams/financial-coach-logical.excalidraw` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `diagrams/financial-coach-logical.png` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `diagrams/financial-coach-logical.svg` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `diagrams/financial-coach-physical.excalidraw` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `diagrams/financial-coach-physical.png` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `diagrams/financial-coach-physical.svg` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `docs/ERD.png` | Outdated unreferenced architecture exports; current Mermaid views retained |
| `docs/agent-reasoning-live-root-causes-2026-10-08.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-07.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-08-post0287740-partial.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-08-post0287740.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-08-postdae539d.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-08-poste99409d.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/agent-reasoning-live-test-results-2026-10-08.md` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/budget-roadmap.md` | Completed implementation notes consolidated into current guides |
| `docs/coach-response-remediation-2026-10-03.md` | Completed implementation notes consolidated into current guides |
| `docs/coach-response-rigidity-audit-2026-10-03.md` | Completed implementation notes consolidated into current guides |
| `docs/combined-education-recovery.md` | Completed implementation notes consolidated into current guides |
| `docs/documentation-audit-2026-10-10.md` | Prior audit replaced by this complete source and evidence review |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-07.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08-post0287740-partial.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08-post0287740.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08-postdae539d.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08-poste99409d-trace-viewer.png` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08-poste99409d.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-2026-10-08.json` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-case-28.png` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-trace-viewer-2026-10-08-post0287740.jpg` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-trace-viewer-2026-10-08-postdae539d.png` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/agent-reasoning-live-v9-trace-viewer-2026-10-08.png` | Retired v9 browser contracts superseded by retained v10 before/after reports |
| `docs/evaluation-evidence/conditional-financial-dependencies-v9.json` | Superseded passing local contract evidence |
| `docs/evaluation-evidence/orchestration-live-fixes-source-verification.json` | Completed implementation notes consolidated into current guides |
| `docs/evaluation-evidence/orchestration-post-retest-recovery-2026-10-08.json` | Completed implementation notes consolidated into current guides |
| `docs/evaluation-evidence/orchestration-read-only-recovery-2026-10-08.json` | Completed implementation notes consolidated into current guides |
| `docs/evaluation-evidence/orchestration-review-recovery-2026-10-08.json` | Completed implementation notes consolidated into current guides |
| `docs/evaluation-evidence/release-live-acceptance-wiring-2026-10-11.json` | Superseded passing local contract evidence |
| `docs/orchestration-live-fixes.md` | Completed implementation notes consolidated into current guides |
| `docs/orchestration-post-retest-recovery.md` | Completed implementation notes consolidated into current guides |
| `docs/orchestration-read-only-recovery.md` | Completed implementation notes consolidated into current guides |
| `docs/orchestration-review-recovery.md` | Completed implementation notes consolidated into current guides |
| `docs/superpowers/plans/2026-10-03-risk-compliance-agent-tests.md` | Retired standalone workflow plans replaced by agent test workflow guides |
| `docs/superpowers/specs/2026-10-03-risk-compliance-agent-tests-design.md` | Retired standalone workflow plans replaced by agent test workflow guides |
