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
        questions = list(dict.fromkeys([*candidate.missing(), *candidate.planning.questions()]))
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
        if result["method"]:
            lines.append(describe_method(result["method"]))
        lines.extend(result["questions"])
    if comparison["results"]:
        lines.append(
            "Reply 'use scenario NAME' to adopt one as an unsaved draft. Then confirm actual income, expense coverage and the exact changes before saving. Hypothetical amounts do not update your profile."
        )
    return "\n\n".join(lines)
