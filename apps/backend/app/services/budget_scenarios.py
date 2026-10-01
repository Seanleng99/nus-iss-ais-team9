"""Compare isolated copies; a comparison cannot authorize a budget write."""

from app.services.budget_methods import describe_method, method_report
from app.services.budget_planning import PlanningInputs, affordability


def compare_draft(draft, existing_categories=None):
    from app.services.budget_capture import DraftCategory

    base = draft.model_copy(deep=True)
    original_names = [" ".join((item.category or "").split()).lower() for item in base.categories]
    if len(original_names) != len(set(original_names)):
        return {
            "results": [],
            "questions": ["Provide one amount per category; duplicates are ambiguous."],
            "saved": False,
        }
    merged = {
        name: {"category": name, "limit_amount": amount}
        for name, amount in (existing_categories or {}).items()
    }
    merged.update(
        {
            " ".join((item.category or "").split()).lower(): item.model_dump(mode="json")
            for item in base.categories
        }
    )
    if len(merged) > 50:
        return {
            "results": [],
            "questions": ["The resulting budget exceeds 50 categories."],
            "saved": False,
        }
    base.categories = [DraftCategory.model_validate(item) for item in merged.values()]
    base.planning = base.planning or PlanningInputs()
    names = [scenario.name.casefold() for scenario in draft.scenarios]
    if len(names) != len(set(names)) or "current plan" in names:
        return {
            "results": [],
            "questions": ["Choose unique scenario names other than Current plan."],
            "saved": False,
        }
    candidates = [("Current plan", base)]
    for scenario in draft.scenarios:
        candidate = base.model_copy(deep=True)
        if scenario.take_home_income is not None:
            candidate.planning.take_home_income = scenario.take_home_income
            # This is explicitly a hypothetical take-home amount, not a profile update.
            candidate.planning.income_basis = "take_home"
        if scenario.savings_target is not None:
            candidate.planning.savings_target = scenario.savings_target
        if scenario.method is not None:
            candidate.planning.method = scenario.method.model_copy(deep=True)
        overrides = {
            " ".join((item.category or "").split()).lower(): item for item in scenario.categories
        }
        existing = {
            " ".join((item.category or "").split()).lower(): item for item in candidate.categories
        }
        existing.update(overrides)
        candidate.categories = list(existing.values())
        # Validate raw overrides too: do not silently collapse duplicate/unnamed categories.
        raw = candidate.model_copy(update={"categories": scenario.categories})
        raw_errors = raw.missing() if scenario.categories else []
        candidate.questions = list(dict.fromkeys([*candidate.questions, *raw_errors]))
        candidates.append((scenario.name, candidate))
    results = []
    for name, candidate in candidates:
        candidate.action = "plan"
        candidate.scenarios = []
        save_questions = candidate.planning.questions()
        coverage_question = "Do these category limits include all your expenses"
        questions = list(dict.fromkeys([*candidate.missing(), *(q for q in save_questions if not q.startswith(coverage_question))]))
        totals = None
        method = None
        if len(candidate.categories) > 50:
            questions.append("The resulting budget exceeds 50 categories.")
        elif candidate.currency == "SGD" and all(
            item.category and item.limit_amount is not None for item in candidate.categories
        ):
            categories = {
                " ".join(item.category.split()).lower(): item.limit_amount
                for item in candidate.categories
            }
            method = method_report(categories, candidate.planning)
            questions.extend(method["questions"])
            if (
                candidate.currency == "SGD"
                and candidate.planning.income_basis == "take_home"
                and candidate.planning.take_home_income is not None
                and candidate.planning.savings_target is not None
            ):
                totals = affordability(categories, candidate.planning)
        results.append(
            {
                "name": name,
                "draft": candidate.model_dump(mode="json"),
                "totals": totals,
                "method": method,
                "questions": list(dict.fromkeys(questions)),
                "save_questions": save_questions,
                "fits_income": totals is not None and totals["funding_gap"] == 0,
            }
        )
    baseline = results[0]["totals"]
    for result in results:
        result["unallocated_change"] = (
            round(result["totals"]["unallocated"] - baseline["unallocated"], 2)
            if baseline and result["totals"]
            else None
        )
    return {"results": results, "questions": [], "saved": False}


def apply_saved_constraints(session, user_id, comparison):
    """Read-only checks share the same saved restrictions as the write path."""
    from datetime import date

    from app.services.budget_constraints import constraint_questions

    for result in comparison.get("results", []):
        draft = result["draft"]
        if draft.get("period_start") and draft.get("currency") == "SGD" and result.get("totals"):
            questions = constraint_questions(session, user_id, date.fromisoformat(draft["period_start"]),
                {c["category"]: c["limit_amount"] for c in draft["categories"]}, PlanningInputs.model_validate(draft["planning"]))
            result["questions"] = list(dict.fromkeys([*result["questions"], *questions]))
            result["meets_saved_constraints"] = not questions
    return comparison


def describe_comparison(comparison):
    lines = ["Budget scenario comparison — nothing has been saved or selected."]
    lines.extend(comparison["questions"])
    for result in comparison["results"]:
        lines.append(result["name"] + ":")
        if result["totals"]:
            totals = result["totals"]
            planning = result["draft"]["planning"]
            lines.append(
                f"Take-home SGD {planning['take_home_income']:,.2f}; expenses SGD {totals['expense_total']:,.2f}; savings SGD {planning['savings_target']:,.2f}; unallocated SGD {totals['unallocated']:,.2f}; funding gap SGD {totals['funding_gap']:,.2f}."
            )
            if result["name"] != "Current plan":
                if totals["funding_gap"]:
                    lines.append(f"This option is short by SGD {totals['funding_gap']:,.2f}. Which amount would you like to revise?")
                else:
                    lines.append(f"This option fits the supplied monthly income, leaving SGD {totals['unallocated']:,.2f} unallocated. Cash availability before payday has not been established.")
        if result["method"]:
            lines.append(describe_method(result["method"]))
        if result.get("cashflow"):
            cash = result["cashflow"]
            lines.extend(cash["questions"])
            if cash.get("lowest_available") is not None:
                lines.append(f"Cash-flow status: {cash['status']}; lowest spendable balance after savings SGD {cash['lowest_available']:,.2f}; minimum balance SGD {cash['minimum_balance']:,.2f}; first below minimum: {cash['first_below_buffer_on'] or 'none'}.")
                lines.extend(cash.get("suggestions", []))
        lines.extend(result["questions"])
    if comparison["results"]:
        options = [item for item in comparison["results"] if item["name"] != "Current plan"]
        lines.append("Reply 'use this change' to review the option as a draft, then confirm the actual income, expenses and exact changes before saving."
            if len(options) == 1 else (
            "Reply 'use scenario NAME' to adopt one as an unsaved draft. Then confirm actual income, expense coverage and the exact changes before saving. Hypothetical amounts do not update your profile."
        ))
    return "\n\n".join(lines)
