"""Read-only tool results remain visible when optional education is unavailable."""

from coach_i18n import translate


def budget_calculation_summary(grounding):
    locale = grounding.get("response_language")
    capacity = grounding.get("capacity", {})
    source = grounding.get("capacity_source")
    if source == "confirmed_plan":
        return translate("budget.saved_calculation", locale,
                         period=capacity["period_start"], income=f"{capacity['take_home_income']:,.2f}",
                         expenses=f"{capacity['planned_expenses']:,.2f}",
                         savings=f"{capacity['estimated_savings_capacity']:,.2f}",
                         unallocated=f"{capacity['unallocated_income']:,.2f}")
    if source == "illustrative_fallback":
        return translate("budget.illustrative_calculation", locale,
                         period=capacity.get("period_start") or grounding.get("period_start") or "—",
                         income=f"{grounding['income']:,.2f}",
                         expenses=f"{grounding['recurring_expenses']:,.2f}",
                         disposable=f"{grounding['disposable_income']:,.2f}",
                         savings=f"{grounding['savings']:,.2f}")
    if source == "period_plans":
        return "\n".join(budget_calculation_summary({"capacity": row, "capacity_source": row.get("source"),
                                                    "response_language": locale})
                         for row in capacity.get("periods", []))
    return " ".join(grounding.get("questions", []) or ([capacity["reason"]] if capacity.get("reason") else []))


def goal_calculation_summary(grounding):
    locale = grounding.get("response_language")
    lines = [translate("goal.required_calculation", locale, name=row["name"],
                       required=f"{row['monthly_required']:,.2f}")
             for row in grounding.get("projections", [])]
    capacity = grounding.get("monthly_savings_capacity", {})
    combined = grounding.get("combined_feasibility")
    for row in grounding.get("period_feasibility", []):
        if row["monthly_capacity"] is None:
            lines.append(translate("goal.unavailable_capacity", locale, period=row["period_start"]))
        else:
            lines.append(translate("goal.combined_calculation", locale,
                                   period=row["period_start"], required=f"{row['monthly_required']:,.2f}",
                                   capacity=f"{row['monthly_capacity']:,.2f}",
                                   shortfall=f"{row['monthly_shortfall']:,.2f}"))
    if combined:
        lines.append(translate("goal.combined_calculation", locale,
                               period=capacity.get("period_start") or "—",
                               required=f"{combined['monthly_required']:,.2f}",
                               capacity=f"{combined['monthly_capacity']:,.2f}",
                               shortfall=f"{combined['monthly_shortfall']:,.2f}"))
        if capacity.get("source") == "illustrative_fallback":
            lines.append(translate("goal.illustrative_capacity", locale))
    lines.extend(grounding.get("questions", []))
    return "\n".join(lines)
