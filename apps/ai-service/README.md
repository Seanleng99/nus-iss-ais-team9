# FastAPI Multi-Agent AI Service

Private Python API containing the model-driven LangGraph orchestration layer.

## Responsibilities

- Normalize and validate user requests.
- Authenticate backend-to-AI service requests with an independent API key.
- Redact sensitive values before prompts and logs.
- Detect direct and indirect prompt-injection attempts.
- Route requests through OpenAI GPT-6 Luna to one or more specialist agents.
- Resolve typed, capability-based specialist dependencies through the orchestrator.
- Suspend and resume dependent tasks without allowing direct agent-to-agent calls.
- Generate grounded specialist narratives and a final synthesis.
- Ground Investment Education in approved Education sources, quarantine unsafe chunks, and return only validated citations.
- Run independent model-assisted risk and compliance validation.
- Supply Investment Education evidence to Risk and Compliance for independent review.
- Ground Risk and Compliance in a separate approved Policy collection and fail closed without current policy evidence.
- Provide an explicit offline fixture for deterministic control and regression evaluation.

## Dynamic Dependencies

Specialists request capabilities rather than naming or invoking other specialists. The
orchestrator validates each request against the capability registry, reuses an existing result or
schedules its provider, detects cycles, and resumes the requester with only the validated result.

Goal requests `monthly_savings_capacity` for personal funding feasibility, while saved-goal
arithmetic can finish without Budget or income. Budget uses the scoped confirmed savings allocation
when available, otherwise a qualified deterministic baseline with explicit recurring terms. Budget
can request Spending's `transaction_category_totals`: ordinary contextual reasoning makes that
edge optional, while reconciliation requires it. Existing matching providers are reused; otherwise
the orchestrator schedules them. Budget/Goal may additionally request governed `education_context`
through Investment Education's grounding logic. Dependency and task-resumption events appear in
the response audit. See [conditional financial dependencies](../../docs/conditional-financial-dependencies.md).

## Run

```powershell
pip install -e "../shared" -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture"
$env:RAG_PROVIDER="local_fixture"
$env:EDUCATION_CORPUS_VERSION="investment-education-sg@local-fixture-v1"
$env:POLICY_RAG_PROVIDER="local_fixture"
$env:POLICY_CORPUS_VERSION="financial-coach-policy-sg@local-fixture-v1"
uvicorn app.main:app --reload --port 8001
```

For a deployed environment, set `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, `MODEL_REASONING_EFFORT=medium`, and supply `OPENAI_API_KEY` through a secret. AWS release sets `RAG_PROVIDER=bedrock` and `POLICY_RAG_PROVIDER=bedrock`, the separate Knowledge Base IDs and exact corpus pins. The image packages the reviewed documents/manifests for provenance validation. Release synchronizes the approved S3 source objects, ingests both KBs and audits them before activation. Runtime uses Bedrock Retrieve, with provenance, version, freshness and injection checks; Policy retrieval requires all three approved policy sources. Bedrock does not generate the answer. Local live-model runs may instead select both `local_documents` providers with the same manifest pins.
For a local live-model run, place the key in the ignored repository-root `.env` file or the shell environment. The service reads `.env` from either the repository root or `apps/ai-service`; the `OPENAI_API_KEY` entry in `.env.example` must remain blank.
`MODEL_ROLE_OVERRIDES` accepts optional `model_id`, `reasoning_effort`, and `max_tokens` per prompt role. Application defaults load the packaged canonical role policy; environment overrides remain available for explicit experiments. OpenAI receives the typed schema on the initial request; open maps retain local validation and a bounded repair. OpenAI reasoning requests omit temperature, and telemetry reports reasoning usage and distinct failure reasons. See [current orchestration](../../docs/orchestration-current-implementation-2026-10-07.md).

`MAX_MODEL_TOKENS_PER_RUN` defaults to `80000` total input and output tokens across routing, query planning, passage answerability, specialist writing, synthesis and independent policy review. The AWS template and release workflow also set `80000`; the release rejects a stale value in the rendered ECS task. Global defaults are medium reasoning and 3,200 output tokens. Application defaults and release load `apps/ai-service/app/core/model-role-policy.json` and explicitly apply and verify `MODEL_ROLE_OVERRIDES`: Budget/Goal/Spending use medium reasoning with 3,200 output tokens, Education medium with 4,000, and Compliance medium with 3,000. Routing and planning have smaller role-specific limits. Per-role output limits, call counts and deadlines remain enforced; explicit smaller total limits still fail closed when exhausted.

The application loads one packaged [current prompt contract](../../docs/current-prompt-contract.md), designated by `prompts/current/manifest.json`. An optional `PROMPT_SET_VERSION` asserts that identity once during configuration loading; it cannot select another implementation. Every Education model-knowledge topic has a visible label and exact review range. Independent review returns section-specific `blocking_issues`; the server derives eligibility for one owned citation/qualification correction from validated ownership, categories and safety flags. A complete answer can still need a safety correction. Financial defects, prohibited intent and unowned synthesized claims cannot be repaired through Education. Unknown references get one contract correction, then fail closed. See [current orchestration](../../docs/orchestration-current-implementation-2026-10-07.md).

`AGENT_TIMEOUT_SECONDS` defaults to `45` seconds so a specialist can finish several bounded calls for query planning, evidence assessment, writing and contract repair. This configured window also controls whether the workflow can start its single semantic education repair; the corrected draft must pass another independent review. The model read timeout remains `30` seconds per call, and a specialist that exceeds the overall deadline still fails closed. The `openai_local` answerability profile uses the current prompts and pins the current bounded runtime, including role policies. Historical implementations are reproduced from their Git commits.
`WORKFLOW_TIMEOUT_SECONDS` defaults to `85`, `MAX_MODEL_CALLS_PER_RUN` to `20`, `MAX_DEPENDENCY_ROUNDS` to `6` and `MAX_PARALLEL_AGENTS` to `4`. Repair admission forecasts remaining provider time as well as calls/tokens and never extends the original deadline. The effective prompt hash includes the shared currency and fairness instructions; a manifest label alone does not identify the precise instructions used by a run.
The packaged Education corpus is owned by Investment Education. Its
retrieval request contains canonical education topics and validated public search concepts,
with personal values and the raw user question excluded. The current prompts retain fine-grained concepts and a canonical question-intent
hint, explicitly record unsupported topics, and preserves partial-evidence notices through
synthesis. Investment Education first uses retrieved passages and may supplement missing
stable concepts in a separate `general_knowledge` field. The application labels that text as model
knowledge, not verified against retrieved sources, before safety review. It must not contain citations,
current market data, scheme eligibility/limits, tax/legal rules, provider claims or personal advice.
`evidence_status` is `hybrid` or `general_knowledge` when supplements are used. Unsupported topics
remain explicit gaps; retrieval errors or unsafe chunks never enable fallback. Budget and Goal Strategy
education still require RAG evidence, and unavailable policy evidence still blocks every answer.
Final citation markers are validated and links are generated from approved metadata.
Blocked narratives are withheld across the response and backend/UI read boundaries. Compliance receives
its sanitized evidence through the agent result rather than querying the Education corpus, and independently retrieves only from the Policy corpus.
The `/health` endpoint is public. Send `AI_SERVICE_API_KEY` through the `X-API-Key` header when
calling `/coach`.
