# Investment Agent call-chain logging

The application writes method entry logs and existing boundary completion/failure events as JSON to the three services' existing CloudWatch log groups. No additional AWS roles, logging services or database tables are required. The default level is `INFO`; successful health checks do not produce logs. General string processing, attribute access and third-party library internals are not logged line by line.

## Explicit method entry logs

The investment application inventory covers **67 Python modules, with entry logs in all 677 implemented functions/methods across 66 of them**, including shared frontend login/chat, backend authentication and request/history packaging, orchestration, Investment Education, RAG, model calls and Risk & Compliance. Each implementation starts with this call as its first executable statement (after any Python docstring):

```python
def _ground(self, task, sanitized_message):
    log_event("VV entering ", "app.agents.investment_education.InvestmentEducationAgent", "_ground")
    # Existing implementation follows unchanged.
```

All three producers accept `log_event(event, classname=None, methodname=None, *, level=INFO, **fields)`:

- AI service: `apps/ai-service/app/core/telemetry.py`
- Backend: `apps/backend/app/core/telemetry.py`
- Frontend: `apps/frontend/ui/telemetry.py`

The shared contract in `apps/shared/coach_trace/__init__.py` permits **only the exact `"VV entering "` marker**, including its trailing space. The general code/event validator still rejects spaces. `classname` and `methodname` accept bounded, dotted Python identifiers; invalid names and unknown payload fields are dropped. Calls use literal source-code names, never user input, arguments, `self`, model answers or credentials. For module-level functions, `classname` is the module name. For nested functions, `methodname` includes its containing function name. Class names identify the defining class, including when inherited methods execute.

Example JSON fields (timestamps and existing tracing IDs are also emitted):

```json
{"service":"ai-service","event":"VV entering ","classname":"app.agents.investment_education.InvestmentEducationAgent","methodname":"_ground"}
```

No new AWS configuration is needed: the services already send INFO application logs to stdout/stderr and ECS collects them in CloudWatch. `LOG_LEVEL=INFO` must remain enabled for these INFO logs. Startup calls before logging configuration may not be emitted, and constructor calls outside a request have no request correlation ID.

```text
fields @timestamp, service, classname, methodname, correlation_id, trace_id, span_id
| filter event = "VV entering "
| filter correlation_id = "replace-with-request-id"
| sort @timestamp asc
| limit 10000
```

These events reuse the current request and instrumented span context. The `classname`/`methodname` pair identifies the entered implementation; the existing `method`/`caller_method` fields still identify the surrounding instrumented span. Entry logs do not create a new span or prove successful completion. For async/generator functions they fire when the body starts executing; cached function bodies fire only on a cache miss. Shared files also emit entries when used by other agents or pages.

Entry logs go to application/CloudWatch logs, **not** the durable semantic decision-event stream or model prompts. This prevents hundreds of additional audit database writes per answer. Logging internals, request telemetry middleware, low-level trace sinks, health endpoints and unimplemented Protocol declarations are excluded. Test/evaluation/deployment scripts, migrations, third-party frameworks, shared localization/arithmetic library internals and specialist-only budget/goal/spending modules are outside this application-method scope.

See the [complete per-file inventory and exclusions](investment-entry-logging.json). `apps/shared/tests/test_entry_logging.py` checks every inventoried implementation's first statement, literal class/method identity, all three logger APIs and privacy filtering. Existing pipeline/privacy tests also exercise successful education, injected input, provider failures, streaming and saved history.

## Follow one question in CloudWatch

Select **Asia Pacific (Singapore) / ap-southeast-1**, open **Logs Insights / Log Analytics**, and select these log groups together:

- `/ecs/ai-financial-wellness-coach/frontend`
- `/ecs/ai-financial-wellness-coach/backend`
- `/ecs/ai-financial-wellness-coach/ai`

Choose the appropriate time range and find recent responses:

```text
fields @timestamp, service, event, correlation_id, journey_id, trace_id, selected_agents, blocked
| filter event = "coach.response.ready"
| sort @timestamp desc
| limit 20
```

Copy a `correlation_id` to inspect the methods executed for that request:

```text
fields @timestamp, service, event, event_type, method, caller_method, span_id, parent_span_id,
       duration_ms, status_code, agent, component, response_type, selected_agents, blocked, details
| filter correlation_id = "replace-with-request-id"
| sort @timestamp asc
| limit 10000
```

`caller_method → method` represents an **instrumented application call boundary**; framework dispatch may occur between these methods without being expanded. Every invocation gets a new `span_id`; use `parent_span_id` to identify its caller's invocation. Parallel agents interleave, so log order alone does not establish parent-child relationships. `method.completed` means the method returned normally. Check `status_code`, `blocked` and quality-review results separately for HTTP success, safety refusal and answer quality.

## From login to displayed answer

| Stage | Main methods and records | Observable information |
| --- | --- | --- |
| Click login | `ui.auth.require_authenticated_user` → `streamlit.user_info.login` | `auth.login_requested` |
| Return after login | `ui.auth.require_authenticated_user` | `auth.session_authenticated`; creates session `journey_id` |
| Backend signature and ownership checks | `require_principal` → `OidcTokenVerifier.verify` → `enforce_user_access` | Authentication type, acceptance or rejection, method failure type |
| Submit chat | `ui.pages.coach_page` → `client.build_request` → `BackendClient.ask_coach` → `BackendClient._request` | Request ID, sanitized route, question length |
| Prepare backend request | `app.api.routes.coach` → `SQLAlchemyUserRepository.get_financial_snapshot` | Whether a persisted snapshot was found; no amounts or account details |
| Call AI service | `AIServiceClient.coach` → `_stream` → AI middleware → `app.main.coach_stream` | Shared request ID, cross-service parent span, HTTP status |
| Dispatch workflow | `AgentOrchestrator.handle` → `_guard_input` → `_resolve_follow_up` → `_route` → `_run_ready_tasks` → `_execute_task` | Safety checks, selected agents, task IDs, parallel execution, dependencies and retries |
| Investment education | `BaseAgent.run_task` → `InvestmentEducationAgent._ground` → `build_education_context` | Evidence sufficiency, result count, response language |
| Retrieval | `RequestScopedEducationRetriever.retrieve` → `BedrockEducationRetriever.retrieve` → `_retrieve` | Cache hit, knowledge base and version, retrieved/accepted/rejected counts |
| Model response | `generate_structured_response` → `TracingModelGateway.generate` → `OpenAIModelGateway.generate` (OpenAI Responses API) → `parse_structured_response` | Model, calling component, input/output lengths, token counts, response type, validation and correction retries |
| Synthesis | `AgentOrchestrator._synthesize` | `synthesis.strategy` distinguishes direct education-agent answers, clarification questions and model synthesis |
| Independent compliance check | `_review_compliance` → `RiskComplianceAgent.validate` → Policy RAG/model | Independent policy evidence, acceptance or refusal |
| AI response packaging | `_finalize` → validated streamed response; legacy `/coach` also emits AI `coach.response.ready` | `CoachResponse` field names, source count, final status, answer length |
| Backend packaging and persistence | `AIServiceClient.coach` → `CoachResponse.model_validate` → chat/audit repositories → `Session.commit` | Validation, safety filtering, persistence completion, final response structure |
| Read saved answer | `get_chat_session` → `SQLAlchemyChatRepository.get` → `_chat_session_response` → `_message_explanation` | Chat history and explanation packaging, historical-content safety filtering |
| Frontend display | `BackendClient._request` → `ui.pages._render_coach_message` → `_render_coach_explanation` | Response receipt, JSON unpacking, matching `coach.response_rendered` event |

The normal backend path uses `/coach/stream` to persist decision events incrementally; direct clients without an active durable run can still use `/coach`. The backend emits the final `coach.response.ready` event after packaging and persistence.

Model and retrieval calls may be skipped after a safety refusal, insufficient evidence, a cache hit or direct use of a specialist answer. These skips are part of the actual execution path and do not indicate missing logs.

## Four identifiers

- `journey_id`: randomly generated for the Streamlit session after the application observes successful login; links later requests in that session.
- `correlation_id`: identifies one application operation/request; travels through frontend, backend and AI HTTP calls and is returned in response headers.
- `span_id` / `parent_span_id`: identifies a method invocation and its parent invocation.
- `trace_id`: generated independently for each AI workflow; links response audits and workflow events. It is not determined by public client identifiers. The backend generates it before calling AI and passes it through the private `X-Workflow-ID` header.

Cognito and Streamlit implement login redirects. The Streamlit session may be recreated across a redirect, so `auth.login_requested` and the subsequent `journey_id` are not guaranteed to correlate one to one. Logs do not claim to expose Cognito's internal password validation, MFA or token-exchange call stacks. Backend JWT verification is an independently observable check. Reopening the app, logging out or changing identity ends the original session association. Tracing headers are for troubleshooting and never participate in authentication or authorization.

To inspect a whole session after login, replace the request filter with:

```text
| filter journey_id = "replace-with-session-id"
```

## Explicitly marked synthetic tests: view question and answer

Default logs do not record questions, raw model output, final answers, financial snapshots, identity claims, passwords or tokens. With project-owner authorization, **only the backend** can additionally record `coach.synthetic.exchange`, and all these conditions must hold:

1. The backend has verified a separate automation API key; ordinary OIDC users do not qualify.
2. `user_id` uses a synthetic-test prefix allowed by deployment configuration, such as `deployment-`.
3. `APP_ENV` is `local`, `test` or `demo`; other environments do not log raw text.
4. The `/api/coach` request explicitly includes `X-Synthetic-Log: true`.
5. The backend has finished the final answer's safety validation and successfully committed the chat records.

This event contains only the test question and **safety-filtered final answer**. It does not copy system prompts, unvalidated model drafts, financial snapshots or the complete `audit` object into logs. Prefixes and test markers do not prove that input is synthetic; testers must use synthetic questions and profiles. Real user information must never enter this test channel.

```text
fields @timestamp, correlation_id, journey_id, question, answer
| filter event = "coach.synthetic.exchange"
| sort @timestamp desc
| limit 50
```

A Python synthetic-test client can explicitly set `BackendClient(automation_api_key=test_key, synthetic_log=True)`. Read the key from a controlled environment; do not put it in source code, command arguments, screenshots or logs. Ordinary product pages have no raw-text logging switch. Unmarked automation requests, forged markers from ordinary users, failed calls and rejected requests do not produce raw question-and-answer events. A safety refusal that returns normally and is successfully saved records the safe refusal answer, never the blocked model draft.

## Errors and overhead

```text
fields @timestamp, service, correlation_id, method, caller_method, exception_type, error_code, status_code
| filter event = "method.failed" or event = "request_failed" or event_type = "workflow.failed"
| sort @timestamp desc
| limit 100
```

Errors record types and bounded codes, not raw exception text. An offline fixture run of “What are stocks, bonds, mutual funds, and ETFs?” emitted 6,199 entry records (about 3.1 MB) across 142 distinct executed methods. This is a measured local example, not an AWS/live-model volume estimate. Each inventoried implementation adds one entry log per body execution. Existing instrumented boundaries also generate start/completion or failure events. Helpers used per retrieved passage, parallel execution and retries can produce many entries, increasing CloudWatch volume; no per-call parameters are included. CloudWatch uses the existing log-group retention settings. Log access also permits access to synthetic question-and-answer text. Global HTTP/SDK DEBUG logging is disabled, and passwords, cookies, Authorization headers and Cognito callback parameters are not captured. Containers disable duplicate raw Uvicorn access logs; application access logs use route templates without user-specific path parameters.

These logs explain program execution and support troubleshooting. They are not hidden model reasoning and do not prove that financial answers meet a 99% quality target.

## Durable decision records

The backend creates a run record before AI execution and commits filtered decision events incrementally. Requests that fail, time out or never produce a final answer still have queryable run status. See [Durable decision traces](durable-decision-traces.md) for upgrade order, queries, permissions, retention and failure boundaries.
