"""Opt-in private diagnostic files; unreviewed content never enters public traces."""

import json
import os
import re
from pathlib import Path
from time import time, time_ns
from uuid import UUID, uuid4

from app.core.guardrails import redact_sensitive_text
from app.core.run_trace import workflow_id
from app.core.telemetry import log_event


def save_review_diagnostic(directory, draft, sections, verdict, facts):
    if not directory or not (verdict.blocked or getattr(verdict, "complete", True) is False):
        return
    try:
        root = Path(directory).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        files = sorted((p for p in root.glob("review-*.json") if not p.is_symlink()), key=lambda p: p.stat().st_mtime)
        for index, path in enumerate(files):
            if re.fullmatch(r"review-[a-f0-9-]+-\d+\.json", path.name) and (
                path.stat().st_mtime < time() - 86400 or index < len(files) - 127
            ):
                path.unlink()
        payload = {"trace_id": workflow_id.get(), "draft_answer": draft[:16000], "sections": sections,
                   "verdict": verdict.model_dump(mode="json"), "financial_facts": facts}
        text = redact_sensitive_text(json.dumps(payload, ensure_ascii=False))[0]
        try:
            identity = str(UUID(str(workflow_id.get())))
        except (ValueError, TypeError):
            identity = str(uuid4())
        path = root / f"review-{identity}-{time_ns()}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        log_event("review.diagnostic.saved", trace_id=workflow_id.get())
    except OSError:
        log_event("review.diagnostic.unavailable", trace_id=workflow_id.get())
