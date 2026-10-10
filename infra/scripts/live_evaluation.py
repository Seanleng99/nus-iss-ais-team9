import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

MAX_SETUP_TURNS = 6
SYNTHETIC_USER_PATTERN = re.compile(r"live-evaluation-[0-9a-f]{32}")
MAX_SEEDED_TRANSACTIONS = 200
MAX_SEEDED_GOALS = 50


class LiveEndpointError(OSError):
    """Privacy-safe live endpoint failure retained in evaluation evidence."""

    def __init__(self, status_code: int, correlation_id: str | None, trace_id: str | None = None) -> None:
        self.status_code = status_code
        self.correlation_id = correlation_id or "missing"
        self.trace_id = _safe_uuid(trace_id)
        super().__init__(
            f"live endpoint returned HTTP {status_code}; "
            f"correlation_id={self.correlation_id}"
        )


def _safe_uuid(value):
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _safe_error_code(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", value) else None


def require_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("live-evaluation URL must use HTTP(S) and include a host")
    return url


def request_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[dict[str, Any], str | None]:
    request = urllib.request.Request(
        require_http_url(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        # B310 is contained by require_http_url before the request is constructed.
        with urllib.request.urlopen(  # nosec B310
            request,
            timeout=timeout_seconds,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body, response.headers.get("X-Correlation-ID")
    except urllib.error.HTTPError as exc:
        correlation_id = exc.headers.get("X-Correlation-ID") if exc.headers else None
        trace_id = exc.headers.get("X-Trace-ID") if exc.headers else None
        raise LiveEndpointError(exc.code, correlation_id, trace_id) from exc


def chat_session_delete_url(url: str, user_id: str, session_id: str) -> str:
    parsed = urllib.parse.urlparse(require_http_url(url))
    coach_path = parsed.path.rstrip("/")
    if not coach_path.endswith("/coach"):
        raise ValueError("live-evaluation URL path must end with /coach")
    api_path = coach_path[: -len("/coach")]
    delete_path = (
        f"{api_path}/users/{urllib.parse.quote(user_id, safe='')}"
        f"/chat-sessions/{urllib.parse.quote(session_id, safe='')}"
    )
    return urllib.parse.urlunparse(
        parsed._replace(path=delete_path, query="", fragment="")
    )


def cleanup_session(
    url: str,
    api_key: str,
    user_id: str,
    session_id: str,
    timeout_seconds: float,
) -> bool:
    request = urllib.request.Request(
        chat_session_delete_url(url, user_id, session_id),
        headers={"Accept": "application/json", "X-API-Key": api_key},
        method="DELETE",
    )
    try:
        # B310 is contained by require_http_url in chat_session_delete_url.
        with urllib.request.urlopen(  # nosec B310
            request, timeout=timeout_seconds
        ) as response:
            response.read()
            return response.status == 204
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except (OSError, ValueError):
        return False


def owned_api_url(url: str, suffix: str) -> str:
    parsed = urllib.parse.urlparse(require_http_url(url))
    path = parsed.path.rstrip("/")
    if not path.endswith("/coach"):
        raise ValueError("live-evaluation URL path must end with /coach")
    return urllib.parse.urlunparse(parsed._replace(path=path[:-6] + suffix, query="", fragment=""))


def _owned_api_request_json(url, api_key, method, payload, timeout_seconds):
    request = urllib.request.Request(
        require_http_url(url),
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Accept": "application/json", "Content-Type": "application/json", "X-API-Key": api_key},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else {}
    except urllib.error.HTTPError as exc:
        correlation_id = exc.headers.get("X-Correlation-ID") if exc.headers else None
        trace_id = exc.headers.get("X-Trace-ID") if exc.headers else None
        raise LiveEndpointError(exc.code, correlation_id, trace_id) from exc


def failed_turn_usage(url, api_key, user_id, session_id, trace_id, timeout_seconds):
    """Reduce an owned failed trace to usage metadata before deleting its actor."""
    trace_id = _safe_uuid(trace_id)
    if not trace_id or not SYNTHETIC_USER_PATTERN.fullmatch(user_id):
        return None
    query = urllib.parse.urlencode({"user_id": user_id})
    trace_url = owned_api_url(url, f"/coach/traces/{trace_id}") + "?" + query
    try:
        trace = _owned_api_request_json(trace_url, api_key, "GET", None, timeout_seconds)
        if (not isinstance(trace, dict) or _safe_uuid(trace.get("trace_id")) != trace_id
                or trace.get("session_id") != session_id or not isinstance(trace.get("audit"), dict)):
            return None
        events = trace["audit"].get("durable_events")
        if not isinstance(events, list) or len(events) > 2000:
            return None
        started = set()
        finished = defaultdict(list)
        malformed = False
        error_codes = set()
        backend_error = _safe_error_code(trace.get("error_code"))
        workflow_error = None
        if backend_error:
            error_codes.add(backend_error)
        for event in events:
            if not isinstance(event, dict):
                malformed = True
                continue
            event_type = event.get("event_type")
            if event_type not in {"model.generation.started", "model.generation.finished", "workflow.failed"}:
                continue
            details = event.get("details")
            if _safe_uuid(event.get("trace_id")) != trace_id or not isinstance(details, dict):
                malformed = True
                continue
            code = _safe_error_code(details.get("error_code"))
            if code:
                error_codes.add(code)
                if event_type == "workflow.failed":
                    workflow_error = code
            if event_type == "workflow.failed":
                continue
            call_id = _safe_uuid(details.get("call_id"))
            if not call_id:
                malformed = True
                continue
            if event_type == "model.generation.started":
                started.add(call_id)
            else:
                # Replayed identical metadata must not count or charge twice.
                completion = {key: details.get(key) for key in ("status", "input_tokens", "output_tokens")}
                completion["error_code"] = code
                if completion not in finished[call_id]:
                    finished[call_id].append(completion)
        call_ids = started | finished.keys()
        input_tokens = output_tokens = completed_calls = 0
        known_paired_calls = 0
        for call_id in call_ids:
            endings = finished.get(call_id, [])
            if len(endings) != 1:
                continue
            completion = endings[0]
            if (completion["status"] != "completed" or completion["error_code"] is not None
                    or any(type(completion[key]) is not int or completion[key] < 0
                           for key in ("input_tokens", "output_tokens"))):
                continue
            input_tokens += completion["input_tokens"]
            output_tokens += completion["output_tokens"]
            completed_calls += 1
            if call_id in started:
                known_paired_calls += 1
        complete = (bool(call_ids) and not malformed and known_paired_calls == len(call_ids)
                    and trace.get("status") in {"failed", "timed_out", "abandoned", "completed", "blocked"})
        return {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "model_call_count": len(call_ids), "completed_model_call_count": completed_calls,
            "model_call_ids": sorted(call_ids), "token_usage_complete": complete,
            "error_code": workflow_error or backend_error or next(iter(sorted(error_codes)), None),
            "error_codes": sorted(error_codes),
        }
    except (OSError, TypeError, ValueError, KeyError):
        return None


def _fixture_payloads(snapshot):
    """Persist explicit fixture facts, deduplicating overlapping snapshot views."""
    if not isinstance(snapshot, dict) or len(json.dumps(snapshot)) > 100_000:
        raise ValueError("snapshot fixtures must be bounded objects")
    profile = {key: snapshot[key] for key in ("monthly_income", "risk_tolerance", "preferences") if key in snapshot}
    if "preferences" in profile and (not isinstance(profile["preferences"], dict) or len(profile["preferences"]) > 50):
        raise ValueError("snapshot preferences must have at most 50 entries")
    records = {}
    for view in ("recent_transactions", "historical_transactions", "recurring_expenses"):
        items = snapshot.get(view, [])
        if not isinstance(items, list) or len(items) > MAX_SEEDED_TRANSACTIONS:
            raise ValueError("snapshot transaction views must contain at most 200 records")
        counts = defaultdict(int)
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("snapshot transactions must be objects")
            payload = {key: item[key] for key in ("description", "category", "amount", "occurred_on", "recurring", "transaction_type", "recurrence", "obligation_id") if key in item}
            if view == "recurring_expenses":
                payload["recurring"] = True
            if any(key not in payload for key in ("description", "category", "amount", "occurred_on")):
                raise ValueError("fixture records require their explicit description, category, amount and date")
            identity = json.dumps({key: payload.get(key) for key in ("description", "category", "amount", "occurred_on", "transaction_type", "recurrence", "obligation_id")}, sort_keys=True)
            counts[identity] += 1
            ordinal = counts[identity] - 1
            prior = records.setdefault(identity, [])
            if ordinal >= len(prior):
                prior.append(payload)
            else:
                prior[ordinal]["recurring"] = prior[ordinal].get("recurring", False) or payload.get("recurring", False)
    transactions = [payload.copy() for rows in records.values() for payload in rows]
    goals = snapshot.get("goals", [])
    if len(transactions) > MAX_SEEDED_TRANSACTIONS or not isinstance(goals, list) or len(goals) > MAX_SEEDED_GOALS:
        raise ValueError("a fixture may seed at most 200 transactions and 50 goals")
    goal_payloads = []
    for goal in goals:
        if not isinstance(goal, dict) or any(key not in goal for key in ("name", "target_amount", "target_months")):
            raise ValueError("fixture goals require explicit name, target amount and duration")
        goal_payloads.append({key: goal[key] for key in ("name", "target_amount", "current_amount", "target_months") if key in goal})
    return profile, transactions, goal_payloads


def seed_case_snapshot(url, api_key, user_id, snapshot, timeout_seconds):
    if not SYNTHETIC_USER_PATTERN.fullmatch(user_id):
        raise ValueError("Only a freshly generated evaluation actor may be seeded")
    profile, transactions, goals = _fixture_payloads(snapshot)
    _owned_api_request_json(owned_api_url(url, "/profiles"), api_key, "POST",
                            {"user_id": user_id, **profile}, timeout_seconds)
    obligation_ids = {}
    transactions.sort(key=lambda item: item["occurred_on"])
    for collection, items in (("transactions", transactions), ("goals", goals)):
        for payload in items:
            original_id = payload.pop("obligation_id", None) if collection == "transactions" else None
            if original_id in obligation_ids:
                payload["obligation_id"] = obligation_ids[original_id]
            result = _owned_api_request_json(owned_api_url(url, f"/users/{user_id}/{collection}"),
                                             api_key, "POST", payload, timeout_seconds)
            if original_id and result.get("obligation_id"):
                obligation_ids[original_id] = result["obligation_id"]
    return {"transactions": len(transactions), "goals": len(goals)}


def cleanup_user_data(url, api_key, user_id, timeout_seconds):
    """Delete only this run's generated actor, with the server's reviewed policy."""
    if not SYNTHETIC_USER_PATTERN.fullmatch(user_id):
        return False
    try:
        policy = _owned_api_request_json(owned_api_url(url, f"/users/{user_id}/data-lifecycle"),
                                         api_key, "GET", None, timeout_seconds)
        version = policy.get("policy_version")
        if not isinstance(version, str) or not version:
            return False
        _owned_api_request_json(owned_api_url(url, f"/users/{user_id}/data"), api_key, "DELETE",
                                {"confirm_user_id": user_id, "policy_version": version}, timeout_seconds)
        return True
    except LiveEndpointError as error:
        return error.status_code == 404
    except (OSError, ValueError):
        return False


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            if (
                not case.get("id")
                or not case.get("category")
                or not case.get("request")
            ):
                raise ValueError(f"invalid live evaluation case at line {line_number}")
            _case_turns(case)
            cases.append(case)
    if not cases:
        raise ValueError("live evaluation dataset is empty")
    return cases


def _case_turns(case: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Bound setup requests and keep their results in the same synthetic session."""
    setup = case.get("setup_turns", [])
    if not isinstance(setup, list) or len(setup) > MAX_SETUP_TURNS:
        raise ValueError("setup_turns must contain at most six requests")
    turns = []
    for item in setup:
        if not isinstance(item, dict):
            raise TypeError("each setup turn must be a request object")
        request = item.get("request", item)
        expected = item.get("expected", {"blocked": False})
        if not isinstance(request, dict) or not isinstance(expected, dict):
            raise TypeError("setup turn requests and expectations must be objects")
        turns.append((request, expected))
    turns.append((case["request"], case.get("expected", {})))
    for request, expected in turns:
        message = request.get("message") if isinstance(request, dict) else None
        if not isinstance(message, str) or not message.strip() or len(message) > 5000:
            raise ValueError("each evaluation turn requires a 1-5000 character message")
        if not isinstance(expected, dict):
            raise TypeError("evaluation expectations must be objects")
    return turns


def _agent_data(response: dict[str, Any], agent: str) -> dict[str, Any]:
    for result in response.get("agent_results", []):
        if result.get("agent") == agent:
            data = result.get("data", {})
            return data if isinstance(data, dict) else {}
    return {}


def _policy_findings(response: dict[str, Any]) -> list[str]:
    return [
        str(finding)
        for result in response.get("agent_results", [])
        for finding in result.get("policy_notes", [])
    ]


def _same_decimal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        value, target = Decimal(str(actual)), Decimal(str(expected))
    except (InvalidOperation, ValueError):
        return False
    return value.is_finite() and target.is_finite() and value == target


def _answer_has_amount(answer: str, currency: str, amount: Any) -> bool:
    # Decimal equality permits normal thousands formatting without accepting
    # substrings of a different amount or silently changing its currency.
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(currency)}\s*([+-]?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)"
        r"(?:\.\d{1,2})?)(?!\d|[,.]\d)", re.IGNORECASE,
    )
    matches = list(pattern.finditer(answer))
    aliases_path = Path(__file__).resolve().parents[2] / "apps/shared/coach_i18n/data/currency_aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    for alias in aliases.get(currency, []):
        numeric = r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?!\d|[,.]\d)"
        for localized in (rf"{re.escape(alias)}\s*{numeric}", rf"(?<![\d.,]){numeric}\s*{re.escape(alias)}"):
            matches.extend(re.finditer(localized, answer))
    return any(_same_decimal(match.group(1).replace(",", ""), amount) for match in matches)


def evaluate_response(
    response: dict[str, Any],
    expected: dict[str, Any],
    *,
    expected_model_provider: str,
    expected_model_id: str,
    expected_prompt_version: str,
) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool) -> None:
        checks.append({"check": name, "passed": bool(passed)})

    if "required_model_components" in expected:
        calls = response.get("audit", {}).get("model_calls", [])
        for component in expected["required_model_components"]:
            add_check("real_model." + component, any(
                call.get("component") == component and call.get("model_id") == expected_model_id
                and call.get("status") == "completed" and call.get("error_code") is None
                and type(call.get("output_characters")) is int and call["output_characters"] > 0
                and type(call.get("input_tokens")) is int and call["input_tokens"] > 0
                and type(call.get("output_tokens")) is int and call["output_tokens"] > 0
                for call in calls))
    for agent, fields in expected.get("agent_data", {}).items():
        data = _agent_data(response, agent)
        for field, value in fields.items():
            actual = data
            for key in field.split("."):
                if isinstance(actual, list) and key.isdigit():
                    actual = actual[int(key)] if int(key) < len(actual) else None
                else:
                    actual = actual.get(key) if isinstance(actual, dict) else None
            add_check("agent_data." + agent + "." + field, actual == value)
    if "answer_status" in expected:
        add_check("answer_status", response.get("audit", {}).get("answer_status") == expected["answer_status"])
    if "budget_draft" in expected:
        draft = _agent_data(response, "budget").get("budget_draft")
        add_check("budget_draft_present", isinstance(draft, dict))
        if isinstance(draft, dict):
            for field, value in expected["budget_draft"].items():
                actual = draft
                for key in field.split("."):
                    actual = actual.get(key) if isinstance(actual, dict) else None
                add_check("budget_draft." + field, actual == value)
        else:
            add_check("budget_draft_fields", False)
    if "budget_categories" in expected:
        draft = _agent_data(response, "budget").get("budget_draft") or {}
        categories = draft.get("categories") or []
        actual = {
            " ".join(str(item.get("category") or "").split()).lower(): item.get(
                "limit_amount"
            )
            for item in categories
        }
        add_check(
            "budget_categories",
            actual == expected["budget_categories"] and len(categories) == len(actual),
        )
    if "budget_capture" in expected:
        add_check(
            "budget_capture",
            response.get("audit", {}).get("budget_capture")
            == expected["budget_capture"],
        )
    if "answer_contains" in expected:
        answer = response.get("answer", "").casefold()
        add_check(
            "answer_contains",
            all(term.casefold() in answer for term in expected["answer_contains"]),
        )
    if "answer_excludes" in expected:
        answer = response.get("answer", "").casefold()
        add_check(
            "answer_excludes",
            all(term.casefold() not in answer for term in expected["answer_excludes"]),
        )
    if "answer_amounts" in expected:
        add_check("answer_amounts", all(
            _answer_has_amount(response.get("answer", ""), item["currency"], item["amount"])
            for item in expected["answer_amounts"]
        ))
    if "action_status" in expected:
        audit = response.get("audit", {})
        allowed = expected["action_status"]
        allowed = allowed if isinstance(allowed, list) else [allowed]
        status = audit.get("action_status")
        add_check("action_status", isinstance(status, str) and status in allowed and any(
            isinstance(outcome, dict) and outcome.get("authority") == "authenticated_backend"
            and outcome.get("status") == status
            for outcome in audit.get("backend_outcomes", [])
        ))
    if "recurring_forecast" in expected:
        audit = response.get("audit", {})
        forecast = audit.get("recurring_forecast")
        add_check("recurring_forecast_source", audit.get("source") == "recurring_forecast"
                  and audit.get("forecast_available") is True)
        for field, value in expected["recurring_forecast"].items():
            actual = forecast.get(field) if isinstance(forecast, dict) else None
            add_check("recurring_forecast." + field,
                      _same_decimal(actual, value) if field == "total"
                      else type(actual) is type(value) and actual == value)
    if "maximum_answer_words" in expected:
        add_check(
            "maximum_answer_words",
            len(response.get("answer", "").split()) <= int(expected["maximum_answer_words"]),
        )
    if "answer_language" in expected:
        answer = response.get("answer", "")
        scripts_path = Path(__file__).resolve().parents[2] / "apps/shared/coach_i18n/data/scripts.json"
        scripts = json.loads(scripts_path.read_text(encoding="utf-8"))
        chinese = len(re.findall(scripts["han_basic"], answer))
        latin = len(re.findall(r"[A-Za-z]", answer))
        language = expected["answer_language"]
        add_check(
            "answer_language",
            (language == "Chinese" and chinese >= 2)
            or (language == "English" and latin >= 10 and chinese == 0),
        )
    if "no_draft" in expected or "draft_present" in expected:
        draft_present = any(
            (result.get("data") or {}).get(field)
            for result in response.get("agent_results", [])
            for field in ("goal_draft", "budget_draft", "spending_draft", "transaction_draft")
        )
        audit = response.get("audit", {})
        draft_present = draft_present or any(
            audit.get(field) for field in ("goal_capture", "budget_capture", "spending_capture")
        )
        if "no_draft" in expected:
            add_check("no_draft", bool(not draft_present) is expected["no_draft"])
        if "draft_present" in expected:
            add_check("draft_present", bool(draft_present) is expected["draft_present"])
    if "blocked" in expected:
        add_check("blocked", response.get("blocked") is expected["blocked"])
    if "selected_agents" in expected:
        add_check(
            "selected_agents",
            response.get("selected_agents", []) == expected["selected_agents"],
        )
    if "forbidden_agents" in expected:
        add_check(
            "forbidden_agents",
            set(response.get("selected_agents", [])).isdisjoint(
                expected["forbidden_agents"]
            ),
        )
    if "dependency_capabilities" in expected:
        actual = {
            item.get("capability")
            for item in response.get("audit", {}).get("dependency_resolutions", [])
            if item.get("resolution") in {"scheduled", "resolved", "reused"}
        }
        add_check(
            "dependency_capabilities",
            set(expected["dependency_capabilities"]) == actual,
        )
    if "needs_input_agents" in expected:
        actual = {
            item.get("agent")
            for item in response.get("agent_results", [])
            if item.get("data", {}).get("needs_input") is True
        }
        add_check("needs_input_agents", actual == set(expected["needs_input_agents"]))
    if "minimum_sources" in expected:
        add_check(
            "minimum_sources",
            len(response.get("sources", [])) >= int(expected["minimum_sources"]),
        )
    if "maximum_sources" in expected:
        add_check(
            "maximum_sources",
            len(response.get("sources", [])) <= int(expected["maximum_sources"]),
        )
    if expected.get("source_provenance") is True:
        sources = response.get("sources", [])
        required = {
            "source_id",
            "title",
            "issuing_organization",
            "canonical_url",
            "published_at",
            "document_version",
            "checksum",
            "corpus_version",
            "review_due_at",
        }
        add_check(
            "source_provenance",
            bool(sources)
            and all(
                required.issubset(source)
                and all(source.get(field) for field in required)
                and str(source.get("checksum", "")).startswith("sha256:")
                for source in sources
            ),
        )
    if expected.get("policy_source_provenance") is True:
        policy_sources = response.get("audit", {}).get("policy_sources", [])
        required = {
            "source_id",
            "title",
            "issuing_organization",
            "canonical_url",
            "published_at",
            "document_version",
            "checksum",
            "corpus_version",
            "review_due_at",
        }
        add_check(
            "policy_source_provenance",
            bool(policy_sources)
            and all(
                required.issubset(source)
                and all(source.get(field) for field in required)
                and str(source.get("checksum", "")).startswith("sha256:")
                for source in policy_sources
            ),
        )
    if "evidence_status" in expected:
        evidence_agent = expected.get("evidence_agent", "investment_education")
        add_check(
            "evidence_status",
            _agent_data(response, evidence_agent).get("evidence_status")
            == expected["evidence_status"],
        )
    if "policy_finding_prefixes" in expected:
        findings = _policy_findings(response)
        add_check(
            "policy_finding_prefixes",
            all(
                any(finding.startswith(prefix) for finding in findings)
                for prefix in expected["policy_finding_prefixes"]
            ),
        )
    if "guardrail_finding_prefixes" in expected:
        findings = response.get("audit", {}).get("guardrail_findings", [])
        add_check(
            "guardrail_finding_prefixes",
            all(
                any(str(finding).startswith(prefix) for finding in findings)
                for prefix in expected["guardrail_finding_prefixes"]
            ),
        )
    if "minimum_disclaimers" in expected:
        add_check(
            "minimum_disclaimers",
            len(response.get("disclaimers", []))
            >= int(expected["minimum_disclaimers"]),
        )

    audit = response.get("audit", {})
    if "retrieval_corpus_version" in expected:
        expected_corpus = str(expected["retrieval_corpus_version"])
        add_check(
            "retrieval_corpus_version",
            audit.get("retrieval_corpus_versions") == [expected_corpus]
            and all(
                source.get("corpus_version") == expected_corpus
                for source in response.get("sources", [])
            ),
        )
    if "policy_corpus_version" in expected:
        expected_policy_corpus = str(expected["policy_corpus_version"])
        add_check(
            "policy_corpus_version",
            audit.get("policy_corpus_versions") == [expected_policy_corpus]
            and all(
                source.get("corpus_version") == expected_policy_corpus
                for source in audit.get("policy_sources", [])
            ),
        )
    if (audit.get("model_provider") is not None or response.get("selected_agents")
            or "minimum_model_calls" in expected or "maximum_model_calls" in expected):
        add_check(
            "model_provider",
            audit.get("model_provider") == expected_model_provider,
        )
        add_check("model_id", audit.get("model_id") == expected_model_id)
        add_check(
            "prompt_set_version",
            audit.get("prompt_set_version") == expected_prompt_version,
        )
        policy_prefixes = expected.get("policy_finding_prefixes", [])
        policy_findings = _policy_findings(response)
        guard_prefixes = expected.get("guardrail_finding_prefixes", [])
        guard_findings = audit.get("guardrail_findings", [])
        input_guard_evidence = (
            expected.get("deterministic_input_guard") is True
            and bool(guard_prefixes)
            and _safe_uuid(audit.get("trace_id")) is not None
            and all(prefix and any(str(finding).startswith(prefix) for finding in guard_findings)
                    for prefix in guard_prefixes)
            and any(isinstance(event, dict) and event.get("event_type") == "guardrail.evaluated"
                    and event.get("actor") == "orchestrator"
                    and event.get("trace_id") == audit.get("trace_id")
                    and event.get("details", {}).get("allowed") is False
                    and type(event.get("details", {}).get("finding_count")) is int
                    and event["details"]["finding_count"] > 0
                    for event in audit.get("events", []))
            and any(isinstance(event, dict) and event.get("event_type") == "workflow.completed"
                    and event.get("trace_id") == audit.get("trace_id")
                    and event.get("details", {}).get("reason_code") == "BOUNDARY_GUARDRAIL"
                    for event in audit.get("events", []))
        )
        deterministic_safety_evidence = (
            expected.get("blocked") is True
            and response.get("blocked") is True
            and (input_guard_evidence or (bool(policy_prefixes) and all(
                prefix
                and any(finding.startswith(prefix) for finding in policy_findings)
                for prefix in policy_prefixes
            )))
            and audit.get("model_calls") == []
            and type(audit.get("model_call_count")) is int
            and audit["model_call_count"] == 0
        )
        add_check(
            "model_execution_or_deterministic_safety_evidence",
            bool(audit.get("model_calls")) or deterministic_safety_evidence,
        )
        if "minimum_model_calls" in expected:
            add_check(
                "minimum_model_calls",
                int(audit.get("model_call_count") or 0)
                >= int(expected["minimum_model_calls"]),
            )
        if "maximum_model_calls" in expected:
            add_check(
                "maximum_model_calls",
                int(audit.get("model_call_count") or 0)
                <= int(expected["maximum_model_calls"]),
            )
    return all(item["passed"] for item in checks), checks


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * percentile) - 1, 0)
    return round(ordered[index], 2)


def run_live_evaluation(
    *,
    url: str,
    api_key: str,
    cases: list[dict[str, Any]],
    repeats: int,
    timeout_seconds: float,
    expected_model_provider: str,
    expected_model_id: str,
    expected_prompt_version: str,
    input_cost_per_million: float,
    output_cost_per_million: float,
    commit_sha: str,
    maximum_estimated_cost_usd: float | None = None,
    maximum_total_tokens: int | None = None,
    capture_synthetic_dialogue: bool = False,
    response_checks: Callable[[dict, dict], list[dict]] | None = None,
    response_observer: Callable | None = None,
    observer_stopped: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if maximum_total_tokens is not None and maximum_total_tokens < 1:
        raise ValueError("maximum_total_tokens must be positive")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if not cases:
        raise ValueError("live evaluation dataset is empty")
    # Reject an oversized conversation before any endpoint calls or charges.
    case_turns = [_case_turns(case) for case in cases]
    target = urllib.parse.urlparse(require_http_url(url))
    records: list[dict[str, Any]] = []
    category_results: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    latencies: list[float] = []
    total_input_tokens = 0
    total_output_tokens = 0
    spending_stopped = False
    usage_unknown = False

    def cannot_start_turn():
        estimated = (total_input_tokens * input_cost_per_million
                     + total_output_tokens * output_cost_per_million) / 1_000_000
        return (usage_unknown
                or (observer_stopped is not None and observer_stopped())
                or (maximum_estimated_cost_usd is not None and estimated >= maximum_estimated_cost_usd)
                or (maximum_total_tokens is not None
                    and total_input_tokens + total_output_tokens >= maximum_total_tokens))

    for repeat in range(1, repeats + 1):
        for case, turns in zip(cases, case_turns, strict=True):
            if cannot_start_turn():
                spending_stopped = True
                break
            session_id = f"live-{case['id'][:48]}-{repeat}-{uuid4().hex[:10]}"
            synthetic_user_id = "live-evaluation-" + uuid4().hex
            started = time.perf_counter()
            record: dict[str, Any] = {
                "case_id": case["id"],
                "category": case["category"],
                "repeat": repeat,
                "passed": True,
                "checks": [],
                "turns": [],
                "setup_turn_count": len(turns) - 1,
                "input_tokens": 0,
                "output_tokens": 0,
                "model_call_count": 0,
                "token_usage_complete": True,
                "rubric_review": "required" if case.get("rubric") else "not_requested",
            }
            active_turn_index = None
            observer_duration = 0.0
            try:
                # The authenticated backend snapshot overrides request snapshots
                # after a profile exists. Seed its owned source records once,
                # then preserve the same actor throughout this conversation.
                snapshots = [request.get("snapshot", {}) for request, _ in turns if request.get("snapshot")]
                fixture = snapshots[0] if snapshots else {}
                if any(snapshot != fixture for snapshot in snapshots[1:]):
                    raise ValueError("A conversation fixture must use one consistent starting snapshot")
                record["seeded_records"] = seed_case_snapshot(url, api_key, synthetic_user_id, fixture, timeout_seconds)
                record["fixture_seed_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                started = time.perf_counter()
                for turn_index, (request, expected) in enumerate(turns):
                    if cannot_start_turn():
                        spending_stopped = True
                        record["passed"] = False
                        record["checks"].append({"check": "spending_budget_available", "passed": False})
                        break
                    payload = json.loads(json.dumps(request))
                    payload["user_id"] = synthetic_user_id
                    payload["session_id"] = session_id
                    turn_started = time.perf_counter()
                    active_turn_index = turn_index
                    response, correlation_id = request_json(
                        url, api_key, payload, timeout_seconds,
                    )
                    audit = response.get("audit", {})
                    if audit.get("composition_usage_complete") is False:
                        record["token_usage_complete"] = False
                        record["composition_usage_complete"] = False
                        record["composition_fallback_code"] = _safe_error_code(audit.get("composition_fallback_code"))
                    if audit.get("model_call_count") and not {
                        "model_input_tokens", "model_output_tokens",
                    }.issubset(audit):
                        record["token_usage_complete"] = False
                    if (expected_model_provider != "local_fixture" and audit.get("model_call_count")
                            and any(not isinstance(call.get(field), int)
                                    for call in audit.get("model_calls", [])
                                    for field in ("input_tokens", "output_tokens"))):
                        record["token_usage_complete"] = False
                    if maximum_total_tokens is not None:
                        calls = audit.get("model_calls", [])
                        consistent = (type(audit.get("model_call_count")) is int
                                      and audit["model_call_count"] == len(calls)
                                      and all(type(call.get(key)) is int and call[key] >= 0
                                              for call in calls for key in ("input_tokens", "output_tokens"))
                                      and all(audit.get("model_" + key) == sum(call.get(key) or 0 for call in calls)
                                              for key in ("input_tokens", "output_tokens")))
                        record["token_usage_complete"] = record["token_usage_complete"] and consistent
                    input_tokens = int(audit.get("model_input_tokens") or 0)
                    output_tokens = int(audit.get("model_output_tokens") or 0)
                    total_input_tokens += input_tokens
                    total_output_tokens += output_tokens
                    record["input_tokens"] += input_tokens
                    record["output_tokens"] += output_tokens
                    call_count = int(audit.get("model_call_count") or 0)
                    record["model_call_count"] += call_count
                    passed, checks = evaluate_response(
                        response, expected,
                        expected_model_provider=expected_model_provider,
                        expected_model_id=expected_model_id,
                        expected_prompt_version=expected_prompt_version,
                    )
                    has_answer = isinstance(response.get("answer"), str) and bool(response["answer"].strip())
                    checks.append({"check": "nonempty_answer", "passed": has_answer})
                    if response_checks is not None:
                        checks.extend(response_checks(response, expected))
                    passed = bool(passed and has_answer and all(item["passed"] for item in checks))
                    prefix = f"setup[{turn_index}]." if turn_index < len(turns) - 1 else ""
                    record["checks"].extend(
                        {"check": prefix + check["check"], "passed": check["passed"]}
                        for check in checks
                    )
                    record["turns"].append({
                        "turn_index": turn_index,
                        "is_setup": turn_index < len(turns) - 1,
                        "passed": passed,
                        "latency_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                        "correlation_id": correlation_id,
                        "trace_id": audit.get("trace_id"),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "model_call_count": call_count,
                        "token_usage_complete": record["token_usage_complete"],
                    })
                    if capture_synthetic_dialogue:
                        # Opt-in only for reviewed synthetic datasets; legacy callers retain metadata only.
                        record["turns"][-1].update({
                            "question": request["message"], "expected": expected,
                            "answer": response.get("answer"), "checks": checks,
                            "selected_agents": response.get("selected_agents", []),
                            "sources": response.get("sources", []),
                            "agent_results": response.get("agent_results", []),
                            "model_calls": [{key: call.get(key) for key in (
                                "component", "model_id", "status", "error_code", "output_characters",
                                "input_tokens", "output_tokens", "duration_ms",
                            )} for call in audit.get("model_calls", [])],
                            "build_commit": audit.get("build_commit"),
                        })
                    record.update({
                        "correlation_id": correlation_id,
                        "trace_id": audit.get("trace_id"),
                        "source_ids": [source["source_id"] for source in response.get("sources", []) if source.get("source_id")],
                        "policy_source_ids": [source["source_id"] for source in audit.get("policy_sources", []) if source.get("source_id")],
                    })
                    record["passed"] = bool(record["passed"] and passed)
                    if response_observer is not None and turn_index == len(turns) - 1:
                        observer_started = time.perf_counter()
                        try:
                            response_observer(case, request, response, repeat, passed)
                        finally:
                            observer_duration += time.perf_counter() - observer_started
                    if (maximum_estimated_cost_usd is not None or maximum_total_tokens is not None) and not record["token_usage_complete"]:
                        usage_unknown = True
                    if not passed and turn_index < len(turns) - 1:
                        # An invalid setup cannot establish the state under test.
                        break
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                recovered = None
                if isinstance(exc, LiveEndpointError) and exc.trace_id and active_turn_index is not None:
                    recovered = failed_turn_usage(
                        url, api_key, synthetic_user_id, session_id, exc.trace_id, timeout_seconds,
                    )
                if recovered is not None:
                    total_input_tokens += recovered["input_tokens"]
                    total_output_tokens += recovered["output_tokens"]
                    record["input_tokens"] += recovered["input_tokens"]
                    record["output_tokens"] += recovered["output_tokens"]
                    record["model_call_count"] += recovered["model_call_count"]
                    record["token_usage_complete"] = (record["token_usage_complete"]
                                                       and recovered["token_usage_complete"])
                    record.update(
                        usage_recovery="durable_trace",
                        recovered_model_call_ids=recovered["model_call_ids"],
                        recovered_completed_model_call_count=recovered["completed_model_call_count"],
                        error_code=recovered["error_code"], error_codes=recovered["error_codes"],
                    )
                else:
                    record["token_usage_complete"] = False
                if (maximum_estimated_cost_usd is not None or maximum_total_tokens is not None) and not record["token_usage_complete"]:
                    usage_unknown = True
                record.update(
                    {
                        "passed": False,
                        "error_type": type(exc).__name__,
                    }
                )
                if isinstance(exc, LiveEndpointError):
                    record.update(
                        {
                            "http_status": exc.status_code,
                            "correlation_id": exc.correlation_id,
                        }
                    )
                    if exc.trace_id:
                        record["trace_id"] = exc.trace_id
                    if active_turn_index is not None:
                        record["turns"].append({
                            "turn_index": active_turn_index, "is_setup": active_turn_index < len(turns) - 1,
                            "passed": False, "http_status": exc.status_code,
                            "latency_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                            "trace_id": exc.trace_id, "correlation_id": exc.correlation_id,
                            "input_tokens": recovered["input_tokens"] if recovered else 0,
                            "output_tokens": recovered["output_tokens"] if recovered else 0,
                            "model_call_count": recovered["model_call_count"] if recovered else 0,
                            "token_usage_complete": bool(recovered and recovered["token_usage_complete"]),
                        })
            finally:
                record["latency_ms"] = round((time.perf_counter() - started - observer_duration) * 1000, 2)
                # Setup and final turns share one disposable owned session.
                cleaned_up = cleanup_session(
                    url, api_key, synthetic_user_id, session_id, timeout_seconds,
                )
                user_cleaned_up = cleanup_user_data(url, api_key, synthetic_user_id, timeout_seconds)
            latencies.append(record["latency_ms"])
            record["checks"].append(
                {"check": "synthetic_session_cleanup", "passed": cleaned_up}
            )
            record["checks"].append({"check": "synthetic_user_cleanup", "passed": user_cleaned_up})
            record["cleanup_succeeded"] = cleaned_up and user_cleaned_up
            record["passed"] = bool(record["passed"] and cleaned_up and user_cleaned_up)
            category_results[case["category"]][0] += int(record["passed"])
            category_results[case["category"]][1] += 1
            records.append(record)
        if spending_stopped:
            break

    passed_runs = sum(int(record["passed"]) for record in records)
    estimated_cost = (
        total_input_tokens * input_cost_per_million
        + total_output_tokens * output_cost_per_million
    ) / 1_000_000
    category_metrics = {
        category: round(passed / total, 4)
        for category, (passed, total) in sorted(category_results.items())
    }
    return {
        "schema_version": 1,
        "measurement": (
            "offline_fixture_contract" if expected_model_provider == "local_fixture"
            else "live_generated_contract_checks"
        ),
        "semantic_quality_review": "required" if any(case.get("rubric") for case in cases) else "not_requested",
        "latency_unit": "complete_conversation_excluding_cleanup",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "target_host": target.hostname,
        "model_provider": expected_model_provider,
        "model_id": expected_model_id,
        "prompt_set_version": expected_prompt_version,
        "repeats": repeats,
        "total_runs": len(records),
        "passed_runs": passed_runs,
        "pass_rate": round(passed_runs / len(records), 4) if records else 0,
        "requested_runs": len(cases) * repeats,
        "completed_requested_runs": len(records) == len(cases) * repeats and not spending_stopped,
        "spending_stopped": spending_stopped,
        "usage_unknown": usage_unknown,
        "category_pass_rates": category_metrics,
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "token_usage": {
            "input": total_input_tokens,
            "output": total_output_tokens,
            "total": total_input_tokens + total_output_tokens,
        },
        "token_usage_complete": all(record["token_usage_complete"] for record in records),
        "cost_estimate": {
            "currency": "USD",
            "input_per_million_tokens": input_cost_per_million,
            "output_per_million_tokens": output_cost_per_million,
            "estimated_total": round(estimated_cost, 6),
        },
        "records": records,
    }


def enforce_thresholds(
    report: dict[str, Any],
    *,
    minimum_pass_rate: float,
    maximum_p95_ms: float,
    maximum_estimated_cost_usd: float,
) -> list[str]:
    failures = []
    if report.get("completed_requested_runs") is False:
        failures.append("live evaluation stopped before all requested runs completed")
    if report.get("usage_unknown"):
        failures.append("live evaluation could not account for model usage")
    if float(report["pass_rate"]) < minimum_pass_rate:
        failures.append("live evaluation pass rate was below threshold")
    p95 = report["latency_ms"]["p95"]
    if p95 is None or float(p95) > maximum_p95_ms:
        failures.append("live evaluation p95 latency exceeded threshold")
    if float(report["cost_estimate"]["estimated_total"]) > maximum_estimated_cost_usd:
        failures.append("live evaluation estimated cost exceeded threshold")
    return failures


def write_job_summary(report: dict[str, Any], failures: list[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    result = "PASS" if not failures else "FAIL"
    categories = ", ".join(
        f"{name}={rate:.0%}" for name, rate in report["category_pass_rates"].items()
    )
    lines = [
        "## Live OpenAI and RAG evaluation",
        "",
        f"- Result: **{result}**",
        f"- Measurement: {report['measurement']}",
        f"- Semantic rubric review: {report['semantic_quality_review']}",
        f"- Contract pass rate: {report['pass_rate']:.1%}",
        f"- Categories: {categories}",
        (
            f"- P50/P95/P99: {report['latency_ms']['p50']} / "
            f"{report['latency_ms']['p95']} / {report['latency_ms']['p99']} ms"
        ),
        f"- Tokens: {report['token_usage']['total']}",
        f"- Estimated cost: USD {report['cost_estimate']['estimated_total']:.6f}",
    ]
    if failures:
        lines.extend(["", "Failures:", *[f"- {failure}" for failure in failures]])
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run repeated privacy-safe evaluation against the deployed coach"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--expected-model-provider", default="openai")
    parser.add_argument("--expected-model-id", required=True)
    parser.add_argument("--expected-prompt-version", default=json.loads((Path(__file__).resolve().parents[2] / "apps/ai-service/prompts/current/manifest.json").read_text())["version"])
    parser.add_argument("--input-cost-per-million", type=float, default=0.10)
    parser.add_argument("--output-cost-per-million", type=float, default=0.50)
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=10000)
    parser.add_argument("--maximum-estimated-cost-usd", type=float, default=0.05)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "unknown"))
    args = parser.parse_args()

    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate must be between zero and one")
    if args.maximum_p95_ms <= 0 or args.maximum_estimated_cost_usd < 0:
        parser.error("latency and cost thresholds must not be negative")

    report = run_live_evaluation(
        url=args.url,
        api_key=args.api_key,
        cases=load_cases(args.cases),
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        expected_model_provider=args.expected_model_provider,
        expected_model_id=args.expected_model_id,
        expected_prompt_version=args.expected_prompt_version,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
        commit_sha=args.commit_sha,
        maximum_estimated_cost_usd=args.maximum_estimated_cost_usd,
    )
    failures = enforce_thresholds(
        report,
        minimum_pass_rate=args.minimum_pass_rate,
        maximum_p95_ms=args.maximum_p95_ms,
        maximum_estimated_cost_usd=args.maximum_estimated_cost_usd,
    )
    report["threshold_failures"] = failures
    report["passed"] = not failures
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_job_summary(report, failures)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "records"}, indent=2
        )
    )
    if failures:
        raise SystemExit("Live evaluation failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
