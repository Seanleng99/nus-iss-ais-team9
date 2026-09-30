"""Shared preview/confirm commands for Budget UI and conversational planning."""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.infrastructure.models import (
    FinancialGoalRecord,
    MonthlyBudgetRecord,
    PlanningPreferencesRecord,
    TransactionRecord,
)
from app.services.financial_workspace import lock_workspace, read_section, write_section


class WorkspaceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["cashflow", "commitments", "reconcile", "unlink", "continuity", "reviews", "timing", "reserves"]
    payload_json: str = Field(default="{}", max_length=30000)


def context(session, user_id):
    from app.services.budget_reconciliation import reconciliation_context

    record = session.get(PlanningPreferencesRecord, user_id)
    return {
        "settings": {
            k: v
            for k, v in (record.data if record else {}).items()
            if k in {"cashflow", "review_preferences", "reserves"} or k.startswith(("constraints:", "timing:"))
        },
        "goals": [
            {"id": str(g.id), "name": g.name, "currency": g.currency}
            for g in session.scalars(
                select(FinancialGoalRecord).where(FinancialGoalRecord.user_id == user_id)
            )
        ],
        "reconciliation": reconciliation_context(session, user_id),
    }


def evidence(session, user_id):
    from app.services.budget_capture import _snapshot
    from app.services.budget_continuity import fingerprint, local_today

    return fingerprint(
        {
            "context": context(session, user_id),
            "date": local_today(),
            "budgets": {
                str(b.period_start): _snapshot(b)
                for b in session.scalars(
                    select(MonthlyBudgetRecord).where(MonthlyBudgetRecord.user_id == user_id)
                )
            },
            "transactions": [
                (str(t.id), str(t.occurred_on), str(t.amount), t.currency, t.transaction_type)
                for t in session.scalars(
                    select(TransactionRecord)
                    .where(TransactionRecord.user_id == user_id)
                    .order_by(TransactionRecord.id)
                )
            ],
            "goals": [
                (str(g.id), str(g.current_amount), str(g.target_amount), g.target_months)
                for g in session.scalars(
                    select(FinancialGoalRecord)
                    .where(FinancialGoalRecord.user_id == user_id)
                    .order_by(FinancialGoalRecord.id)
                )
            ],
        }
    )


def build_change(session, user_id, change):
    from app.services.budget_constraints import AllocationPolicy, validate_policy
    from app.services.budget_continuity import ContinuityRequest, ReviewPreferences, preview_batch
    from app.services.budget_reconciliation import (
        MatchRequest,
        UnlinkRequest,
        validate_match,
        validate_settings,
        validate_unlink,
    )
    from app.services.cashflow import CashflowSettings

    try:
        supplied = json.loads(change.payload_json)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError(
            "Please clarify the planning details; the draft format was invalid"
        ) from error
    if not isinstance(supplied, dict):
        raise ValueError("Supply planning details as one object")  # noqa: TRY004 - domain validation for API/Coach
    supplied.pop("confirmed", None)  # Model approval is never authorization.
    op = change.operation
    previous = None
    if op == "cashflow":
        previous = read_section(session, user_id, "cashflow") or {}
        raw = {**previous, **supplied, "confirmed": True}
        for key in ("opening_on", "opening_balance", "currency", "schedules"):
            if key not in raw:
                raise ValueError(
                    f"Please supply {key.replace('_', ' ')} for cash-flow planning (SGD only)"
                )
        # Schedule lists are complete replacements and displayed as such; IDs preserve existing identities.
        target = validate_settings(
            session, user_id, CashflowSettings.model_validate(raw)
        ).model_dump(mode="json")
    elif op == "commitments":
        if not supplied.get("period_start"):
            raise ValueError("Which month and year should these commitments apply to?")
        stored = read_section(session, user_id, "constraints:" + supplied["period_start"]) or {}
        previous = stored.get("policy", {})
        target = AllocationPolicy.model_validate(
            {**previous, **supplied, "confirmed": True}
        ).model_dump(mode="json")
        validate_policy(session, user_id, AllocationPolicy.model_validate(target))
    elif op == "reserves":
        from app.services.budget_reserves import Reserves
        target = Reserves.model_validate({**supplied, "confirmed": True}).model_dump(mode="json")
        previous = read_section(session, user_id, "reserves")
    elif op == "timing":
        from app.services.budget_timing import TimingSettings
        target = TimingSettings.model_validate({**supplied, "confirmed": True}).model_dump(mode="json")
        previous = read_section(session, user_id, "timing:" + target["period_start"])
    elif op == "reconcile":
        target = MatchRequest.model_validate(supplied).model_dump(mode="json")
        return target, validate_match(session, user_id, MatchRequest.model_validate(target))
    elif op == "unlink":
        target = UnlinkRequest.model_validate(supplied).model_dump(mode="json")
        validate_unlink(session, user_id, UnlinkRequest.model_validate(target))
        from app.services.budget_reconciliation import links

        previous = next(r for r in links(session, user_id) if r["id"] == target["link_id"])
    elif op == "continuity":
        if supplied.pop("coverage_confirmed", None) is not True:
            raise ValueError(
                "Confirm that the supplied take-home income, savings and expense coverage apply to every target month"
            )
        request = ContinuityRequest.model_validate(supplied)
        target = {**request.model_dump(mode="json"), "coverage_confirmed": True}
        preview = preview_batch(session, user_id, request, persist=False)
        if preview["questions"]:
            raise ValueError(" ".join(preview["questions"]))
        return target, preview
    else:
        previous = read_section(session, user_id, "review_preferences") or {}
        target = ReviewPreferences.model_validate(
            {**previous, **supplied, "confirmed": True}
        ).model_dump(mode="json")
    return target, {
        "previous": previous,
        "proposed": target,
        "note": "Listed collections replace the previous collection in full. Other top-level settings are preserved. No money is moved or transactions created.",
    }


def preview_change(session, user_id, change):
    lock_workspace(session, user_id)
    try:
        target, details = build_change(session, user_id, change)
    except ValidationError as error:
        issues = [
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in error.errors(include_input=False, include_url=False)
        ]
        raise ValueError("Please supply or correct: " + "; ".join(issues)) from error
    return {
        "preview_id": str(uuid4()),
        "operation": change.operation,
        "target": target,
        "details": details,
        "labels": context(session, user_id),
        "evidence": evidence(session, user_id),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }


def confirm_change(session, user_id, pending):
    from app.services.budget_constraints import AllocationPolicy, save_policy
    from app.services.budget_continuity import (
        BatchConfirmation,
        ReviewPreferences,
        confirm_batch,
    )
    from app.services.budget_reconciliation import (
        MatchRequest,
        UnlinkRequest,
        save_match,
        save_settings,
        unlink,
    )
    from app.services.cashflow import CashflowSettings

    lock_workspace(session, user_id)
    if (
        datetime.fromisoformat(pending["expires_at"]) < datetime.now(UTC)
        or evidence(session, user_id) != pending["evidence"]
    ):
        raise ValueError(
            "This preview expired or its financial records/settings changed. Request a fresh preview before confirming"
        )
    op, target = pending["operation"], pending["target"]
    if op == "cashflow":
        return save_settings(session, user_id, CashflowSettings.model_validate(target))
    if op == "commitments":
        return save_policy(session, user_id, AllocationPolicy.model_validate(target))
    if op == "reserves":
        from app.services.budget_reserves import Reserves
        return write_section(session, user_id, "reserves", Reserves.model_validate(target).model_dump(mode="json"))
    if op == "timing":
        from app.services.budget_timing import TimingSettings
        settings = TimingSettings.model_validate(target)
        return write_section(session, user_id, "timing:" + str(settings.period_start), settings.model_dump(mode="json"))
    if op == "reconcile":
        return save_match(session, user_id, MatchRequest.model_validate(target))
    if op == "unlink":
        return unlink(session, user_id, UnlinkRequest.model_validate(target))
    if op == "continuity":
        preview = pending["details"]
        return confirm_batch(
            session,
            user_id,
            BatchConfirmation(preview_id=preview["preview_id"], confirmed=True),
            chat_preview=preview,
        )
    return write_section(
        session,
        user_id,
        "review_preferences",
        ReviewPreferences.model_validate(target).model_dump(mode="json"),
    )


def describe_preview(preview):
    import re

    def safe(value):
        return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", str(value)).replace("\n", " ")

    def money(value):
        return f"SGD {value:,.2f}"

    op, target, details = preview["operation"], preview["target"], preview["details"]
    owned = preview["labels"]
    bills = {
        s["id"]: s["name"] for s in (owned["settings"].get("cashflow") or {}).get("schedules", [])
    }
    goals = {g["id"]: g["name"] for g in owned["goals"]}
    lines = ["Review proposed planning changes:"]
    if op == "cashflow":
        for heading, settings in (
            ("Previously saved", details["previous"]),
            ("Proposed replacement", target),
        ):
            lines.append(heading + ":")
            if not settings:
                lines.append("No saved cash-flow settings.")
                continue
            lines.append(
                f"Opening balance {money(settings['opening_balance'])} at the start of {settings['opening_on']}."
            )
            for s in settings["schedules"]:
                lines.append(
                    f"- {safe(s['name'])}: {money(s['amount'])} {s['kind']}, category {safe(s['category'])}, {s['frequency']} from {s['first_on']}, end {s.get('last_on') or 'not set'}; manually settled dates: {', '.join(s.get('settled_dates', [])) or 'none'}."
                )
            if not settings["schedules"]:
                lines.append("No schedules.")
    elif op == "commitments":
        lines.append(f"Commitments for {target['period_start']}:")
        lines.append(
            f"Minimum savings {money(target['minimum_savings'])}; maximum reduction {target['max_reduction_percent']}% against the currently saved category limits."
        )
        lines.append(
            "Protected categories: "
            + (", ".join(safe(c) for c in target["protected_categories"]) or "none")
        )
        lines.append(
            "Category minimums: "
            + (
                "; ".join(f"{safe(k)} {money(v)}" for k, v in target["category_floors"].items())
                or "none"
            )
        )
        lines.append(
            "Goal contributions (within savings): "
            + (
                "; ".join(
                    f"{safe(goals.get(g['goal_id'], g['goal_id']))} {money(g['monthly_amount'])}/month"
                    for g in target["goals"]
                )
                or "none"
            )
        )
        lines.append("Debt commitments:")
        for d in target["debts"]:
            relationship = (
                "separate obligation"
                if d["separate_obligation"]
                else "linked to " + safe(bills[d["schedule_id"]])
            )
            lines.append(
                f"- {safe(d['name'])}: balance {money(d['balance'])}, minimum {money(d['minimum_payment'])}/month, category {safe(d['category'])}; {relationship}."
            )
        if not target["debts"]:
            lines.append("None.")
        lines.append(
            "These lists replace the previous commitments for this month in full. Budget limits and goal balances will not change."
        )
    elif op == "reserves":
        from app.services.budget_continuity import local_today
        from app.services.budget_reserves import Reserves, reserve_report
        report = reserve_report(Reserves.model_validate(target), local_today().replace(day=1))
        lines.append("Replace the saved irregular-expense reserve list with:")
        for r in report["reserves"]:
            lines.append(f"{safe(r['name'])}: target {money(r['target_amount'])}, already reserved {money(r['current_reserved'])}, contribute {money(r['monthly_contribution'])}/month from {r['start_period']} through {r['due_on']}; projected unfunded gap {money(r['projected_gap'])}.")
        lines.append(report["warning"])
    elif op == "timing":
        lines.append(f"For {target['period_start']}, spend remaining expense limits using {target['expense_pattern'].replace('_', ' ')} from {target['start_on']}; reserve the plan's savings on {target['savings_on']}; maintain at least {money(target['minimum_balance'])} available. You confirmed recorded expenses and bill/payday schedules are complete.")
    elif op == "reconcile":
        effects = {
            "payment": "payment",
            "refund_reopens": "refund that makes the amount payable again",
            "refund_reduces_due": "refund that reduces the bill amount",
        }
        lines.append(
            f"Match {money(target['amount'])} from {safe(details['transaction'])} to {safe(details['bill'])}, due {target['due_on']}, as a {effects[target['effect']]}."
        )
        lines.append(
            f"Remaining bill amount: {money(details['before']['remaining'])} → {money(details['after']['remaining'])}. Transaction amount left unmatched: {money(details['transaction_unallocated'])}."
        )
    elif op == "unlink":
        row = details["previous"]
        lines.append(
            f"Remove the {row['effect'].replace('_', ' ')} match of {money(row['amount'])} to {safe(bills[row['schedule_id']])}, due {row['due_on']}. Keep the recorded transaction and recalculate the unpaid bill amount."
        )
    elif op == "continuity":
        lines.append(
            f"Source month {target['source_period']}; rule {target['carry_rule'].replace('_', ' ')}."
        )
        for row in details["plans"]:
            plan = row["budget"]
            lines.append(
                f"{plan['period_start']}: {'REPLACE saved plan' if row['replaces_existing'] else 'new plan'}; take-home income {money(plan['planning']['take_home_income'])}, savings {money(plan['planning']['savings_target'])}, unallocated {money(row['unallocated'])}."
            )
            lines.extend(
                f"- {safe(c['category'])}: {money(c['limit_amount'])}" for c in plan["categories"]
            )
        lines.extend(details["warnings"])
    else:
        lines.append(
            f"In-app reviews {'enabled' if target['enabled'] else 'disabled'}; frequency {target['cadence']}; next review {target['next_review_on'] or 'not scheduled'}."
        )
    lines.append(
        "Nothing has been saved. Reply 'confirm budget' to apply this exact preview, 'cancel' to discard, or send corrections. No money is moved."
    )
    return "\n\n".join(lines)
