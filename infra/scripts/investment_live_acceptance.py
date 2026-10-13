"""One bounded synthetic run against real OpenAI, ECS, Bedrock and saved chat history.

No generation retries, no infrastructure changes, no real-user data. The workflow
disables itself before this script runs. A failure remains evidence, not a retry.
"""
import hashlib
import html
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

try:
    from .live_evaluation import (
        LiveEndpointError,
        _owned_api_request_json,
        cleanup_session,
        cleanup_user_data,
        owned_api_url,
        request_json,
    )
except ImportError:
    from live_evaluation import (
        LiveEndpointError,
        _owned_api_request_json,
        cleanup_session,
        cleanup_user_data,
        owned_api_url,
        request_json,
    )

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "infra/llmsecops/investment-live-evaluation-cases.jsonl"
RAG_CASES = ROOT / "infra/llmsecops/investment-live-rag-cases.jsonl"
MANIFEST = ROOT / "knowledge/investment_education/source_manifest.json"
MODEL = "gpt-6-luna"
MAX_TOKENS = 200_000  # Stop BEFORE another turn; a turn can cross this threshold.
SOURCE_FIELDS = (
    "source_id", "title", "issuing_organization", "canonical_url", "published_at",
    "document_version", "checksum", "corpus_version", "review_due_at",
)


def load_dataset(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def source_matches(source, manifest):
    expected = next((item for item in manifest["sources"]
                     if item["source_id"] == source.get("source_id")), None)
    return bool(manifest.get("manifest_status") == "approved_for_ingestion"
                and expected and expected.get("ingestion_approved") is True
                and expected.get("source_review_status") == expected.get("content_review_status") == "approved"
                and not expected.get("withdrawn_at")
                and all(source.get(key) == (manifest["corpus_version"] if key == "corpus_version"
                                            else expected.get(key)) for key in SOURCE_FIELDS)
                and str(source.get("review_due_at", "")) >= datetime.now(UTC).date().isoformat())


def capture_aws(ecs, cluster, services):
    """Select only non-secret deployment facts; never persist a full task definition."""
    response = ecs.describe_services(cluster=cluster, services=list(services.values()))
    if response.get("failures") or {s["serviceName"] for s in response["services"]} != set(services.values()):
        raise ValueError("ECS_SERVICES_MISSING")
    result = {}
    for role, name in services.items():
        service = next(s for s in response["services"] if s["serviceName"] == name)
        deployments = service["deployments"]
        if not (service["status"] == "ACTIVE" and service["desiredCount"] > 0
                and service["runningCount"] == service["desiredCount"] and service["pendingCount"] == 0
                and len(deployments) == 1 and deployments[0].get("rolloutState") == "COMPLETED"):
            raise ValueError("ECS_NOT_STABLE_" + role.upper())
        definition = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
        containers = definition["containerDefinitions"]
        envs = [{e["name"]: e["value"] for e in c.get("environment", [])} for c in containers]
        config = {}
        if role == "ai":
            selected = [(c, e) for c, e in zip(containers, envs, strict=True) if "MODEL_PROVIDER" in e]
            if len(selected) != 1:
                raise ValueError("AI_CONTAINER_NOT_IDENTIFIED")
            container, env = selected[0]
            keys = ("MODEL_PROVIDER", "MODEL_ID", "RAG_PROVIDER", "POLICY_RAG_PROVIDER",
                    "EDUCATION_KNOWLEDGE_BASE_ID", "EDUCATION_CORPUS_VERSION", "BUILD_COMMIT")
            config = {key: env.get(key) for key in keys}
            config["BUILD_COMMIT"] = config["BUILD_COMMIT"] or container["image"].rsplit(":", 1)[-1]
            if not (config["MODEL_PROVIDER"] == "openai" and config["MODEL_ID"] == MODEL
                    and config["RAG_PROVIDER"] == config["POLICY_RAG_PROVIDER"] == "bedrock"
                    and config["EDUCATION_KNOWLEDGE_BASE_ID"]
                    and re.fullmatch(r"[a-f0-9]{40}", config["BUILD_COMMIT"])):
                raise ValueError("LIVE_PROVIDERS_OR_BUILD_NOT_VERIFIED")
        elif role == "backend":
            config = {"postgres_configured": any(e.get("POSTGRES_HOST") and e.get("POSTGRES_DB") for e in envs)}
            if not config["postgres_configured"]:
                raise ValueError("POSTGRES_NOT_CONFIGURED")
        arns = ecs.list_tasks(cluster=cluster, serviceName=name, desiredStatus="RUNNING")["taskArns"]
        tasks = ecs.describe_tasks(cluster=cluster, tasks=arns) if arns else {"tasks": []}
        if (tasks.get("failures") or len(tasks["tasks"]) != service["desiredCount"] or any(
            t.get("lastStatus") != "RUNNING" or t.get("taskDefinitionArn") != service["taskDefinition"]
            or t.get("healthStatus") == "UNHEALTHY" or not t.get("containers")
            or any(not c.get("imageDigest") or c.get("lastStatus") != "RUNNING" for c in t["containers"])
            for t in tasks["tasks"]
        )):
            raise ValueError("RUNNING_TASKS_NOT_VERIFIED_" + role.upper())
        result[role] = {"service": name, "task_definition": service["taskDefinition"],
                        "rollout_state": "COMPLETED", "running_count": service["runningCount"],
                        "config": config, "images": sorted({c["image"] for t in tasks["tasks"] for c in t["containers"]}),
                        "image_digests": sorted({c["imageDigest"] for t in tasks["tasks"] for c in t["containers"]})}
    return result


def bedrock_probe(client, knowledge_base, cases, manifest):
    records = []
    for case in cases:
        response = client.retrieve(
            knowledgeBaseId=knowledge_base, retrievalQuery={"text": case["query"]},
            retrievalConfiguration={"vectorSearchConfiguration": {
                "numberOfResults": 5, "filter": {"andAll": [
                    {"equals": {"key": "corpus_version", "value": manifest["corpus_version"]}},
                    {"equals": {"key": "review_status", "value": "approved"}},
                ]},
            }},
        )
        rows = response.get("retrievalResults", [])
        matches = [r for r in rows if source_matches(r.get("metadata", {}), manifest)
                   and r.get("metadata", {}).get("review_status") == "approved"
                   and bool(r.get("content", {}).get("text", "").strip())]
        hit = bool(set(case["expected_source_ids"]) & {r["metadata"]["source_id"] for r in matches})
        records.append({**case, "passed": bool(hit and len(matches) == len(rows) and 0 < len(rows) <= 5),
                        "expected_source_hit_at_5": hit,
                        "aws_request_id": response.get("ResponseMetadata", {}).get("RequestId"),
                        "results": [{"rank": i + 1, "score": r.get("score"),
                                     "source": {k: r.get("metadata", {}).get(k) for k in SOURCE_FIELDS},
                                     "text": r.get("content", {}).get("text", "")[:6000]}
                                    for i, r in enumerate(rows)]})
    return records


def investment_data(response):
    return next((item.get("data", {}) for item in response.get("agent_results", [])
                 if item.get("agent") == "investment_education"), {})


def explanation_words(response):
    result = next((item for item in response.get("agent_results", [])
                   if item.get("agent") == "investment_education"), {})
    # Use the actual specialist explanation, excluding appended citation URLs/disclaimers.
    text = result.get("summary", "")
    text = re.sub(r"\[[^\]]*\]\([^)]*\)|\[source:[^\]]+\]", "", text)
    return re.findall(r"\b[\w'-]+\b", text)


def evaluate_turn(response, expected, manifest, build, previous=None):
    audit = response.get("audit", {})
    answer = response.get("answer", "")
    calls = audit.get("model_calls", [])
    checks = {
        "nonempty_answer": isinstance(answer, str) and bool(answer.strip()),
        "blocked_matches": response.get("blocked") is expected["blocked"],
        "routing_exact_match": set(response.get("selected_agents", [])) == set(expected["selected_agents"]),
        "deployed_build_matches": audit.get("build_commit") == build,
        "model_provider": audit.get("model_provider") == "openai" and audit.get("model_id") == MODEL,
        "answer_terms": all(term.casefold() in answer.casefold() for term in expected["answer_terms"]),
        "token_usage_complete": audit.get("composition_usage_complete") is not False
            and type(audit.get("model_call_count")) is int and audit["model_call_count"] == len(calls)
            and all(type(c.get(k)) is int and c[k] >= 0 for c in calls for k in ("input_tokens", "output_tokens"))
            and all(audit.get("model_" + k) == sum(c.get(k) or 0 for c in calls)
                    for k in ("input_tokens", "output_tokens")),
    }
    if expected["model_required"]:
        checks["real_model_called"] = checks["token_usage_complete"] and bool(calls) and sum(c["input_tokens"] for c in calls) > 0 and all(
            c.get("model_id") == MODEL and c.get("status") == "completed" for c in calls)
        checks["no_generic_withheld_answer"] = audit.get("answer_status") == "answered"
    else:
        checks["safety_refusal_recorded"] = response.get("blocked") is True and audit.get("answer_status") == "refused"
        if not expected["selected_agents"]:
            checks["injection_blocked_before_model"] = not calls and bool(audit.get("guardrail_findings"))
        else:
            refusal = json.loads((ROOT / "apps/shared/coach_i18n/locales/en.json").read_text())["safety.brokerage_refusal"]
            checks["friendly_brokerage_refusal"] = answer == refusal
    if expected["rag"]:
        sources = response.get("sources", [])
        data = investment_data(response)
        checks["manifest_matched_citations"] = bool(sources) and all(source_matches(s, manifest) for s in sources)
        checks["clickable_citations"] = bool(sources) and all(
            f"]({s.get('canonical_url')})" in answer for s in sources)
        checks["grounded_or_labelled_hybrid"] = data.get("evidence_status") in {"grounded", "hybrid"}
        if data.get("evidence_status") == "hybrid":
            checks["hybrid_model_sections_separate"] = bool(data.get("general_knowledge"))
    if expected.get("simpler_than_previous"):
        before = explanation_words(previous or {})
        after = explanation_words(response)
        checks["followup_shorter_explanation"] = bool(after) and len(after) < len(before)
    return [{"check": key, "passed": bool(value)} for key, value in checks.items()]


def run_conversations(url, key, cases, manifest, build, request=request_json,
                      owned_request=_owned_api_request_json, cleanup=cleanup_user_data,
                      session_cleanup=cleanup_session, save=lambda records: None):
    records = []
    tokens = 0
    stop = False
    for case in cases:
        if stop or tokens >= MAX_TOKENS:
            break
        owner, session = "live-evaluation-" + uuid4().hex, "investment-live-" + uuid4().hex
        record = {"case_id": case["id"], "rubric": case["rubric"], "turns": [], "passed": False,
                  "synthetic_user_id": owner, "session_id": session}
        records.append(record)
        previous = None
        try:
            owned_request(owned_api_url(url, "/profiles"), key, "POST", {"user_id": owner}, 30)
            for turn in case["turns"]:
                if tokens >= MAX_TOKENS:
                    raise ValueError("TOKEN_SPENDING_BOUND_REACHED")
                start = time.monotonic()
                response, correlation_id = request(url, key, {
                    "user_id": owner, "session_id": session, "message": turn["message"],
                }, 90)
                audit = response.get("audit", {})
                checks = evaluate_turn(response, turn["expected"], manifest, build, previous)
                row = {"question": turn["message"], "expected": turn["expected"],
                       "answer": response.get("answer"), "sources": response.get("sources", []),
                       "selected_agents": response.get("selected_agents"), "blocked": response.get("blocked"),
                       "evidence_status": investment_data(response).get("evidence_status"),
                       "model_knowledge": investment_data(response).get("general_knowledge", []),
                       "checks": checks, "latency_ms": round((time.monotonic() - start) * 1000),
                       "correlation_id": correlation_id,
                       "audit": {k: audit.get(k) for k in (
                           "trace_id", "build_commit", "model_provider", "model_id", "prompt_set_version",
                           "model_call_count", "model_input_tokens", "model_output_tokens", "answer_status",
                           "guardrail_findings", "retrieval_corpus_versions")}}
                row["model_calls"] = [{k: c.get(k) for k in (
                    "component", "model_id", "status", "input_tokens", "output_tokens", "duration_ms")}
                    for c in audit.get("model_calls", [])]
                row["passed"] = all(c["passed"] for c in checks)
                record["turns"].append(row)
                previous = response
                if not next(c["passed"] for c in checks if c["check"] == "token_usage_complete"):
                    stop = True
                else:
                    tokens += audit["model_input_tokens"] + audit["model_output_tokens"]
                save(records)
                # A failed setup cannot establish the follow-up; never retry it.
                if not row["passed"] or stop:
                    break
            history = owned_request(owned_api_url(url, f"/users/{owner}/chat-sessions/{session}"),
                                    key, "GET", None, 30)
            answers = [m for m in history.get("messages", []) if m.get("role") == "assistant"]
            record["history_persisted"] = len(answers) == len(record["turns"]) and all(
                item.get("content") == turn["answer"] and item.get("sources", []) == turn["sources"]
                for item, turn in zip(answers, record["turns"], strict=True))
        except (OSError, ValueError, KeyError, TypeError) as error:
            record["error_type"] = type(error).__name__
            if isinstance(error, LiveEndpointError):
                record["http_status"] = error.status_code
                record["correlation_id"] = error.correlation_id
                record["trace_id"] = error.trace_id
            # Unknown request outcomes may have spent tokens. Do not issue another generation.
            stop = True
        finally:
            session_removed = session_cleanup(url, key, owner, session, 30)
            actor_removed = cleanup(url, key, owner, 30)
            record["cleanup_succeeded"] = session_removed and actor_removed
            record["passed"] = (not record.get("error_type") and record.get("history_persisted", False)
                                and record["cleanup_succeeded"] and len(record["turns"]) == len(case["turns"])
                                and all(t["passed"] for t in record["turns"]))
            if not record["cleanup_succeeded"]:
                stop = True
            save(records)
    return records


def write_report(report, directory):
    (directory / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    title = "AUTOMATED CHECKS PASS" if report.get("passed") else "NOT PASSED / INCOMPLETE"
    sections = ["<h1>Investment Agent: one-time live integration</h1>",
                f"<p><strong>{title}</strong> — synthetic questions; real deployed services.</p>",
                "<p>Automated contract checks are not a semantic quality guarantee. Review the answers against each rubric.</p>"]
    for case in report.get("conversations", []):
        sections.append(f"<h2>{html.escape(case['case_id'])}</h2><p>{html.escape(case['rubric'])}</p>")
        for turn in case["turns"]:
            sections.append(f"<h3>{html.escape(turn['question'])}</h3><pre>{html.escape(turn['answer'] or '')}</pre>")
            sections.append("<p>Evidence: " + html.escape(str(turn.get("evidence_status"))) + "</p><ul>")
            for source in turn.get("sources", []):
                url = source.get("canonical_url", "")
                if isinstance(url, str) and url.startswith("https://"):
                    sections.append(f'<li><a href="{html.escape(url, quote=True)}">{html.escape(str(source.get("title")))}</a></li>')
            sections.append("</ul>")
            sections.append("<p>" + html.escape(", ".join(c["check"] + ": " + str(c["passed"]) for c in turn["checks"])) + "</p>")
    sections.append("<h2>Complete measurements and AWS evidence</h2><pre>" + html.escape(json.dumps(report, indent=2, ensure_ascii=False)) + "</pre>")
    (directory / "index.html").write_text("<!doctype html><meta charset='utf-8'><title>Investment live evaluation</title>"
        "<style>body{max-width:1000px;margin:40px auto;font:16px system-ui;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f7;padding:20px}h2{margin-top:40px}</style>" + "\n".join(sections))


def main():
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError

    directory = ROOT / "artifacts/investment-live"
    directory.mkdir(parents=True, exist_ok=False)  # Never overwrite the single run.
    cases, rag_cases = load_dataset(CASES), load_dataset(RAG_CASES)
    if len(cases) != 6 or sum(len(c["turns"]) for c in cases) != 7 or len(rag_cases) != 3:
        raise ValueError("BOUNDED_DATASET_CHANGED")
    manifest = json.loads(MANIFEST.read_text())
    report = {"schema_version": 1, "passed": False, "started_at": datetime.now(UTC).isoformat(),
              "execution": "one live run; zero harness generation retries", "test_commit": os.environ.get("GITHUB_SHA"),
              "workflow_run_id": os.environ.get("GITHUB_RUN_ID"), "human_semantic_review": "pending",
              "planned_conversations": 6, "planned_turns": 7, "planned_bedrock_queries": 3,
              "dataset_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (CASES, RAG_CASES, MANIFEST)}, "conversations": []}
    write_report(report, directory)
    try:
        if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("RERUN_NOT_ALLOWED")
        region, cluster = os.environ["AWS_REGION"], os.environ["ECS_CLUSTER"]
        services = {role: os.environ[role.upper() + "_SERVICE"] for role in ("ai", "backend", "frontend")}
        config = Config(retries={"total_max_attempts": 1}, connect_timeout=10, read_timeout=30)
        ecs = boto3.client("ecs", region_name=region, config=config)
        report["stage"] = "aws_preflight"
        report["aws_before"] = capture_aws(ecs, cluster, services)
        ai = report["aws_before"]["ai"]["config"]
        if ai["EDUCATION_CORPUS_VERSION"] != manifest["corpus_version"]:
            raise ValueError("DEPLOYED_CORPUS_DIFFERS_FROM_TEST_MANIFEST")
        kb_region = os.environ.get("BEDROCK_KB_REGION") or region
        bedrock = boto3.client("bedrock-agent-runtime", region_name=kb_region, config=config)
        report["stage"] = "bedrock_retrieval"
        report["bedrock"] = bedrock_probe(bedrock, ai["EDUCATION_KNOWLEDGE_BASE_ID"], rag_cases, manifest)
        write_report(report, directory)
        def checkpoint(records):
            report["conversations"] = records
            write_report(report, directory)

        report["stage"] = "live_conversations"
        report["conversations"] = run_conversations(
            os.environ["COACH_URL"], os.environ["SMOKE_BACKEND_API_KEY"], cases, manifest, ai["BUILD_COMMIT"],
            save=checkpoint)
        write_report(report, directory)
        report["stage"] = "aws_postflight"
        report["aws_after"] = capture_aws(ecs, cluster, services)
        report["deployment_unchanged"] = report["aws_before"] == report["aws_after"]
        report["passed"] = (report["deployment_unchanged"] and len(report["conversations"]) == len(cases)
                            and all(r["passed"] for r in report["conversations"])
                            and all(r["passed"] for r in report["bedrock"]))
        report["stage"] = "complete"
    except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError) as error:
        # No provider error bodies, keys, headers or complete task environments in evidence.
        report["error_type"] = type(error).__name__
        if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]+", str(error)):
            report["error_code"] = str(error)
        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "")
            if re.fullmatch(r"[A-Za-z_]+", code):
                report["aws_error_code"] = code
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        turns = [t for c in report["conversations"] for t in c["turns"]]
        usage_known = len(turns) == 7 and all(
            next(c["passed"] for c in t["checks"] if c["check"] == "token_usage_complete") for t in turns)
        report["metrics"] = {"completed_turns": len(turns), "planned_turns": 7,
                             "passing_turns": sum(t["passed"] for t in turns),
                             "turn_contract_pass_rate": sum(t["passed"] for t in turns) / 7,
                             "expected_source_hit_at_5": sum(r["expected_source_hit_at_5"] for r in report.get("bedrock", [])) / 3,
                             "usage_complete_for_planned_run": usage_known,
                             "input_tokens": sum(t["audit"]["model_input_tokens"] for t in turns
                                                 if type(t["audit"].get("model_input_tokens")) is int),
                             "output_tokens": sum(t["audit"]["model_output_tokens"] for t in turns
                                                  if type(t["audit"].get("model_output_tokens")) is int)}
        write_report(report, directory)
        summary = (f"## One-time Investment live integration: {'PASS' if report['passed'] else 'NOT PASSED'}\n\n"
                   f"- Turns passing: {report['metrics']['passing_turns']}/7.\n"
                   f"- Bedrock expected-source hit@5: {report['metrics']['expected_source_hit_at_5']:.0%}.\n"
                   "- Acceptance: all 7 turn contracts, 3/3 expected-source hits, stable unchanged ECS services, saved answers/citations and synthetic cleanup. Missing or skipped evidence cannot pass.\n"
                   "- Model: real OpenAI gpt-6-luna. Dataset: infra/llmsecops/investment-live-evaluation-cases.jsonl and investment-live-rag-cases.jsonl.\n"
                   "- Real model and AWS proof, questions, answers, citations and per-check results: **investment-live-evidence** artifact.\n"
                   "- Human semantic review pending; one run is not a production quality percentage.\n"
                   "- This workflow disables itself before evaluation and rejects reruns.\n")
        summary += "\n| Scenario | Result |\n|---|---|\n"
        for case in cases:
            observed = next((c for c in report["conversations"] if c["case_id"] == case["id"]), None)
            status = "NOT EXECUTED" if observed is None else "PASS" if observed["passed"] else "FAIL"
            summary += f"| {case['id']} | {status} |\n"
        (directory / "summary.md").write_text(summary)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
                handle.write(summary)
        print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
