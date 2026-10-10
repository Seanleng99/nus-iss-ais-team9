# Investment Agent call-chain logging

The application writes key method entry, completion and failure events as JSON to the three services' existing CloudWatch log groups. No additional AWS roles, logging services or database tables are required. The default level is `INFO`; successful health checks do not produce logs. General string processing, attribute access and third-party library internals are not logged line by line.

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

Errors record types and bounded codes, not raw exception text. Each key method usually generates two log entries plus stage events; parallel execution and retries increase the count. CloudWatch uses the existing log-group retention settings. Log access also permits access to synthetic question-and-answer text. Global HTTP/SDK DEBUG logging is disabled, and passwords, cookies, Authorization headers and Cognito callback parameters are not captured. Containers disable duplicate raw Uvicorn access logs; application access logs use route templates without user-specific path parameters.

These logs explain program execution and support troubleshooting. They are not hidden model reasoning and do not prove that financial answers meet a 99% quality target.

## Durable decision records

The backend creates a run record before AI execution and commits filtered decision events incrementally. Requests that fail, time out or never produce a final answer still have queryable run status. See [Durable decision traces](durable-decision-traces.md) for upgrade order, queries, permissions, retention and failure boundaries.
