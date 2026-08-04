# Requirements Traceability

This matrix maps the module briefing, FAQ, Team 9 proposal, and proposal feedback to repository evidence. `Implemented` means executable behavior exists now. `Scaffolded` means the boundary, contract, or operating procedure exists but still needs a real AWS or model integration. `Planned` is intentionally outside the current skeleton.

| Requirement | Status | Repository evidence | Remaining work before final assessment |
|---|---|---|---|
| Non-deterministic multi-agent system with orchestration | Implemented | LangGraph state machine in `apps/ai-service/app/orchestrator.py`, Bedrock gateway, versioned prompts, five model-assisted roles | Run and retain repeated live-model evaluation evidence before final assessment. |
| Explainability and traceability | Implemented | Agent rationale/confidence, audit trace and timestamp, `docs/responsible-ai.md` | Validate explanations with representative users. |
| Guardrails across agents, tools, and boundaries | Implemented | `core/guardrails.py`, `agents/base.py`, tool allowlist, backend/AI authentication, security evals | Add managed Bedrock Guardrails only after comparing it with application controls. |
| PII and sensitive financial-data handling | Implemented | Input redaction patterns, body-free structured access logs, security tests | Complete a formal privacy review before accepting real customer data. |
| Direct and indirect prompt-injection protection | Implemented | Prompt inspection, RAG sanitization, unit tests, eval dataset, deployment smoke test | Expand adversarial datasets and add model-based attack cases. |
| Defined evaluation data, outputs, metrics, and criteria | Implemented | JSONL datasets, `docs/evaluation-plan.md`, versioned evaluation policy | Expand seed datasets before final evaluation. |
| Data/model behavior drift observation | Implemented | Weekly CI schedule and baseline-regression checks in evaluation policy v2 | Add sanitized production-distribution metrics after production data approval. |
| Logical and physical architecture | Implemented | `docs/architecture.md` | Produce a rendered AWS diagram for the final report if required by the presentation format. |
| Scalability and reliability controls | Scaffolded | Independent ECS services, circuit breakers, health checks, bounded load-smoke script, `docs/operations.md` | Run and retain load results against the AWS demo environment; tune autoscaling from evidence. |
| MLSecOps/LLMSecOps CI/CD | Implemented | GitHub Actions CI/release, CodeQL, dependency review, ECR/Inspector gates, immutable tags, rollback | Configure protected GitHub environment and AWS resources. |
| Monitoring, alerting, logging, auditability | Scaffolded | Correlation-safe JSON access events, audit metadata, CloudWatch plan | Provision dashboards, alarms, retention, and EventBridge notifications in AWS. |
| Model selection and justification | Scaffolded | Bedrock Converse adapter, valid model/profile identifier, `docs/agent-design.md` | Run model quality, latency, cost, and data-residency comparison before fixing the production model. |
| Prompt versioning | Implemented | Executable `apps/ai-service/prompts/v1/prompts.json`, prompt catalog, pull-request gate, audit metadata | Add an approval record for each production prompt release. |
| Agent memory and state | Planned | Request-scoped snapshot contract and backend repository ports | Add consent-aware PostgreSQL persistence, retention, deletion, and session-history controls. |
| Risk and Compliance RAG | Scaffolded | Compliance-only retrieval permission, trusted source IDs, deterministic retriever, document sanitization, retrieval ownership tests and evals | Build offline policy ingestion, provenance manifests, freshness checks, and managed vector persistence. |
| User authentication and permissions | Planned | Separate service credentials and backend security boundary | Replace the demo service key at the public application boundary with OIDC/JWT user authentication before real users. |
| MCP and A2A consideration | Implemented | `docs/adr/0001-mcp-a2a-decision.md` | Revisit only if tools or agents become independently owned services. |

## Release Interpretation

The repository is suitable for source control and a synthetic-data AWS demo after the deployment checklist is completed. It is not approved for real personal financial data, regulated financial advice, or production users. Those transitions require the planned identity, privacy, persistence, model-validation, and operational controls above.
