# Durable decision traces

The backend creates and commits an orchestration run before calling the AI service. A run belongs to an authorized chat session and does not require an assistant message. Failed requests can leave an empty conversation; questions and answers are appended together only after a validated response.

The private AI endpoint `POST /coach/stream` requires the existing service API key and a backend-generated UUID in `X-Workflow-ID`. It emits newline-delimited JSON decision/model-call events, then one validated response or a content-free error. The public `/api/coach` response remains JSON. The original private `/coach` endpoint remains available to direct clients, but only the backend stream path provides incremental database persistence.

## Retrieve a run

Read `X-Trace-ID` from a successful or AI-unavailable (503) `/api/coach` response, or `audit.trace_id` from a successful response. For persistence errors, find `trace.run.started` / `trace.run.finished` in service logs by `correlation_id`.

Use the existing authenticated endpoint:

```text
GET /api/coach/traces/{trace_id}?user_id={profile_id}
```

It now returns `status`, `correlation_id`, `finished_at`, `error_code`, and a nullable `assistant_message_id`. `audit.durable_events` contains the metadata committed incrementally. Completed runs also retain the existing safety-filtered final audit, agent results, and rationales. Raw prompts, intermediate model answers, and unreviewed rationales are never copied into incremental records.

Each event has an `event_id` shared with its operational log. Task IDs and parent-task IDs preserve dependency links. Model calls have a `call_id` and `span_id`; specialist calls also carry `task_id` and `attempt`. Event order is receipt order; use parent links and IDs to interpret parallel activity rather than assuming timestamp order describes causality.

## Run lifecycle and failures

- `running`: run created; events are committed one at a time.
- `completed` / `blocked`: final sanitized answer, chat messages, and run completion commit together.
- `failed`: AI/protocol failure or final persistence failure.
- `timed_out`: AI transport/overall deadline or required-agent timeout.
- `abandoned`: cancellation or a run whose backend deadline plus 60-second persistence grace has elapsed without completion.

Expired running records are reconciled when a trace is retrieved and by the existing trace/data-retention jobs. Abandonment means execution is no longer known to be active; it does not claim the external model call was cancelled. Existing in-flight provider calls may finish after a disconnect, but no new events are accepted by that closed stream.

Earlier committed events survive a later failure. If the database cannot save even the failure status, metadata-only logs record `trace.persistence.failed`; the last committed run remains available and is reconciled after recovery. If initial run creation fails, the AI call does not start. Events still in transit at a process crash are not guaranteed to be saved; this is not an exactly-once delivery system.

The stream uses a bounded 128-frame queue, at most 32 workflow workers per AI process, a backend overall timeout, and a maximum of 2,000 persisted events per run. Duplicate event IDs are ignored. Unsupported content types, malformed frames, mismatched run IDs, and streams ending without a final response fail closed. Each event commit rewrites the bounded JSON event array; a separate append-only event table is a future scaling improvement if run volume grows.

## Access and retention

Existing profile authorization and trace deletion apply to unfinished runs as well. Chat/profile deletion cascades to runs without assistant messages. The normal trace retention period applies. Owner exports include unfinished runs under `data.incomplete_orchestration_traces`.

## Rollout

1. Apply backend Alembic migration `20260926_0009` (`alembic upgrade head` from `apps/backend`). This allows a missing assistant message and adds lifecycle fields/indexes.
2. Deploy the AI service with `/coach/stream` before the new backend. Existing backend instances continue to use `/coach` during this transition.
3. Deploy the backend; verify a normal run and a forced AI failure in the target environment, using their trace IDs to compare API records with logs.

No production migration or deployment is performed by the code change itself. Downgrade refuses to discard incomplete runs silently: export and explicitly remove those records first if reverting the schema is necessary.


## Decision trace viewer

Open **Guidance → Decision traces** in the workspace sidebar, or **View decision trace** inside a saved answer's explanation. The viewer uses the active profile's authorization on every request and does not cache trace contents in browser session state.

- Browse recent runs in pages of 25 and filter by run status, including failures without answers.
- Enter a reference ID for a specific run; expired, deleted, or inaccessible records show an unavailable message.
- **Decisions & evidence** shows the final approved routing and agent explanations and evidence versions. Blocked runs withhold generated explanations.
- **Timeline** shows saved event order, Singapore timestamps, elapsed time, component/task filters, and event identifiers. Legacy traces fall back to their final audit events.
- **Dependencies** draws recorded requester-to-provider capability edges and lists dependency resolutions. Missing edges are not inferred from timestamps.
- **Model calls** joins started/finished events by call ID, so failures and unfinished calls remain visible even without a final model-call summary. Unknown token counts remain blank.
- **Refresh** reloads the run from the backend. Runs still in progress are not automatically polled.

The authenticated list endpoint is `GET /api/coach/traces?user_id=...&status=failed&limit=25&offset=0`. Status is optional; limits are bounded to 1–100. It returns summary `items` and `next_offset`, without audit payloads or agent results. Every page is sorted newest first; refresh returns current database state. The viewer needs the updated backend list endpoint and the existing durable-run migration before frontend rollout. No additional database migration is needed for the viewer.
