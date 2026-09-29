"""Interactive method exploration; comparisons never save automatically."""

import json
from hashlib import sha256

import pandas as pd
import streamlit as st

from ui.components import backend_call, money

METHODS = {
    "flexible": "Flexible category plan",
    "50_30_20": "50/30/20",
    "80_20": "80/20",
    "zero_based": "Zero-based",
    "pay_yourself_first": "Savings first",
    "custom": "Custom percentages",
}
DESCRIPTIONS = {
    "flexible": "Choose category limits and a savings amount, with room for unallocated income.",
    "50_30_20": "Compare needs, wants and savings with 50%, 30% and 20% of full take-home income. You classify your categories.",
    "80_20": "Compare total expenses with 80% and savings with 20% of full take-home income.",
    "zero_based": "Assign every dollar to an expense category or savings. Saving requires no unallocated income or funding gap.",
    "pay_yourself_first": "Reserve your chosen savings amount first, then check whether expenses fit the remainder.",
    "custom": "Choose needs, wants and savings percentages totaling 100%. You classify your categories.",
}


def _method_details(chosen, prior, categories, scope, label_prefix=""):
    method = {"name": chosen, "category_groups": {}}
    if chosen == "custom":
        columns = st.columns(3)
        percentages = prior.get("percentages") or {}
        method["percentages"] = {
            name: columns[i].number_input(
                f"{label_prefix}{name.title()} percentage",
                min_value=0.0,
                max_value=100.0,
                value=float(percentages[name]) if name in percentages else None,
                step=1.0,
                key=f"{scope}-{name}-pct",
            )
            for i, name in enumerate(("needs", "wants", "savings"))
        }
    if chosen in {"50_30_20", "custom"}:
        for category in categories:
            choices = ["Choose", "needs", "wants"]
            group = st.selectbox(
                f"{label_prefix}Classify {category}",
                choices,
                index=choices.index(prior.get("category_groups", {}).get(category, "Choose")),
                key=f"{scope}-{chosen}-{category}-group",
            )
            if group != "Choose":
                method["category_groups"][category] = group
    return method


def render_method_explorer(client, user_id, period, categories, planning, scope, draft_key):
    with st.expander("Explore budgeting methods and scenarios", icon=":material/compare_arrows:"):
        st.caption(
            "Compare hypothetical monthly amounts without changing your saved budget. Percentage targets are guidance; category amounts and savings stay under your control."
        )
        chosen = st.selectbox(
            "Budgeting method",
            list(METHODS),
            format_func=METHODS.get,
            index=list(METHODS).index((planning or {}).get("method", {}).get("name", "flexible")),
            key=f"{scope}-method",
        )
        st.info(DESCRIPTIONS[chosen])
        method = _method_details(chosen, (planning or {}).get("method", {}), categories, scope)
        columns = st.columns(2)
        income = columns[0].number_input(
            "Scenario monthly take-home income (SGD)",
            min_value=0.0,
            value=float(planning["take_home_income"]) if planning else None,
            step=100.0,
            key=f"{scope}-compare-income",
        )
        savings = columns[1].number_input(
            "Scenario monthly savings (SGD)",
            min_value=0.0,
            value=float(planning["savings_target"]) if planning else None,
            step=50.0,
            key=f"{scope}-compare-savings",
        )
        st.caption(
            "The current option uses the category amounts in the editor above. Enter a change below to compare a second option."
        )
        scenario_income = st.number_input(
            "Alternative take-home income (SGD)",
            min_value=0.0,
            value=None,
            step=100.0,
            key=f"{scope}-alternative-income",
        )
        scenario_savings = st.number_input(
            "Alternative savings (SGD)",
            min_value=0.0,
            value=None,
            step=50.0,
            key=f"{scope}-alternative-savings",
        )
        alternative_method = st.selectbox(
            "Alternative method",
            ["same", *METHODS],
            format_func=lambda key: "Same method" if key == "same" else METHODS[key],
            key=f"{scope}-alternative-method",
        )
        changed = st.selectbox(
            "Alternative category",
            ["No category change", *categories],
            key=f"{scope}-alternative-category",
        )
        changed_amount = (
            st.number_input(
                "Alternative category limit (SGD)",
                min_value=0.0,
                value=None,
                step=25.0,
                key=f"{scope}-alternative-limit",
            )
            if changed != "No category change"
            else None
        )
        complete_percentages = chosen != "custom" or all(
            value is not None for value in method["percentages"].values()
        )
        scenario = {
            "name": "Alternative",
            "take_home_income": scenario_income,
            "savings_target": scenario_savings,
            "categories": [{"category": changed, "limit_amount": changed_amount}]
            if changed != "No category change"
            else [],
        }
        if alternative_method != "same":
            scenario["method"] = _method_details(
                alternative_method, {}, categories, f"{scope}-alternative", "Alternative "
            )
            complete_percentages = complete_percentages and (
                alternative_method != "custom"
                or all(value is not None for value in scenario["method"]["percentages"].values())
            )
        payload = {
            "period_start": period.isoformat(),
            "currency": "SGD",
            "action": "compare",
            "categories": [
                {"category": key, "limit_amount": value} for key, value in categories.items()
            ],
            "planning": {
                "take_home_income": income,
                "income_basis": "take_home" if income is not None else "unknown",
                "savings_target": savings,
                "expenses_confirmed": False,
                "method": method,
            },
            "scenarios": [scenario],
        }
        signature = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        result_key = f"{scope}-comparison"
        if st.button("Compare scenarios", key=f"{scope}-compare"):
            if not complete_percentages:
                st.warning("Enter all three custom percentages before comparing.")
            else:
                result = backend_call(lambda: client.compare_budget(user_id, payload))
                if result:
                    st.session_state[result_key] = (signature, result)
        stored = st.session_state.get(result_key)
        if not stored or stored[0] != signature:
            return
        comparison = stored[1]
        for question in comparison.get("questions", []):
            st.warning(question)
        results = comparison.get("results", [])
        if not results:
            return
        rows = []
        for result in results:
            totals = result.get("totals") or {}
            inputs = result["draft"]["planning"]
            rows.append(
                {
                    "Option": result["name"],
                    "Income": inputs.get("take_home_income"),
                    "Expenses": totals.get("expense_total"),
                    "Savings": inputs.get("savings_target"),
                    "Unallocated": totals.get("unallocated"),
                    "Funding gap": totals.get("funding_gap"),
                }
            )
            report = result.get("method") or {}
            st.markdown(f"**{result['name']} · {report.get('label', 'Method pending')}**")
            if report.get("targets"):
                st.caption(
                    "Guidance: "
                    + "; ".join(
                        f"{name}: {money(value)}" for name, value in report["targets"].items()
                    )
                )
            for warning in report.get("warnings", []):
                st.warning(warning)
            for question in result.get("questions", []):
                st.caption(question)
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        complete = [
            row
            for row in rows
            if all(
                row[key] is not None
                for key in ("Expenses", "Savings", "Unallocated", "Funding gap")
            )
        ]
        if complete:
            import plotly.graph_objects as go

            chart = go.Figure()
            for field, color in (
                ("Expenses", "#64748b"),
                ("Savings", "#0d9488"),
                ("Unallocated", "#cbd5e1"),
            ):
                chart.add_bar(
                    name=field,
                    x=[row["Option"] for row in complete],
                    y=[row[field] for row in complete],
                    marker_color=color,
                )
            chart.update_layout(
                barmode="stack", yaxis_title="SGD", height=300, margin={"t": 10, "b": 10}
            )
            st.plotly_chart(chart, use_container_width=True, key=f"{scope}-scenario-chart")
        selected = st.selectbox(
            "Option to adopt", [row["name"] for row in results], key=f"{scope}-adopt-option"
        )
        if st.button("Use option in editor", key=f"{scope}-adopt"):
            candidate = next(row["draft"] for row in results if row["name"] == selected)
            inputs = candidate["planning"]
            if (
                inputs["take_home_income"] is None
                or inputs["savings_target"] is None
                or not candidate["categories"]
                or any(item["limit_amount"] is None for item in candidate["categories"])
            ):
                st.warning(
                    "Supply income, savings and every category amount before adopting this option."
                )
                return
            st.session_state[draft_key] = candidate
            st.rerun()
