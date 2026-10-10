"""Bounded private NDJSON stream; only the final response contains user content."""

import asyncio
import json
from contextvars import copy_context
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Event, Thread

from app.core.run_trace import event_sink, workflow_id
from app.core.telemetry import log_event

# Streaming endpoints must not create an unbounded number of workflow threads.
_workers = BoundedSemaphore(32)


class TraceStreamClosed(RuntimeError):
    pass


async def stream_run(orchestrator, request, trace_id: str, *, operation="coach", timeout_seconds=None):
    log_event("VV entering ", "app.core.trace_stream", "stream_run")
    if not _workers.acquire(blocking=False):
        yield json.dumps({"type": "error", "code": "WORKFLOW_CAPACITY"}) + "\n"
        return
    queue = Queue(maxsize=128)
    closed = Event()

    def send(item):
        log_event("VV entering ", "app.core.trace_stream", "stream_run.send")
        while not closed.is_set():
            try:
                queue.put(item, timeout=0.1)
                return
            except Full:
                continue
        raise TraceStreamClosed("Trace stream closed")

    def work():
        log_event("VV entering ", "app.core.trace_stream", "stream_run.work")
        trace_token = workflow_id.set(trace_id)
        sink_token = event_sink.set(lambda event: send({"type": "event", "event": event}))
        try:
            if operation == "composition":
                from app.core.action_composition import compose_action

                result = compose_action(request, orchestrator)
            else:
                log_event("coach.request.accepted", input_characters=len(request.message))
                result = (orchestrator.handle(request, timeout_seconds=timeout_seconds)
                          if timeout_seconds is not None else orchestrator.handle(request))
            log_event(
                "coach.response.ready",
                trace_id=trace_id,
                selected_agents=[agent.value for agent in result.selected_agents],
                blocked=result.blocked,
                output_characters=len(result.answer),
                source_count=len(result.sources),
                response_fields=list(type(result).model_fields),
            )
            if operation == "coach":
                from app.core.drift import log_observation

                log_observation(request, result)
            send({"type": "response", "response": result.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 - private errors must become content-free frames.
            if not closed.is_set():
                code = getattr(exc, "code", "WORKFLOW_FAILED")
                try:
                    send(
                        {
                            "type": "error",
                            "code": (
                                code if code in {"AGENT_TIMEOUT", "WORKFLOW_TIMEOUT", "OPENAI_TIMEOUT"}
                                else "WORKFLOW_FAILED"
                            ),
                        }
                    )
                except TraceStreamClosed:
                    pass
        finally:
            event_sink.reset(sink_token)
            workflow_id.reset(trace_token)
            _workers.release()

    context = copy_context()
    try:
        Thread(target=context.run, args=(work,), daemon=True, name="trace-stream").start()
    except RuntimeError:
        _workers.release()
        raise
    try:
        while True:
            try:
                item = await asyncio.to_thread(queue.get, True, 0.5)
            except Empty:
                continue
            yield json.dumps(item, separators=(",", ":")) + "\n"
            if item["type"] in {"response", "error"}:
                break
    finally:
        closed.set()
