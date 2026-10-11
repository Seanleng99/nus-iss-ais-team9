# Durable decision traces

After authorizing the profile and conversation, the backend creates and commits an orchestration run before dispatching local handlers or calling the AI service. A run belongs to an authorized chat session and does not require an assistant message. Failed requests can leave an empty conversation; questions and answers are appended together only after a validated response.

The private AI endpoint `POST /coach/stream` requires the existing service API key and a backend-generated UUID in `X-Workflow-ID`. It emits newline-delimited JSON decision/model-call events, then one validated response or a content-free error. The public `/api/coach` response remains JSON. The original private `/coach` endpoint remains available to direct clients, while the backend stream paths provide incremental trace delivery. The private `POST /coach/compose/stream` endpoint streams post-action composition using the same service key and `X-Workflow-ID`; composition identity must match the request and response session.

## Retrieve a run

Read `X-Trace-ID` from a successful or AI-unavailable (503) `/api/coach` response, or `audit.trace_id` from a successful response. For persistence errors, find `trace.run.started` / `trace.run.finished` in service logs by `correlation_id`.

Use the existing authenticated endpoint:

```text
GET /api/coach/traces/{trace_id}?user_id={profile_id}
```

It now returns `status`, `correlation_id`, `finished_at`, `error_code`, and a nullable `assistant_message_id`. `audit.durable_events` contains the metadata committed incrementally. Completed runs also retain the existing safety-filtered final audit, agent results, and rationales. Raw prompts, intermediate model answers, and unreviewed rationales are never copied into incremental records.

Events use the shared `coach_trace` schema (`schema_version: 1`) packaged with the existing shared distribution. Producers, backend persistence, and viewer apply the same typed metadata filter. Governed education topics are stored as canonical IDs with spaces replaced by underscores; unknown topics and unreviewed prose are discarded. Legacy events without an explicit schema version remain readable. Unsupported incoming schema versions fail closed.

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

## Decisions and transaction boundaries

- Routing records the initial proposal and every effective override with a rule ID, decision source, and safe before/after state. No model rationale is recorded incrementally.
- Semantic events record synthesis strategy, grounding status, evidence coverage, structured-response correction, contract validation, and decision acceptance or rejection. Provider generation success does not imply that its output passed validation.
- Task queue/start timestamps, per-attempt events, retries and backoff are emitted during execution. The coordinator processes futures as they finish. Execution, queue, dependency wait, and backoff durations are separate metadata fields. Dependency resumes share the same task ID; execution IDs distinguish invocations.
- Review events distinguish the original review, repair eligibility, repair execution, and subsequent review. Incremental coverage uses only question/source/passage identifiers and coverage codes. Supporting quotes and limitations are displayed only from the final approved result.
- Local confirmations and handlers share the run lifecycle, trace response header, and failure retention of orchestrated requests. Backend events record authorization acceptance, selected handler, pending action outcomes, composition, and persistence.

During any transaction containing financial actions, `DurableRun` **buffers** metadata and streamed composition events rather than committing the caller's session. These events commit atomically with the final exchange and action. If that transaction fails or the request is cancelled, it rolls back first, then saves buffered content-free metadata and the failure status. A successful persistence event is saved only with the successful final commit. Pending action outcomes are marked `phase: pending_commit`; they do not establish committed writes on a failed run.

Initial orchestration events still commit incrementally before actions are staged. Buffering preserves action atomicity, but buffered events can be lost in a process crash before final commit or rollback recovery; composition does not claim independent crash durability. The explicit pre-AI checkpoint is the only place buffered preparatory events are flushed before execution. No audit callback commits pending financial writes.

## Access and retention

Existing profile authorization and trace deletion apply to unfinished runs as well. Chat/profile deletion cascades to runs without assistant messages. The normal trace retention period applies. Owner exports include unfinished runs under `data.incomplete_orchestration_traces`.

## Rollout

1. Build the shared package including `coach_trace` and deploy it with all three services. Run `alembic upgrade head` from `apps/backend` (current head `20261010_0018`). Durable runs were introduced by `20260926_0009`, which permits a missing assistant message and adds lifecycle fields/indexes; the later head also includes shared Coach quota tables. The decision-contract and viewer changes add no separate migration.
2. Deploy the AI service with `/coach/stream` and `/coach/compose/stream` before the new backend. Existing backend instances continue to use `/coach` during this transition.
3. Deploy the backend; verify a normal run and a forced AI failure in the target environment, using their trace IDs to compare API records with logs.

No production migration or deployment is performed by the code change itself. Downgrade refuses to discard incomplete runs silently: export and explicitly remove those records first if reverting the schema is necessary.


## Decision trace viewer

Open **Guidance → Decision traces** in the workspace sidebar, or **View decision trace** inside a saved answer's explanation. The viewer uses the active profile's authorization on every request and does not cache trace contents in browser session state.

- Browse recent runs in pages of 25 and filter by run status, including failures without answers.
- Enter a reference ID for a specific run; expired, deleted, or inaccessible records show an unavailable message.
- **Decisions & evidence** shows safe routing proposals/overrides, agent outcomes and timing, reviews/repairs, and question coverage alongside final approved explanations and evidence versions. Blocked runs withhold generated explanations.
- **Timeline** shows saved event order, Singapore timestamps, elapsed time, component/task filters, and event identifiers. Legacy traces fall back to their final audit events.
- **Dependencies** draws recorded requester-to-provider capability edges and lists dependency resolutions. For unfinished runs, edges and resolutions are reconstructed from explicit saved dependency events. Required/optional flags are joined from dependency requests. Missing edges are not inferred from timestamps.
- **Model calls** joins started/finished events by call ID, so failures and unfinished calls remain visible even without a final model-call summary. Generation status, contract validation, decision acceptance/rejection and correction requests are shown separately. Unknown token counts remain blank.
- **Refresh** reloads the run from the backend. Runs still in progress are not automatically polled.

The authenticated list endpoint is `GET /api/coach/traces?user_id=...&status=failed&limit=25&offset=0`. Status is optional; limits are bounded to 1–100. It returns summary `items` and `next_offset`, without audit payloads or agent results. Every page is sorted newest first; refresh returns current database state. The viewer needs the updated backend list endpoint and the existing durable-run migration before frontend rollout. No additional database migration is needed for the viewer.
