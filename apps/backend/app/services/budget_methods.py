"""Authoritative, read-only method guidance and what-if arithmetic."""

from decimal import ROUND_HALF_UP, Decimal

from app.domain.budget_methods import METHOD_LABELS


def method_report(categories, planning):
    method = planning.method
    questions = method.questions(categories)
    result = {
        "name": method.name,
        "label": METHOD_LABELS[method.name],
        "targets": {},
        "actual": {},
        "warnings": [],
        "questions": questions,
    }
    if planning.take_home_income is None or planning.income_basis != "take_home":
        return result
    income = Decimal(str(planning.take_home_income))
    expenses = sum((Decimal(str(value)) for value in categories.values()), Decimal(0))
    savings = Decimal(str(planning.savings_target)) if planning.savings_target is not None else None
    percentages = None
    if method.name == "50_30_20":
        percentages = {"needs": 50, "wants": 30, "savings": 20}
    elif method.name == "custom" and method.percentages and not method.questions([]):
        percentages = method.percentages.model_dump()
    if percentages:
        # Assign any rounding cent to savings so targets sum exactly to income.
        needs = (income * Decimal(str(percentages["needs"])) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        wants = (income * Decimal(str(percentages["wants"])) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # Rounding two buckets upward on a tiny income must not make savings negative.
        wants = min(wants, income - needs)
        result["targets"] = {
            "needs": float(needs),
            "wants": float(wants),
            "savings": float(income - needs - wants),
        }
        if not questions:
            result["actual"] = {
                group: float(
                    sum(
                        (
                            Decimal(str(value))
                            for name, value in categories.items()
                            if method.category_groups[name] == group
                        ),
                        Decimal(0),
                    )
                )
                for group in ("needs", "wants")
            }
    elif method.name == "80_20":
        target_savings = (income * Decimal("0.20")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        result["targets"] = {
            "expenses": float(income - target_savings),
            "savings": float(target_savings),
        }
        result["actual"] = {"expenses": float(expenses)}
    elif method.name == "pay_yourself_first" and savings is not None:
        result["targets"] = {"expenses": float(income - savings), "savings": float(savings)}
        result["actual"] = {"expenses": float(expenses)}
    if savings is not None:
        result["actual"]["savings"] = float(savings)
        balance = income - expenses - savings
        if method.name == "zero_based" and balance != 0:
            questions.append(
                "Zero-based budgeting assigns all take-home income. Revise expenses or savings until unallocated income and funding gap are both zero, or select another method."
            )
    for group, target in result["targets"].items():
        actual = result["actual"].get(group)
        if actual is None:
            continue
        if (group == "savings" and actual < target) or (group != "savings" and actual > target):
            result["warnings"].append(
                f"{group.title()}: SGD {actual:,.2f} versus method target SGD {target:,.2f}. This is guidance; no amounts were changed."
            )
    return result


def describe_method(report):
    lines = ["Method: " + report["label"] + "."]
    if report["targets"]:
        lines.append(
            "Guidance based on full take-home income: "
            + "; ".join(f"{name}: SGD {value:,.2f}" for name, value in report["targets"].items())
            + "."
        )
    lines.extend(report["warnings"])
    return " ".join(lines)
