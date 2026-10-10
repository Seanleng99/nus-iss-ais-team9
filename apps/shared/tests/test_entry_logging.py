"""One contract for all three service loggers and the investment entry inventory."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from coach_trace import (
    ENTRY_EVENT,
    code,
    is_durable_event,
    log_event_name,
    safe_details,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("service,module", [
    ("ai-service", "app.core.telemetry"),
    ("backend", "app.core.telemetry"),
    ("frontend", "ui.telemetry"),
])
def test_three_loggers_accept_entry_signature_and_keep_privacy_contract(service, module):
    script = f'''
from {module} import configure_logging, log_event, trace_context, call_span
configure_logging()
with trace_context(correlation_id="entry-contract"):
    with call_span("app.InvestmentEducationAgent.run_task"):
        log_event("VV entering ", "app.InvestmentEducationAgent", "_ground",
                  input_characters=23, question="PRIVATE_QUESTION", api_key="PRIVATE_KEY",
                  response="PRIVATE_RESPONSE", headers={{"Authorization": "PRIVATE_TOKEN"}})
        log_event("VV entering ", "PRIVATE_EMAIL@example.com", "PRIVATE_METHOD\\nINJECTION")
        log_event("VV entering PRIVATE_EVENT")
        log_event("existing.event", blocked=False, question="PRIVATE_QUESTION")
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT / "apps" / service,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "apps" / service), str(ROOT / "apps/shared")))},
        text=True, capture_output=True, check=True,
    )
    assert "PRIVATE_" not in result.stdout + result.stderr
    records = [json.loads(line) for line in result.stderr.splitlines()]
    entries = [r for r in records if r["event"] == ENTRY_EVENT]
    assert len(entries) == 2
    entry = entries[0]
    assert entry["service"] == service
    assert entry["classname"] == "app.InvestmentEducationAgent"
    assert entry["methodname"] == "_ground"
    assert entry["input_characters"] == 23
    assert entry["correlation_id"] == "entry-contract"
    assert entry["span_id"] and entry["method"] == "app.InvestmentEducationAgent.run_task"
    assert "classname" not in entries[1] and "methodname" not in entries[1]
    assert any(r["event"] == "telemetry.event" for r in records)
    assert any(r["event"] == "existing.event" and r["blocked"] is False for r in records)


def test_entry_marker_does_not_relax_codes_or_fill_durable_audits():
    assert log_event_name(ENTRY_EVENT) == ENTRY_EVENT
    assert code(ENTRY_EVENT) is None
    assert not is_durable_event(ENTRY_EVENT)
    assert safe_details({"classname": "app.Agent", "methodname": "run", "question": "PRIVATE"}) == {
        "classname": "app.Agent", "methodname": "run",
    }
    for value in (None, [], 123, "", "secret@example.com", "a/b", "a\nb", "a " , "a" * 181):
        assert safe_details({"classname": value, "methodname": value}) == {}


def test_every_inventoried_function_starts_with_static_entry_log():
    inventory = json.loads((ROOT / "docs/investment-entry-logging.json").read_text())
    for item in inventory["files"]:
        path = ROOT / item["path"]
        tree = ast.parse(path.read_text())
        exclusions = {entry["method"] for entry in item["excluded_methods"]}
        base = "apps/frontend/" if item["path"].startswith("apps/frontend/") else (
            "apps/ai-service/" if item["path"].startswith("apps/ai-service/") else "apps/backend/"
        )
        module = item["path"].removeprefix(base).removesuffix(".py").replace("/", ".")
        class Entries(ast.NodeVisitor):
            def __init__(self, module, exclusions):
                self.module = module
                self.exclusions = exclusions
                self.entries = []
                self.classes = []
                self.functions = []

            def visit_ClassDef(self, node):
                self.classes.append(node.name)
                self.generic_visit(node)
                self.classes.pop()

            def visit_FunctionDef(self, node):
                owner = ".".join([self.module, *self.classes])
                method = ".".join([*self.functions, node.name])
                if owner + "." + method not in self.exclusions:
                    self.entries.append((node, owner, method))
                self.functions.append(node.name)
                self.generic_visit(node)
                self.functions.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

        visitor = Entries(module, exclusions)
        visitor.visit(tree)
        for node, owner, method in visitor.entries:
            body = node.body
            if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            first = body[0]
            assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), (path, node.name)
            call = first.value
            assert isinstance(call.func, ast.Name) and call.func.id == "log_event", (path, node.name)
            assert len(call.args) == 3 and not call.keywords, (path, node.name)
            assert all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args), (path, node.name)
            assert [a.value for a in call.args] == [ENTRY_EVENT, owner, method], (path, node.name)
            assert safe_details({"classname": owner, "methodname": method}) == {
                "classname": owner, "methodname": method,
            }
        assert len(visitor.entries) == item["method_count"], path
