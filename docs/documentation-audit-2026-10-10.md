# Documentation alignment audit — 10 October 2026

Reviewed all **100 Markdown files tracked at the audit baseline**, commit
`8fcd3fdd92403bf0f53935b5dce5924d050b7e98`. The table below covers each file;
**55 existing Markdown files were updated; 45 were retained after review.**
This new audit record is additional to those 100. This is a source/documentation
review, not a new application release or live-model acceptance run.

## Source of truth and corrections

- **CI and evaluation:** compared all eight workflow YAML files, the version 3
  agent-evaluation specification, suite selection and report scripts, datasets and
  policy gates. The unified workflow has seven required offline suites and seven
  optional, manually enabled live suites. Live failures are advisory; existing
  release health and safety smoke checks still gate deployment. See
  [CI/CD](cicd-pipeline.md) and [job and evaluation details](agent-test-workflows.md).
- **Models, retrieval and prompts:** distinguished OpenAI generation from the two
  Bedrock retrieval collections, local development modes from AWS configuration,
  and the current v10 prompt catalog from retained versions. Education is pinned
  to `investment-education-sg@2026-09-27.2`; Policy is pinned to
  `financial-coach-policy-sg@2026-10-09.1`. Updated diagrams and ingestion guidance
  against the release scripts and manifests.
- **Agent behavior and memory:** checked orchestrator-controlled dependencies,
  the shared Education grounding capability, role-scoped inputs, validated
  observations, chat history, pending-action persistence and streaming logs.
  Existing chat context is distinguished from disabled cross-chat durable memory.
- **Product and operations:** corrected Budget/Coach UI instructions, explicit
  recurrence behavior, current migration head `20261010_0018`, request quotas,
  and deployment-versus-infrastructure activation claims.
- **Historical evidence:** retained original dates, counts, failures and limits.
  Replaced machine-specific source links and missing local-artifact hyperlinks;
  explicitly marked retired workflows and old rollout statements as historical.

Runtime configuration and Python code take precedence over old prose. The
[representative-user study](representative-user-validation.md) still requires
Nova Lite in its policy/template while the application uses GPT-6 Luna; that
mismatch is now explicit. Updating the study policy requires a separate governed
change. Likewise, documented drift monitoring does not imply an accepted live
baseline or activated monitoring.

## Verification

- Checked **659 repository-local Markdown links**, including line/heading anchors,
  across the resulting 101 Markdown files; no broken targets were found.
- Validated Education and Policy governance preparation: **10 Education and
  3 Policy documents**, with no validation issues. The 13 source Markdown files
  and their pinned manifests were not edited or uploaded to AWS.
- Ran the repository final-assessment inventory validator: **15 requirements,
  6 scenarios and 56 referenced evidence files**, retaining **5 deferred
  scope decisions**. This validates inventory/hashes, not whether deferred gates pass.
- Regenerated the [Chinese character inventory](chinese-character-inventory.md)
  and its companion JSON using `scripts/scan_chinese.py --check-code`.
- Checked the final diff for whitespace errors and restricted changes to
  documentation and its generated inventory. No application tests, paid model
  calls, AWS mutations or production acceptance checks were needed for this edit.

## File-by-file coverage

“Reviewed; retained” means the file already matched its current or explicitly
historical scope. “Retained corpus” means governed retrieval content was inspected
and validated without changing its approved bytes. “Updated” includes factual
corrections, portable references and explicit historical scope.

| Tracked Markdown file | Outcome | Review focus |
|---|---|---|
| [README.md](../README.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [SECURITY.md](../SECURITY.md) | Reviewed; retained | Application configuration, repository structure, deployment scripts and current guides. |
| [apps/ai-service/README.md](../apps/ai-service/README.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [apps/ai-service/prompts/v1/README.md](../apps/ai-service/prompts/v1/README.md) | Updated | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v2/README.md](../apps/ai-service/prompts/v2/README.md) | Updated | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v3/README.md](../apps/ai-service/prompts/v3/README.md) | Reviewed; retained | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v4/README.md](../apps/ai-service/prompts/v4/README.md) | Reviewed; retained | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v5/README.md](../apps/ai-service/prompts/v5/README.md) | Reviewed; retained | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v6/README.md](../apps/ai-service/prompts/v6/README.md) | Updated | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v7/README.md](../apps/ai-service/prompts/v7/README.md) | Updated | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v8/README.md](../apps/ai-service/prompts/v8/README.md) | Updated | Archived prompt version compared with the current v10 catalog. |
| [apps/ai-service/prompts/v9/README.md](../apps/ai-service/prompts/v9/README.md) | Reviewed; retained | Archived prompt version compared with the current v10 catalog. |
| [docs/adr/0001-mcp-a2a-decision.md](adr/0001-mcp-a2a-decision.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/adr/0002-dynamic-agent-dependencies.md](adr/0002-dynamic-agent-dependencies.md) | Reviewed; retained | Enforcement code, configuration and explicit residual limitations. |
| [docs/adr/0003-cross-user-data-access-guardrail.md](adr/0003-cross-user-data-access-guardrail.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/agent-design.md](agent-design.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/agent-reasoning-live-root-causes-2026-10-08.md](agent-reasoning-live-root-causes-2026-10-08.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-root-causes-2026-10-09.md](agent-reasoning-live-root-causes-2026-10-09.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-07.md](agent-reasoning-live-test-results-2026-10-07.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-08-post0287740-partial.md](agent-reasoning-live-test-results-2026-10-08-post0287740-partial.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-08-post0287740.md](agent-reasoning-live-test-results-2026-10-08-post0287740.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-08-postdae539d.md](agent-reasoning-live-test-results-2026-10-08-postdae539d.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-08-poste99409d.md](agent-reasoning-live-test-results-2026-10-08-poste99409d.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-08.md](agent-reasoning-live-test-results-2026-10-08.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-live-test-results-2026-10-09.md](agent-reasoning-live-test-results-2026-10-09.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-reasoning-test-prompts-2026-10-07.md](agent-reasoning-test-prompts-2026-10-07.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/agent-test-workflows.md](agent-test-workflows.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/ai-security-hardening-2026-10-10.md](ai-security-hardening-2026-10-10.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/architecture.md](architecture.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/aws-account-migration.md](aws-account-migration.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/bedrock-kb-restoration-2026-10-09.md](bedrock-kb-restoration-2026-10-09.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/budget-agent-evaluation.md](budget-agent-evaluation.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/budget-browser-acceptance-20261001.md](budget-browser-acceptance-20261001.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/budget-planning.md](budget-planning.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/budget-roadmap.md](budget-roadmap.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/budget-usability.md](budget-usability.md) | Reviewed; retained | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/chinese-character-inventory.md](chinese-character-inventory.md) | Updated | Regenerated from tracked and non-ignored project text. |
| [docs/cicd-pipeline.md](cicd-pipeline.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/coach-response-remediation-2026-10-03.md](coach-response-remediation-2026-10-03.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/coach-response-rigidity-audit-2026-10-03.md](coach-response-rigidity-audit-2026-10-03.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/combined-education-recovery.md](combined-education-recovery.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/conditional-financial-dependencies.md](conditional-financial-dependencies.md) | Reviewed; retained | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/container-security.md](container-security.md) | Reviewed; retained | Enforcement code, configuration and explicit residual limitations. |
| [docs/current-prompt-contract.md](current-prompt-contract.md) | Reviewed; retained | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/data-lifecycle.md](data-lifecycle.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/demo-runbook.md](demo-runbook.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/durable-decision-traces.md](durable-decision-traces.md) | Reviewed; retained | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/evaluation-evidence/ai-security-hardening-live-2026-10-10.md](evaluation-evidence/ai-security-hardening-live-2026-10-10.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/evaluation-plan.md](evaluation-plan.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/final-assessment.md](final-assessment.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/goal-agent-evaluation.md](goal-agent-evaluation.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/investment-agent-evaluation.md](investment-agent-evaluation.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/investment-agent-live-evaluation.md](investment-agent-live-evaluation.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/investment-call-logging.md](investment-call-logging.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/language-support.md](language-support.md) | Reviewed; retained | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/latest-live-failure-fixes-2026-10-09.md](latest-live-failure-fixes-2026-10-09.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/model-drift-monitoring.md](model-drift-monitoring.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/model-selection.md](model-selection.md) | Reviewed; retained | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/operational-alert-runbook.md](operational-alert-runbook.md) | Reviewed; retained | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/operational-evidence.md](operational-evidence.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/operations.md](operations.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/orchestration-current-implementation-2026-10-07.md](orchestration-current-implementation-2026-10-07.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/orchestration-live-fixes.md](orchestration-live-fixes.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/orchestration-local-claim-recovery-2026-10-09.md](orchestration-local-claim-recovery-2026-10-09.md) | Reviewed; retained | Dated evidence or design history; results kept separate from current behavior. |
| [docs/orchestration-post-retest-recovery.md](orchestration-post-retest-recovery.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/orchestration-read-only-recovery.md](orchestration-read-only-recovery.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/orchestration-review-recovery.md](orchestration-review-recovery.md) | Reviewed; retained | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/policy-rag-governance.md](policy-rag-governance.md) | Updated | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/project-security-scan.md](project-security-scan.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/rag-quality.md](rag-quality.md) | Updated | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/rag-source-governance.md](rag-source-governance.md) | Updated | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/rag_arch.md](rag_arch.md) | Updated | Retriever/model configuration, manifests, prompt catalog and release behavior. |
| [docs/representative-user-validation.md](representative-user-validation.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/requirements-summary.md](requirements-summary.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/requirements-traceability.md](requirements-traceability.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [docs/responsible-ai.md](responsible-ai.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/risk-compliance-agent-evaluation.md](risk-compliance-agent-evaluation.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/risk-compliance-agent-tests.md](risk-compliance-agent-tests.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/risk-compliance-review-update-2026-10-09.md](risk-compliance-review-update-2026-10-09.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/security-guardrails.md](security-guardrails.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/security-risk-register.md](security-risk-register.md) | Updated | Enforcement code, configuration and explicit residual limitations. |
| [docs/session-context.md](session-context.md) | Updated | Agent/backend/frontend contracts, routing, context, tools and response flow. |
| [docs/spending-agent-evaluation.md](spending-agent-evaluation.md) | Reviewed; retained | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [docs/superpowers/plans/2026-10-03-risk-compliance-agent-tests.md](superpowers/plans/2026-10-03-risk-compliance-agent-tests.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [docs/superpowers/specs/2026-10-03-risk-compliance-agent-tests-design.md](superpowers/specs/2026-10-03-risk-compliance-agent-tests-design.md) | Updated | Dated evidence or design history; results kept separate from current behavior. |
| [infra/aws/README.md](../infra/aws/README.md) | Updated | Application configuration, repository structure, deployment scripts and current guides. |
| [infra/llmsecops/conversational-evaluation.md](../infra/llmsecops/conversational-evaluation.md) | Updated | Workflow jobs, test datasets, metric policies, evidence scope and opt-in gates. |
| [knowledge/investment_education/documents/cpf_beginner_investing.md](../knowledge/investment_education/documents/cpf_beginner_investing.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/cpf_investment_scheme.md](../knowledge/investment_education/documents/cpf_investment_scheme.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_compound_interest.md](../knowledge/investment_education/documents/moneysense_compound_interest.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_guide_to_etfs.md](../knowledge/investment_education/documents/moneysense_guide_to_etfs.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_investment_risk.md](../knowledge/investment_education/documents/moneysense_investment_risk.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_investment_scams.md](../knowledge/investment_education/documents/moneysense_investment_scams.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_managing_debt.md](../knowledge/investment_education/documents/moneysense_managing_debt.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_managing_money.md](../knowledge/investment_education/documents/moneysense_managing_money.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_types_of_investments.md](../knowledge/investment_education/documents/moneysense_types_of_investments.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/investment_education/documents/moneysense_what_is_investing.md](../knowledge/investment_education/documents/moneysense_what_is_investing.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/policy_controls/documents/advice_boundary.md](../knowledge/policy_controls/documents/advice_boundary.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/policy_controls/documents/evidence_and_citation.md](../knowledge/policy_controls/documents/evidence_and_citation.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
| [knowledge/policy_controls/documents/instruction_security.md](../knowledge/policy_controls/documents/instruction_security.md) | Retained corpus | Governed source text, manifest checksums and ingestion validation; bytes retained. |
