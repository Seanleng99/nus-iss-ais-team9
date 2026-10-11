# Documentation and evidence index

Reviewed against repository source on 11 October 2026. Runtime code, packaged
prompt/corpus manifests and workflow definitions take precedence over dated
implementation notes. Retained test reports describe their tested build and
measurement scope; they do not establish acceptance of later changes.
The [11 October audit](documentation-audit-2026-10-11.md) records the reviewed
inventory, 51 removals, retained evidence integrity and local verification.

## Current guides

| Area | Guides |
|---|---|
| Project and assessment | [Requirements](requirements-summary.md), [traceability](requirements-traceability.md), [final assessment](final-assessment.md), [demo runbook](demo-runbook.md) |
| Architecture and agents | [Architecture](architecture.md), [agent design](agent-design.md), [orchestration](orchestration-current-implementation-2026-10-07.md), [conditional dependencies](conditional-financial-dependencies.md) |
| Prompts and review | [Current prompt contract](current-prompt-contract.md), [model selection](model-selection.md), [local claim recovery](orchestration-local-claim-recovery-2026-10-09.md), [Risk & Compliance contract](risk-compliance-review-update-2026-10-09.md) |
| Product and context | [Budget contracts](budget-planning.md), [Budget usability](budget-usability.md), [session context](session-context.md), [language support](language-support.md) |
| Traces and logs | [Durable decision traces](durable-decision-traces.md), [Investment call logging](investment-call-logging.md), [logging schema](investment-entry-logging.json) |
| Retrieval | [RAG architecture](rag_arch.md), [RAG quality](rag-quality.md), [Education governance](rag-source-governance.md), [Policy governance](policy-rag-governance.md) |
| Security and lifecycle | [Security guardrails](security-guardrails.md), [risk register](security-risk-register.md), [container security and active exceptions](container-security.md), [data lifecycle](data-lifecycle.md), [responsible AI](responsible-ai.md) |
| CI, release and operations | [CI/CD](cicd-pipeline.md), [post-deployment acceptance](post-deployment-acceptance.md), [operations](operations.md), [alert runbook](operational-alert-runbook.md), [drift monitoring](model-drift-monitoring.md) |
| Evaluation | [Evaluation plan](evaluation-plan.md), [agent test workflows](agent-test-workflows.md), [offline test ownership](test-organization.md), [conversational evaluation](../infra/llmsecops/conversational-evaluation.md), [fairness testing](fairness-testing.md), [security scanning](project-security-scan.md) |
| Specialist evaluation | [Spending](spending-agent-evaluation.md), [Budget](budget-agent-evaluation.md), [Goal](goal-agent-evaluation.md), [Investment](investment-agent-evaluation.md), [Investment live evaluation](investment-agent-live-evaluation.md), [Risk & Compliance](risk-compliance-agent-evaluation.md), [Risk & Compliance tests](risk-compliance-agent-tests.md) |
| Design decisions | [MCP/A2A](adr/0001-mcp-a2a-decision.md), [dynamic dependencies](adr/0002-dynamic-agent-dependencies.md), [cross-user access](adr/0003-cross-user-data-access-guardrail.md) |

The [repository README](../README.md), [AI-service guide](../apps/ai-service/README.md),
[AWS guide](../infra/aws/README.md) and [security policy](../SECURITY.md) remain
the setup and service entry points. Approved source documents under
`knowledge/` remain governed runtime content and are retained with their exact
manifest checksums.

The current architecture renders its logical and AWS views in Mermaid, with
matching [logical](../diagrams/financial-coach-logical.mmd) and
[physical](../diagrams/financial-coach-physical.mmd) sources. Outdated raster,
SVG and Excalidraw exports were removed. The current Policy guide explicitly
records that mandatory-source coverage is not rechecked after review sanitization.

## Retained evidence and acceptance limits

| Evidence | Why it remains relevant |
|---|---|
| [Operational evidence register](operational-evidence.md) | Deployment/control history and unresolved current-model failures. AWS Operational Validation now checks infrastructure, edge controls and retention; it does not run live model or load acceptance. |
| [Latest retained v10 browser retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md) | Build `7356713`: 30/34 original turns, case 35 and 6/7 repeats passed. Two withheld and three incomplete answers remain failures. This does not validate subsequent builds. |
| [Pre-recovery v10 report](agent-reasoning-live-test-results-2026-10-09.md) and [root-cause diagnosis](agent-reasoning-live-root-causes-2026-10-09.md) | Original trace evidence still supports the retained local claim recovery and its before/after comparison. |
| [Reasoning prompt catalogue](agent-reasoning-test-prompts-2026-10-07.md) | Reusable synthetic setup and scenario expectations for the retained v10 reports. |
| [AI hardening](ai-security-hardening-2026-10-10.md) and [live findings](evaluation-evidence/ai-security-hardening-live-2026-10-10.md) | Security controls, incomplete live gates and unfavorable findings remain visible. See the risk register for later deployment evidence. |
| [Fairness verification](evaluation-evidence/fairness-verification-2026-10-11.md) | Fixture, blocked live-model and review evidence are retained; objective parity does not establish semantic or representative-user fairness. |
| [Drift activation](evaluation-evidence/model-drift-activation-2026-10-11.json) and [human approval](evaluation-evidence/model-drift-human-review-2026-10-11.json) | Baseline approval, scheduled monitoring and the unresolved grading alert. Earlier candidate/repair records retain distinct failed attempts. |
| [Optional release verification](evaluation-evidence/optional-release-live-verification-2026-10-11.json) | Current opt-in selection, skip/failure handling and rollback contracts; local verification does not establish paid live acceptance. It supersedes the retired mandatory-paid-stage wiring snapshot. |
| [Release split verification](evaluation-evidence/release-job-split-verification-2026-10-11.json) | Historical OIDC preflight failure and trust/readback evidence, distinct from the current optional-stage policy. |
| [Offline ownership verification](evaluation-evidence/test-organization-verification-2026-10-11.json) | Test ownership and execution evidence; its Windows symlink skip and earlier source hashes remain explicit. |
| [Budget browser acceptance](budget-browser-acceptance-20261001.md) | Dated manual UI evidence, scoped to the exercised page revision. |
| [Bedrock restoration](bedrock-kb-restoration-2026-10-09.md) | Ingestion/audit evidence for the retained Education and Policy KBs and corpus pins. |

Companion JSON, screenshots and review CSVs are in
[evaluation-evidence](evaluation-evidence/). They retain their original identities,
counts and failures. A prior-artifact path inside an immutable report is a
historical identifier; older superseded artifacts can be recovered from Git.

## Requirements history and deferred work

The [original Team 9 proposal](<Project Proposal_Team 9.docx>) remains the
requirements source; its Angular/Spring/Bedrock-generation architecture is
historical. Use the current architecture guide for the implementation.
The [account-migration record](aws-account-migration.md) remains a dated cutover
record and migration procedure. [Representative-user validation](representative-user-validation.md)
remains a deferred activation protocol with an explicit model-policy mismatch.
The [Chinese character inventory](chinese-character-inventory.md) is generated
from the current working tree and has a companion JSON inventory.

## Retention rules

Keep current operating/design guidance, assessment references, governance and
approval records, reusable evaluation protocols, and evidence of open failures.
Keep a baseline when it is needed to explain a retained diagnosis or comparison.
Preserve original report bytes and distinguish local, fixture, live and human
review measurements.

Remove completed task plans, superseded implementation notes, partial snapshots
covered by complete reports, and report/JSON/screenshot bundles for retired
contracts when they no longer support current assessment or an open finding.
Update incoming links in the same change. Retired prompt notes, v9 browser
retests, older recovery notes and the obsolete September ERD were removed in
this review. Git retains their original history; the database source of truth
is [the current ORM](../apps/backend/app/infrastructure/models.py) and its migrations.

The assessment manifest remains the authoritative list of required evidence.
Deleting repository copies does not change GitHub Actions artifact retention or
application-data retention. Do not delete governed corpus bytes or unresolved
failure evidence merely because a newer run exists.
