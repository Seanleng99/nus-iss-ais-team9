"""Bounded live Coach edits on a unique synthetic profile, erased in finally."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

try:
    from .live_evaluation import LiveEndpointError, require_http_url
except ImportError:  # Direct script execution in the release workflow.
    from live_evaluation import LiveEndpointError, require_http_url


def http_json(url, key, method, payload=None):
    request = urllib.request.Request(require_http_url(url), data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "X-API-Key": key}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # nosec B310 - validated HTTP(S) URL
            data = response.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as error:
        raise LiveEndpointError(error.code, error.headers.get("X-Correlation-ID")) from error


def run(url, key, *, request=http_json):
    require_http_url(url)
    if not url.rstrip("/").endswith("/coach"):
        raise ValueError("Expected the Coach API URL")
    base = url.rstrip("/")[:-len("/coach")]
    owner = "live-evaluation-budget-" + uuid4().hex
    session = "budget-multiturn-" + uuid4().hex
    path = f"{base}/users/{owner}"
    checks = []
    turns = []
    created = False

    def check(name, condition):
        checks.append({"check": name, "passed": bool(condition)})
        if not condition:
            raise ValueError("Acceptance check failed: " + name)

    def send(message, *, model=True):
        start = time.monotonic()
        result = request(url, key, "POST", {"user_id": owner, "session_id": session, "message": message})
        audit = result.get("audit", {})
        turns.append({"elapsed_ms": round((time.monotonic()-start)*1000), "model_id": audit.get("model_id"), "budget_capture": audit.get("budget_capture")})
        if model:
            check("live_model_"+str(len(turns)), audit.get("model_id") == "gpt-6-luna" and bool(audit.get("model_calls")))
        return result

    def stored():
        return request(path+"/cashflow/settings", key, "GET")

    def stage_settings(payload):
        preview = request(path+"/budget/workspace/preview", key, "POST", {"operation": "cashflow", "payload_json": json.dumps(payload)})
        request(path+"/budget/workspace/confirm", key, "POST", {"preview_id": preview["preview_id"], "confirmed": True})

    error_type = None
    try:
        request(path+"/profile", key, "PUT", {})
        created = True
        stage_settings({"opening_on": "2026-10-01", "opening_balance": 2000, "currency": "SGD", "schedules": [
            {"id": "rent", "name": "Rent", "category": "housing", "kind": "expense", "amount": 1000, "first_on": "2026-10-05", "frequency": "monthly"},
            {"id": "phone", "name": "Phone", "category": "utilities", "kind": "expense", "amount": 50, "first_on": "2026-10-10", "frequency": "monthly"}]})
        result = send("In my budget workspace, change the Rent bill amount. Ask me for the new amount; I have not supplied it yet. Keep all other bill terms and schedules.")
        check("clarifies_missing_amount", result.get("audit", {}).get("budget_capture") == "needs_input")
        check("clarification_does_not_save", stored()["schedules"][0]["amount"] == 1000)
        result = send("The new Rent bill amount is SGD 1200 monthly. Keep its dates, category and other settings and all other bills. Please preview the change.")
        check("first_preview", result.get("audit", {}).get("budget_capture") == "workspace_preview")
        result = send("Correction: Rent should be SGD 1250 monthly, not 1200. Keep all other schedules and settings. Show the corrected preview.")
        check("corrected_preview", result.get("audit", {}).get("budget_capture") == "workspace_preview")
        check("preview_does_not_save", stored()["schedules"][0]["amount"] == 1000)
        send("confirm budget", model=False)
        saved = {r["id"]: r for r in stored()["schedules"]}
        check("confirmed_corrected_amount", saved["rent"]["amount"] == 1250)
        check("preserves_other_bill", saved["phone"]["amount"] == 50 and len(saved) == 2)
        send("Change the Rent bill amount to SGD 1300 monthly, preserving every other term and schedule. Preview the budget workspace change.")
        send("cancel", model=False)
        check("cancellation_preserves_saved_amount", {r["id"]: r for r in stored()["schedules"]}["rent"]["amount"] == 1250)
        send("Change the Rent bill amount to SGD 1400 monthly, preserving every other term and schedule. Preview the budget workspace change.")
        stage_settings({"opening_balance": 2100})
        result = send("confirm budget", model=False)
        check("stale_confirmation_rejected", "changed" in result.get("answer", "").lower())
        check("stale_preview_does_not_save", {r["id"]: r for r in stored()["schedules"]}["rent"]["amount"] == 1250)
    except (OSError, ValueError, KeyError, TypeError) as error:
        error_type = type(error).__name__
    finally:
        cleanup = not created
        if created:
            try:
                policy = request(path+"/data-lifecycle", key, "GET")["policy_version"]
                request(path+"/data", key, "DELETE", {"confirm_user_id": owner, "policy_version": policy})
                cleanup = True
            except (OSError, ValueError, KeyError, TypeError):
                cleanup = False
        checks.append({"check": "synthetic_profile_erased", "passed": cleanup})
    return {"passed": error_type is None and all(c["passed"] for c in checks), "error_type": error_type, "checks": checks, "turns": turns}


def main():
    result = run(os.environ["COACH_URL"], os.environ["SMOKE_BACKEND_API_KEY"])
    output = Path("artifacts/budget-multiturn-acceptance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
