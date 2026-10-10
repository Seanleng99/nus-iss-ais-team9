import html
import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime
from urllib.parse import quote

import httpx
import pandas as pd
import streamlit as st
from coach_i18n import resolve_locale, translate

from client import build_request
from ui.budget_methods import METHODS
from ui.budget_page import render_budget_page
from ui.budget_timing import render_timing_summary
from ui.coach_language import (
    apply_profile_default,
    current_selection,
    explicit_selection,
    sync_response_locale,
)
from ui.components import backend_call, clamp_progress, money, page_header, percent
from ui.currency_markdown import currency_safe_markdown
from ui.i18n import (
    display_frame,
    month_formatter,
    month_label,
    option_formatter,
    option_label,
    ui_message,
    ui_text,
)
from ui.response_metadata import response_metadata
from ui.state import get_client, get_period_start, get_user_id
from ui.telemetry import call_span, context_fields, log_event, trace_context
from ui.trace_viewer import trace_link

CATEGORIES = [
    "housing",
    "food",
    "transport",
    "utilities",
    "healthcare",
    "education",
    "entertainment",
    "shopping",
    "groceries",
    "dining out",
    "insurance",
    "subscriptions",
    "personal care",
    "fitness",
    "childcare",
    "family support",
    "pets",
    "travel",
    "gifts",
    "charity",
    "debt repayments",
    "savings",
    "other",
]
RISK_OPTIONS = ["conservative", "moderate", "growth"]
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EMPLOYMENT_OPTIONS = [
    "employed",
    "self-employed",
    "student",
    "unemployed",
    "retired",
    "prefer not to say",
]
OCCUPATION_OPTIONS = [
    "business and administration",
    "education",
    "engineering and technology",
    "healthcare",
    "hospitality and services",
    "public service",
    "sales and marketing",
    "skilled trades",
    "student",
    "other",
    "prefer not to say",
]
INCOME_FREQUENCY_OPTIONS = ["monthly", "fortnightly", "weekly", "irregular"]
INCOME_STABILITY_OPTIONS = ["stable", "variable", "seasonal", "not applicable"]
HOUSING_OPTIONS = [
    "family home",
    "renting",
    "homeowner with mortgage",
    "homeowner without mortgage",
    "other",
    "prefer not to say",
]
LITERACY_OPTIONS = ["beginner", "intermediate", "advanced"]
LANGUAGE_OPTIONS = ["English", "Mandarin"]
ACCESSIBILITY_OPTIONS = [
    "plain language",
    "shorter responses",
    "step-by-step explanations",
    "screen-reader friendly",
]
AGE_BANDS = ["18-20", "21-25", "26-30", "31-35", "Prefer not to say"]
GENDER_OPTIONS = ["Woman", "Man", "Non-binary", "Another identity", "Prefer not to say"]
RACE_ETHNICITY_OPTIONS = [
    "Chinese",
    "Malay",
    "Indian",
    "Eurasian",
    "Other",
    "Prefer not to say",
]
RESIDENCY_OPTIONS = [
    "Singapore citizen",
    "Permanent resident",
    "Work or student pass holder",
    "Other",
    "Prefer not to say",
]
DISABILITY_OPTIONS = [
    "No disability disclosed",
    "Disability disclosed",
    "Prefer not to say",
]
MARITAL_OPTIONS = [
    "Single",
    "Married or partnered",
    "Separated or divorced",
    "Widowed",
    "Prefer not to say",
]
REGION_OPTIONS = [
    "Central",
    "East",
    "North",
    "North-East",
    "West",
    "Outside Singapore",
    "Prefer not to say",
]
COACH_STARTERS = [
    ("coach.starter_spending", ":material/receipt_long:"),
    ("coach.starter_emergency", ":material/savings:"),
    ("coach.starter_budget", ":material/pie_chart:"),
    ("coach.starter_goal", ":material/flag:"),
]
AGENT_LABELS = {"spending", "budget", "goal_strategy", "investment_education", "risk_compliance"}


def _option_index(options: list[str], value: str | None) -> int | None:
    log_event("VV entering ", "ui.pages", "_option_index")
    return options.index(value) if value in options else None


def _category_label(category: str) -> str:
    log_event("VV entering ", "ui.pages", "_category_label")
    return option_label(category)


def _confidence_band(value: float, locale="en") -> str:
    log_event("VV entering ", "ui.pages", "_confidence_band")
    if value < 0.5:
        return translate("coach.confidence_low", locale)
    if value < 0.8:
        return translate("coach.confidence_moderate", locale)
    return translate("coach.confidence_high", locale)


def _agent_label(agent: str, locale) -> str:
    log_event("VV entering ", "ui.pages", "_agent_label")
    return (
        translate(f"coach.agent_{agent}", locale)
        if agent in AGENT_LABELS else agent.replace("_", " ").title()
    )


def _coach_reference(explanation, locale) -> str:
    log_event("VV entering ", "ui.pages", "_coach_reference")
    parts = []
    if explanation.get("trace_id"):
        parts.append(translate("coach.reference", locale, trace_id=explanation["trace_id"]))
    if explanation.get("prompt_set_version"):
        parts.append(translate("coach.prompt_set", locale, version=explanation["prompt_set_version"]))
    return " · ".join(parts)


def _render_coach_explanation(explanation: dict | None, locale="en") -> None:
    log_event("VV entering ", "ui.pages", "_render_coach_explanation")
    with (
        call_span(f"{__name__}._render_coach_explanation")
        if context_fields().get("correlation_id") else nullcontext()
    ):
        if not explanation:
            return
        with st.expander(translate("coach.explanation", locale)):
            st.caption(translate("coach.confidence_help", locale))
            if explanation.get("blocked"):
                st.warning(
                    translate('safety.ui_withheld_notice', locale)
                )
                trace_id = explanation.get("trace_id")
                reference = _coach_reference(explanation, locale)
                if reference:
                    st.caption(reference)
                trace_link(trace_id, locale)
                return
            selected_agents = explanation.get("selected_agents", [])
            if selected_agents:
                labels = [
                    _agent_label(agent, locale)
                    for agent in selected_agents
                ]
                st.markdown(translate("coach.areas", locale, areas=", ".join(labels)))
            routing_rationale = explanation.get("routing_rationale", [])
            if routing_rationale:
                st.markdown("**" + translate("coach.routing", locale) + "**")
                for rationale in routing_rationale:
                    st.markdown(currency_safe_markdown(f"- {rationale}"))
            for result in explanation.get("agent_results", []):
                agent = result.get("agent", "unknown")
                label = _agent_label(agent, locale)
                confidence = min(max(float(result.get("confidence", 0.0)), 0.0), 1.0)
                st.markdown(
                    "**" + translate(
                        "coach.agent_confidence", locale, agent=label,
                        band=_confidence_band(confidence, locale), score=f"{confidence:.2f}",
                    ) + "**"
                )
                for rationale in result.get("rationale", []):
                    text = (
                        translate("coach.missing_input", locale)
                        if rationale == "MISSING_REQUIRED_INPUT" else rationale
                    )
                    st.markdown(currency_safe_markdown(f"- {text}"))
            trace_id = explanation.get("trace_id")
            reference = _coach_reference(explanation, locale)
            if reference:
                st.caption(reference)
            trace_link(trace_id, locale)


def _transaction_payload(
    description: str,
    category: str,
    amount: float,
    occurred_on: date,
    recurring: bool,
    recurrence: dict | None = None,
) -> dict:
    log_event("VV entering ", "ui.pages", "_transaction_payload")
    return {
        "description": description.strip(),
        "category": category,
        "amount": {"currency": "SGD", "amount": amount},
        "occurred_on": occurred_on.isoformat(),
        "recurring": recurring,
        "recurrence": recurrence if recurring else None,
    }


def _recurrence_fields(key, existing=None):
    log_event("VV entering ", "ui.pages", "_recurrence_fields")
    existing = existing or {}
    options = ["unknown", "once", "weekly", "fortnightly", "monthly", "yearly"]
    with st.expander(ui_text("Recurring schedule (optional)")):
        frequency = st.selectbox(ui_text("Repeat frequency"), options,
            index=options.index(existing.get("frequency", "unknown")),
            format_func=option_formatter(), key=f"{key}-frequency")
        interval = st.number_input(ui_text("Every"), min_value=1, max_value=120,
            value=int(existing.get("interval", 1)), step=1, key=f"{key}-interval")
        first_on = st.date_input(ui_text("First scheduled date"),
            value=date.fromisoformat(existing["first_on"]) if existing.get("first_on") else None,
            key=f"{key}-first")
        next_due = st.date_input(ui_text("Next due date"),
            value=date.fromisoformat(existing["next_due_on"]) if existing.get("next_due_on") else None,
            key=f"{key}-next")
        last_on = st.date_input(ui_text("Last scheduled date (optional)"),
            value=date.fromisoformat(existing["last_on"]) if existing.get("last_on") else None,
            key=f"{key}-last")
        month_end = st.checkbox(ui_text("On the last day of the month"),
            value=bool(existing.get("month_end", False)),
            key=f"{key}-month-end")
        if frequency == "unknown":
            st.caption(ui_text("Frequency is unknown until you provide a schedule."))
            return None
        return {"frequency": frequency, "interval": interval,
                "month_end": bool(month_end) if frequency in {"monthly", "yearly"} else False,
                "first_on": first_on.isoformat() if first_on else None,
                "next_due_on": next_due.isoformat() if next_due else None,
                "last_on": last_on.isoformat() if last_on else None}


def _create_pie_chart(categories: list[str], amounts: list[float], currency: str):
    """
    Create a pie chart for spending category distribution.
    Returns None if plotly is not available.
    """
    log_event("VV entering ", "ui.pages", "_create_pie_chart")
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
    
    # Color palette for categories
    colors = [
        "#18794e",  # Green
        "#2563eb",  # Blue
        "#dc2626",  # Red
        "#d97706",  # Amber
        "#7c3aed",  # Purple
        "#db2777",  # Pink
        "#0891b2",  # Cyan
        "#65a30d",  # Lime
        "#ea580c",  # Orange
        "#4f46e5",  # Indigo
    ]
    
    fig = go.Figure(data=[
        go.Pie(
            labels=categories,
            values=amounts,
            hole=0.4,  # Donut chart
            marker={"colors": colors[:len(categories)]},
            textinfo="percent",
            hoverinfo="label+value+percent",
            textposition="outside",
        )
    ])

    fig.update_layout(
        showlegend=False,
        margin={"t": 30, "b": 30, "l": 30, "r": 30},
        height=300,
    )
    
    return fig


def dashboard_page() -> None:
    log_event("VV entering ", "ui.pages", "dashboard_page")
    client = get_client()
    user_id = get_user_id()
    period_start = get_period_start()
    page_header(ui_text('Overview'), month_label(period_start))
    dashboard = backend_call(lambda: client.get_dashboard(user_id, period_start))
    if not dashboard:
        st.info(ui_text('Create a profile to start your financial workspace.'))
        return

    currency = dashboard["currency"]
    budget_alert = dashboard.get("budget_alert")
    if budget_alert:
        alert_categories = [
            item["category"].capitalize() for item in budget_alert["categories_over"]
        ]
        if budget_alert["status"] == "over":
            if budget_alert["over_income"]:
                st.error(
                    ui_text('🚨 You have spent {v0} this month — {v1} more than your monthly income of {v2}.', v0=money(budget_alert['total_spent'], currency), v1=money(budget_alert['amount_over_income'], currency), v2=money(budget_alert['monthly_income'], currency))
                )
            if (
                budget_alert["total_budget_limit"] > 0
                and budget_alert["total_spent"] > budget_alert["total_budget_limit"]
            ):
                detail = (
                    f" Categories over their limit: {', '.join(alert_categories)}."
                    if alert_categories
                    else ""
                )
                st.error(
                    ui_text('🚨 You are over your monthly budget of {v0}.{v1}', v0=money(budget_alert['total_budget_limit'], currency), v1=detail)
                )
            elif budget_alert["categories_over"]:
                detail = "; ".join(
                    f"{_category_label(item['category'])}: "
                    f"{money(item['spent'] - item['limit_amount'], currency)} over its limit"
                    for item in budget_alert["categories_over"]
                )
                st.warning(ui_text('Category limits exceeded — {v0}.', v0=detail))
        elif budget_alert["status"] == "approaching":
            usage_parts = []
            if budget_alert["income_usage_percent"] is not None:
                usage_parts.append(
                    f"{budget_alert['income_usage_percent']:.0f}% of your monthly income"
                )
            if budget_alert["budget_usage_percent"] is not None:
                usage_parts.append(
                    f"{budget_alert['budget_usage_percent']:.0f}% of your monthly budget"
                )
            warning_categories = [
                item["category"].capitalize()
                for item in budget_alert["categories_at_limit"]
            ]
            category_detail = (
                f" Close to their limit: {', '.join(warning_categories)}."
                if warning_categories
                else ""
            )
            st.warning(
                ui_text('⚠️ Approaching your limits: you have used {v0} this month.{v1}', v0=' and '.join(usage_parts), v1=category_detail)
            )
    income, spent = st.columns(2)
    income.metric(ui_text('Monthly income'), money(dashboard["monthly_income"], currency))
    spent.metric(ui_text('Spent'), money(dashboard["total_spent"], currency))
    balance, rate = st.columns(2)
    balance.metric(ui_text('Available'), money(dashboard["available_balance"], currency))
    rate.metric(ui_text('Savings rate'), percent(dashboard["savings_rate_percent"]))

    st.subheader(ui_text('Spending'))
    
    # Add context description
    st.caption(ui_text("Track your spending patterns and get personalized insights to understand where your money goes each month. Add transactions regularly to unlock smarter analysis and recommendations."))
    
    # NEW: Render spending insights if available
    spending_insights = dashboard.get("spending_insights", [])
    spending_data_quality = dashboard.get("spending_data_quality", "insufficient")
    spending_months_analyzed = dashboard.get("spending_months_analyzed", 0)
    
    if spending_insights:
        from ui.spending_insights_component.spending_insights import (
            render_spending_insights_section,
        )
        render_spending_insights_section(spending_insights)
        
        # Show data quality indicator
        if spending_data_quality in ["limited", "insufficient"]:
            st.info(
                ui_text('💡 Keep adding transactions! You have {v0} month(s) of data so far — aim for at least 3 months to unlock more accurate insights and pattern detection.', v0=spending_months_analyzed)
            )
        elif spending_data_quality == "good":
            st.success(
                ui_text('✅ You have {v0} months of transaction data. Keep tracking to unlock even deeper insights!', v0=spending_months_analyzed)
            )
        else:  # excellent
            st.success(
                ui_text("✅ You have {v0}+ months of transaction data — you're getting the most accurate insights possible!", v0=spending_months_analyzed)
            )
    
    # Show category charts: Pie chart (distribution) + Bar chart (breakdown)
    category_spending = dashboard.get("category_spending", {})
    if category_spending:
        categories = [_category_label(name) for name in category_spending]
        amounts = list(category_spending.values())
        
        # Show summary metrics
        metric_cols = st.columns(2)
        metric_cols[0].metric(
            ui_text('Categories'),
            str(len(categories)),
            delta=None
        )
        metric_cols[1].metric(
            ui_text('Average per Category'),
            money(sum(amounts) / len(categories), currency) if categories else money(0, currency),
            delta=None
        )
        
        # Chart 1: Pie Chart - Category Distribution
        st.markdown(ui_text('#### Category Distribution'))
        st.markdown(
            "<div style='color: #6b7280; font-size: 13px; margin-bottom: 10px;'>",
            unsafe_allow_html=True,
        )
        st.markdown(
            ui_text('This chart shows how your spending is distributed across different categories as percentages. Each slice represents the proportion of your total spending for that category. Larger slices indicate categories where you spend a higher percentage of your budget. Hover over any slice to see the exact amount and percentage.')
        )
        st.markdown("</div>", unsafe_allow_html=True)
        
        pie_chart = _create_pie_chart(categories, amounts, currency)
        if pie_chart:
            st.plotly_chart(pie_chart, use_container_width=True, key="spending_pie_chart")
        else:
            st.info(ui_text('📊 Install plotly for pie chart: `pip install plotly`'))
        
        # Chart 2: Bar Chart - Category Breakdown
        st.markdown(ui_text('#### Category Breakdown'))
        st.markdown(
            "<div style='color: #6b7280; font-size: 13px; margin-bottom: 10px;'>",
            unsafe_allow_html=True,
        )
        st.markdown(
            ui_text('This chart displays the actual spending amounts for each category, making it easy to compare where your money is going. Categories are arranged to help you quickly identify your top spending areas. Use this view to spot categories that might need attention or budget adjustments.')
        )
        st.markdown("</div>", unsafe_allow_html=True)
        
        spending_frame = pd.DataFrame(
            {
                "Category": categories,
                "Amount": amounts,
            }
        ).set_index("Category")
        st.bar_chart(
            display_frame(spending_frame),
            horizontal=True,
            color="#18794e",
            use_container_width=True
        )
    else:
        st.info(
            ui_text("📝 **No transactions recorded yet**  Start by adding your transactions in the Transactions tab. As you add more data, you'll see your spending patterns visualized here with helpful insights.")
        )

    if (dashboard.get("review_reminder") or {}).get("due"):
        st.info(ui_message(dashboard["review_reminder"]["message"]), icon=":material/event:")
    _render_overview_budget(dashboard.get("budget"), currency)
    timing = dashboard.get("budget_timing")
    if timing and timing.get("status") in {"within_buffer", "shortfall"}:
        render_timing_summary(timing)

    st.subheader(ui_text('Goals'))
    goals = dashboard.get("goals", [])
    if not goals:
        st.caption(ui_text('No active goals.'))
    for goal in goals:
        left, right = st.columns([3, 1])
        left.write(f"**{goal['name']}**")
        right.write(money(goal["current_amount"], currency))
        st.progress(
            clamp_progress(goal["progress_percent"] / 100),
            text=ui_text('{v0:.0f}% of {v1}', v0=goal['progress_percent'], v1=money(goal['target_amount'], currency)),
        )


def _render_budget_plan_summary(budget: dict) -> None:
    log_event("VV entering ", "ui.pages", "_render_budget_plan_summary")
    planning = budget.get("planning")
    if not planning:
        return
    currency = budget.get("currency", "SGD")
    expenses = sum(float(item["limit_amount"]) for item in budget.get("categories", []))
    unallocated = round(planning["take_home_income"] - expenses - planning["savings_target"], 2)
    st.markdown(ui_text('**Plan affordability**'))
    st.caption(ui_text("Budgeting method: {v0}", v0=ui_text(METHODS.get(planning.get("method", {}).get("name", "flexible"), "Flexible category plan"))))
    columns = st.columns(3)
    columns[0].metric(ui_text('Take-home income'), money(planning["take_home_income"], currency))
    columns[1].metric(ui_text('Savings allocation'), money(planning["savings_target"], currency))
    columns[2].metric(ui_text('Unallocated income'), money(unallocated, currency))
    st.caption(ui_text('Savings are a planned allocation, separate from expense limits—not a recorded savings balance or transfer. Affordability depends on the income and expense coverage you confirmed.'))


def _render_overview_budget(budget: dict | None, currency: str) -> None:
    log_event("VV entering ", "ui.pages", "_render_overview_budget")
    st.subheader(":material/account_balance_wallet: " + ui_text("Budget"), anchor=False)
    st.caption(
        ui_text('Your monthly plan and the categories that need attention. Edit your plan in Budget. Ask Coach for spending reviews or pace illustrations.')
    )
    rows = (budget or {}).get("categories", [])
    if not rows:
        st.info(
            ui_text('No category limits set for this month. Add suggested or custom categories in Budget, or ask Coach to prepare a plan for your confirmation.'),
            icon=":material/pie_chart:",
        )
    else:
        import plotly.graph_objects as go

        currency = budget.get("currency", currency)
        _render_budget_plan_summary(budget)
        planned = float(budget["total_limit"])
        spent = float(budget["total_spent"])
        remaining = planned - spent
        over = [item for item in rows if item["spent_amount"] > item["limit_amount"]]
        with st.container(border=True):
            metrics = st.columns(3)
            metrics[0].metric(ui_text('Planned'), money(planned, currency))
            metrics[1].metric(ui_text('Spent'), money(spent, currency))
            metrics[2].metric(
                ui_text('Over budget') if remaining < 0 else ui_text('Remaining'), money(abs(remaining), currency)
            )
            unbudgeted = max(0.0, round(spent - sum(float(item["spent_amount"]) for item in rows), 2))
            st.caption(ui_text('Totals include all spending for the selected month.'))
            if unbudgeted > 0:
                st.info(
                    ui_text('{v0} was spent in categories without budget limits. Add limits in Budget to track these categories.', v0=money(unbudgeted, currency)),
                    icon=":material/info:",
                )
            chart_column, category_column = st.columns([1, 2])
            with chart_column:
                if planned > 0:
                    usage = spent / planned
                    chart = go.Figure(
                        go.Pie(
                            labels=[ui_text(v) for v in ["Within plan", "Remaining", "Over budget"]],
                            values=[min(spent, planned), max(remaining, 0), max(-remaining, 0)],
                            hole=0.76,
                            sort=False,
                            direction="clockwise",
                            marker={"colors": ["#0d9488", "#e2e8f0", "#dc2626"]},
                            textinfo="none",
                            hovertemplate=f"%{{label}}: {currency} %{{value:,.2f}}<extra></extra>",
                        )
                    )
                    chart.update_layout(
                        height=250,
                        margin={"l": 10, "r": 10, "t": 15, "b": 10},
                        showlegend=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                        annotations=[
                            {
                                "text": f"<b>{usage:.0%}</b><br>" + ui_text("of plan spent"),
                                "x": 0.5,
                                "y": 0.5,
                                "showarrow": False,
                                "font": {
                                    "size": 20,
                                    "color": "#dc2626" if usage > 1 else "#17211d",
                                },
                            }
                        ],
                    )
                    st.plotly_chart(chart, use_container_width=True, key="overview-budget-usage")
                    if usage > 1:
                        st.caption(ui_text('Over the monthly plan by {v0}.', v0=money(-remaining, currency)))
                    elif usage == 1:
                        st.caption(ui_text('The monthly plan is fully used.'))
                    else:
                        st.caption(ui_text('{v0} left in the monthly plan.', v0=money(remaining, currency)))
                else:
                    st.info(
                        ui_text('All category limits are zero. Set positive limits to see budget usage.')
                    )
            with category_column:
                st.markdown(ui_text('**Category limits**'))
                if over:
                    st.warning(
                        ui_text('{v0} category is over the limit.', v0=len(over))
                        if len(over) == 1 else ui_text('{v0} categories are over the limit.', v0=len(over)),
                        icon=":material/warning:",
                    )
                st.caption(ui_text('Highest usage first · up to 5 categories'))

                def usage_rank(item):
                    log_event("VV entering ", "ui.pages", "_render_overview_budget.usage_rank")
                    limit = float(item["limit_amount"])
                    actual = float(item["spent_amount"])
                    return actual / limit if limit > 0 else (float("inf") if actual > 0 else 0)

                ranked = sorted(rows, key=usage_rank, reverse=True)
                for item in ranked[:5]:
                    limit = float(item["limit_amount"])
                    actual = float(item["spent_amount"])
                    difference = limit - actual
                    status = (
                        ui_text("Over by {v0}", v0=money(-difference, currency))
                        if difference < 0
                        else ui_text("At limit")
                        if difference == 0
                        else ui_text("{v0} left", v0=money(difference, currency))
                    )
                    st.text(f"{_category_label(item['category'])} · {status}")
                    st.progress(
                        clamp_progress(actual / limit)
                        if limit > 0
                        else (1.0 if actual > 0 else 0.0),
                        text=ui_text('{v0} spent / {v1} planned', v0=money(actual, currency), v1=money(limit, currency)),
                    )
                if len(rows) > 5:
                    st.caption(ui_text('View all {v0} categories in Budget.', v0=len(rows)))
    if st.button(
        ui_text('View budget') if rows else ui_text('Set up budget'),
        icon=":material/edit:",
        key="overview-manage-budget",
    ):
        st.switch_page(st.Page(budget_page, title=ui_text('Budget'), url_path="budget"))


def transactions_page() -> None:
    log_event("VV entering ", "ui.pages", "transactions_page")
    client = get_client()
    user_id = get_user_id()
    period_start = get_period_start()
    page_header(ui_text('Transactions'), month_label(period_start))
    transactions = backend_call(lambda: client.list_transactions(user_id, period_start)) or []
    ledger_tab, add_tab = st.tabs([ui_text('Ledger'), ui_text('Add transaction')])

    with add_tab:
        with st.form("add-transaction", clear_on_submit=True):
            description = st.text_input(
                ui_text('Description'),
                max_chars=255,
                key=f"add-transaction-{user_id}-description-v2",
            )
            transaction_type = st.selectbox(ui_text('Transaction type'), ["expense", "income", "transfer", "refund"], format_func=option_formatter(), key=f"add-transaction-{user_id}-type")
            first, second = st.columns(2)
            category = first.selectbox(
                ui_text('Category'),
                CATEGORIES,
                index=None,
                format_func=option_formatter(),
                key=f"add-transaction-{user_id}-category-v2",
                accept_new_options=True,
            )
            amount = second.number_input(
                ui_text('Amount (SGD)'),
                min_value=0.0,
                value=0.0,
                step=10.0,
                key=f"add-transaction-{user_id}-amount-v2",
            )
            third, fourth = st.columns(2)
            occurred_on = third.date_input(
                ui_text('Date'), value=None, key=f"add-transaction-{user_id}-date-v2"
            )
            recurring = fourth.toggle(
                ui_text('Recurring expense'), key=f"add-transaction-{user_id}-recurring-v2"
            )
            recurrence = _recurrence_fields(f"add-transaction-{user_id}")
            add_submitted = st.form_submit_button(
                ui_text('Add transaction'), type="primary", icon=":material/add:"
            )
        if add_submitted:
            if not description.strip():
                st.warning(ui_text('Enter a transaction description.'))
            elif category is None:
                st.warning(ui_text('Select a transaction category.'))
            elif amount <= 0:
                st.warning(ui_text('Enter a transaction amount greater than zero.'))
            elif occurred_on is None:
                st.warning(ui_text('Select a transaction date.'))
            elif recurring and recurrence and (not recurrence["first_on"] or not recurrence["next_due_on"]):
                st.warning(ui_text('Enter the first scheduled date and next due date.'))
            else:
                result = backend_call(
                    lambda: client.create_transaction(
                        user_id,
                        {**_transaction_payload(description, category, amount, occurred_on, recurring, recurrence), "transaction_type": transaction_type},
                    )
                )
                if result:
                    st.success(ui_text('Transaction added.'))
                    st.rerun()

    with ledger_tab:
        if not transactions:
            st.info(ui_text('No transactions recorded for this month.'))
            return
        frame = pd.DataFrame(
            [
                {
                    "Date": item["occurred_on"],
                    "Description": item["description"],
                    "Type": option_label(item.get("transaction_type", "expense")),
                    "Category": _category_label(item["category"]),
                    "Amount": item["amount"]["amount"],
                    "Recurring": item["recurring"],
                }
                for item in transactions
            ]
        )
        st.dataframe(
            display_frame(frame),
            hide_index=True,
            use_container_width=True,
            column_config={
                ui_text("Amount"): st.column_config.NumberColumn(ui_text("Amount (SGD)"), format="%.2f"),
            },
        )

        st.subheader(ui_text('Manage transaction'))
        
        # Month filter for viewing historical transactions
        st.caption(ui_text('View transactions from different months'))
        
        # Get ALL transactions (no period filter) to extract available months
        all_transactions = backend_call(lambda: client.list_transactions(user_id, None)) or []
        
        # Extract unique months from all transactions
        if all_transactions:
            transaction_months = sorted({
                datetime.strptime(item["occurred_on"], "%Y-%m-%d").replace(tzinfo=UTC).strftime("%Y-%m")
                for item in all_transactions
            }, reverse=True)

            # Add current month if not present
            current_month = period_start.strftime("%Y-%m")
            if current_month not in transaction_months:
                transaction_months.insert(0, current_month)
        else:
            transaction_months = [period_start.strftime("%Y-%m")]

        format_month = month_formatter()
        selected_month = st.selectbox(
            ui_text('Filter by month'),
            options=transaction_months,
            format_func=lambda x: format_month(datetime.strptime(x + "-01", "%Y-%m-%d").replace(tzinfo=UTC)),
            index=0,
            key=f"transactions-{user_id}-month-filter"
        )
        
        # Convert selected month to period_start date
        selected_year, selected_month_num = map(int, selected_month.split("-"))
        filter_period_start = date(selected_year, selected_month_num, 1)
        
        # Fetch transactions for selected month
        filtered_transactions = backend_call(lambda: client.list_transactions(user_id, filter_period_start)) or []
        
        # Use filtered transactions for the rest of the page
        display_transactions = filtered_transactions if filtered_transactions else transactions
        
        selected_id = st.selectbox(
            ui_text('Transaction'),
            [item["id"] for item in display_transactions],
            index=None,
            format_func=lambda value: next(
                f"{item['occurred_on']} · {item['description']}"
                for item in display_transactions
                if item["id"] == value
            ),
            key=f"manage-transaction-{user_id}-selection-v2",
        )
        if selected_id is not None:
            selected = next(item for item in display_transactions if item["id"] == selected_id)
            selected_category = selected["category"]
            edit_categories = list(dict.fromkeys([*CATEGORIES, selected_category]))
            selected_occurred = date.fromisoformat(selected["occurred_on"])
            actual_month_start = datetime.now(UTC).date().replace(day=1)
            editable = (
                selected_occurred.year == actual_month_start.year
                and selected_occurred.month == actual_month_start.month
            )
            if not editable:
                st.info(
                    ui_text('Transactions from previous or future months are read-only. You can still delete them.')
                )
                st.text_input(ui_text('Description'), value=selected["description"], disabled=True)
                detail_left, detail_right = st.columns(2)
                detail_left.text_input(
                    ui_text('Category'), value=_category_label(selected["category"]), disabled=True
                )
                detail_right.number_input(
                    ui_text('Amount (SGD)'),
                    value=float(selected["amount"]["amount"]),
                    disabled=True,
                )
                detail_left.date_input(
                    ui_text('Date'), value=selected_occurred, disabled=True,
                    key=f"manage-transaction-{selected_id}-readonly-date",
                )
                detail_right.toggle(
                    ui_text('Recurring expense'),
                    value=selected["recurring"],
                    disabled=True,
                    key=f"manage-transaction-{selected_id}-readonly-recurring",
                )
                if st.button(
                    ui_text('Delete'), icon=":material/delete:", key=f"manage-transaction-{selected_id}-delete-readonly"
                ):
                    backend_call(lambda: client.delete_transaction(user_id, selected_id))
                    st.success(ui_text('Transaction deleted.'))
                    st.rerun()
                return
            with st.form("manage-transaction"):
                edit_description = st.text_input(
                    ui_text('Description'),
                    value=selected["description"],
                    key=f"manage-transaction-{selected_id}-description",
                )
                first, second = st.columns(2)
                edit_category = first.selectbox(
                    ui_text('Category'),
                    edit_categories,
                    index=edit_categories.index(selected_category),
                    format_func=option_formatter(),
                    key=f"manage-transaction-{selected_id}-category",
                    accept_new_options=True,
                )
                edit_amount = second.number_input(
                    ui_text('Amount (SGD)'),
                    min_value=0.01,
                    value=float(selected["amount"]["amount"]),
                    key=f"manage-transaction-{selected_id}-amount",
                )
                third, fourth = st.columns(2)
                edit_date = third.date_input(
                    ui_text('Date'),
                    value=date.fromisoformat(selected["occurred_on"]),
                    key=f"manage-transaction-{selected_id}-date",
                )
                edit_recurring = fourth.toggle(
                    ui_text('Recurring expense'),
                    value=selected["recurring"],
                    key=f"manage-transaction-{selected_id}-recurring",
                )
                edit_recurrence = _recurrence_fields(f"manage-transaction-{selected_id}", selected.get("recurrence"))
                edit_type = st.selectbox(ui_text('Transaction type'), ["expense", "income", "transfer", "refund"], format_func=option_formatter(), index=["expense", "income", "transfer", "refund"].index(selected.get("transaction_type", "expense")), key=f"manage-transaction-{selected_id}-type")
                save, delete = st.columns(2)
                save_submitted = save.form_submit_button(
                    ui_text('Save changes'), type="primary", icon=":material/save:"
                )
                delete_submitted = delete.form_submit_button(
                    ui_text('Delete'), icon=":material/delete:"
                )
            if save_submitted:
                if edit_recurring and edit_recurrence and (not edit_recurrence["first_on"] or not edit_recurrence["next_due_on"]):
                    st.warning(ui_text('Enter the first scheduled date and next due date.'))
                    return
                result = backend_call(
                    lambda: client.update_transaction(
                        user_id,
                        selected_id,
                        {**_transaction_payload(edit_description, edit_category, edit_amount, edit_date, edit_recurring, edit_recurrence), "transaction_type": edit_type,
                         "obligation_id": selected.get("obligation_id") if edit_recurring else None},
                    )
                )
                if result:
                    st.success(ui_text('Transaction updated.'))
                    st.rerun()
            if delete_submitted:
                backend_call(lambda: client.delete_transaction(user_id, selected_id))
                st.success(ui_text('Transaction deleted.'))
                st.rerun()


def budget_page() -> None:
    log_event("VV entering ", "ui.pages", "budget_page")
    render_budget_page(
        get_client(), get_user_id(), get_period_start(), CATEGORIES, _create_pie_chart,
    )


def goals_page() -> None:
    log_event("VV entering ", "ui.pages", "goals_page")
    client = get_client()
    user_id = get_user_id()
    page_header(ui_text('Goals'), ui_text('Savings targets'))
    goals = backend_call(lambda: client.list_goals(user_id)) or []

    for goal in goals:
        current = float(goal["current_amount"]["amount"])
        target = float(goal["target_amount"]["amount"])
        st.write(f"**{goal['name']}**")
        st.progress(
            clamp_progress(current / target if target else 1.0),
            text=ui_text('{v0} of {v1}', v0=money(current), v1=money(target)),
        )

    add_tab, manage_tab = st.tabs([ui_text('Add goal'), ui_text('Manage goals')])
    with add_tab:
        with st.form("add-goal", clear_on_submit=True):
            name = st.text_input(
                ui_text('Goal name'), max_chars=120, key=f"add-goal-{user_id}-name-v2"
            )
            first, second = st.columns(2)
            target_amount = first.number_input(
                ui_text('Target (SGD)'),
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"add-goal-{user_id}-target-v2",
            )
            current_amount = second.number_input(
                ui_text('Saved (SGD)'),
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"add-goal-{user_id}-current-v2",
            )
            target_months = st.number_input(
                ui_text('Time horizon (months)'),
                min_value=0,
                max_value=600,
                value=0,
                key=f"add-goal-{user_id}-months-v2",
            )
            add_submitted = st.form_submit_button(
                ui_text('Add goal'), type="primary", icon=":material/add:"
            )
        if add_submitted:
            if not name.strip():
                st.warning(ui_text('Enter a goal name.'))
            elif target_amount <= 0:
                st.warning(ui_text('Enter a target amount greater than zero.'))
            elif target_months <= 0:
                st.warning(ui_text('Enter a time horizon greater than zero.'))
            else:
                payload = {
                    "name": name.strip(),
                    "target_amount": {"currency": "SGD", "amount": target_amount},
                    "current_amount": {"currency": "SGD", "amount": current_amount},
                    "target_months": target_months,
                }
                result = backend_call(lambda: client.create_goal(user_id, payload))
                if result:
                    st.success(ui_text('Goal added.'))
                    st.rerun()

    with manage_tab:
        if not goals:
            st.caption(ui_text('No goals to manage.'))
            return
        goal_id = st.selectbox(
            ui_text('Goal'), [goal["id"] for goal in goals],
            index=None,
            format_func=lambda value: next(goal["name"] for goal in goals if goal["id"] == value),
            key=f"manage-goal-{user_id}-selection-v2",
        )
        if goal_id is not None:
            selected = next(goal for goal in goals if goal["id"] == goal_id)
            with st.form("manage-goal"):
                edit_name = st.text_input(
                    ui_text('Goal name'),
                    value=selected["name"],
                    key=f"manage-goal-{goal_id}-name",
                )
                first, second = st.columns(2)
                edit_target = first.number_input(
                    ui_text('Target (SGD)'),
                    min_value=1.0,
                    value=float(selected["target_amount"]["amount"]),
                    key=f"manage-goal-{goal_id}-target",
                )
                edit_current = second.number_input(
                    ui_text('Saved (SGD)'),
                    min_value=0.0,
                    value=float(selected["current_amount"]["amount"]),
                    key=f"manage-goal-{goal_id}-current",
                )
                edit_months = st.number_input(
                    ui_text('Time horizon (months)'),
                    min_value=1,
                    max_value=600,
                    value=int(selected["target_months"]),
                    key=f"manage-goal-{goal_id}-months",
                )
                save, delete = st.columns(2)
                save_submitted = save.form_submit_button(
                    ui_text('Save changes'), type="primary", icon=":material/save:"
                )
                delete_submitted = delete.form_submit_button(
                    ui_text('Delete'), icon=":material/delete:"
                )
            payload = {
                "name": edit_name.strip(),
                "target_amount": {"currency": "SGD", "amount": edit_target},
                "current_amount": {"currency": "SGD", "amount": edit_current},
                "target_months": edit_months,
            }
            if save_submitted:
                result = backend_call(lambda: client.update_goal(user_id, goal_id, payload))
                if result:
                    st.success(ui_text('Goal updated.'))
                    st.rerun()
            if delete_submitted:
                backend_call(lambda: client.delete_goal(user_id, goal_id))
                st.success(ui_text('Goal deleted.'))
                st.rerun()


def _user_message_markdown(content: str) -> str:
    # Markdown renders a single newline as a space; keep the user's typed line breaks.
    log_event("VV entering ", "ui.pages", "_user_message_markdown")
    return "  \n".join(currency_safe_markdown(content).replace("\r\n", "\n").split("\n"))


def _render_coach_message(message: dict, locale="en") -> None:
    log_event("VV entering ", "ui.pages", "_render_coach_message")
    with (
        call_span(f"{__name__}._render_coach_message")
        if context_fields().get("correlation_id") else nullcontext()
    ):
        avatar = (
            ":material/person:"
            if message["role"] == "user"
            else ":material/account_balance_wallet:"
        )
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(
                _user_message_markdown(message["content"])
                if message["role"] == "user"
                else currency_safe_markdown(message["content"])
            )
            explanation = message.get("explanation") or message.get("audit") or {}
            if explanation.get("model_provider") == "local_fixture":
                st.caption(translate("coach.offline_fixture", locale))
            sources = message.get("sources", [])
            if sources:
                if any(source.get("document_filename") for source in sources):
                    st.caption(translate("citation.rag_references", locale))
                if any(not source.get("document_filename") for source in sources):
                    st.caption(translate("citation.references", locale))
                for source in sources:
                    title = _escape_markdown_text(source["title"])
                    organization = _escape_markdown_text(source["issuing_organization"])
                    published_at = _escape_markdown_text(source["published_at"])
                    url = quote(source["canonical_url"], safe=":/?&=#%")
                    filename = source.get("document_filename")
                    content_kind = source.get("content_kind")
                    provenance = {
                        "source_document": "citation.source_document",
                        "project_summary": "citation.project_summary",
                    }.get(content_kind)
                    details = f"{organization}, {published_at}"
                    if filename:
                        details += f" · {_escape_markdown_text(filename)}"
                    if provenance:
                        details = f"{translate(provenance, locale)} · {details}"
                    st.markdown(
                        f"- [{title}]({url}) — {details} · "
                        + translate("citation.source_id", locale, source_id=_escape_markdown_text(source['source_id']))
                    )
            _render_coach_explanation(message.get("explanation"), locale)
        if context_fields().get("correlation_id"):
            log_event("coach.response_rendered", **response_metadata(message))


def _escape_markdown_text(value: str) -> str:
    log_event("VV entering ", "ui.pages", "_escape_markdown_text")
    value = html.escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+!|>$])", r"\\\1", value)


def _open_coach_rename(session_id: str, title: str) -> None:
    log_event("VV entering ", "ui.pages", "_open_coach_rename")
    st.session_state.coach_rename_open = session_id
    st.session_state[f"coach-rename-title-{session_id}"] = title
    st.session_state.pop("coach_delete_open", None)


def _open_coach_delete(session_id: str) -> None:
    log_event("VV entering ", "ui.pages", "_open_coach_delete")
    st.session_state.coach_delete_open = session_id
    st.session_state.pop("coach_rename_open", None)


def _render_coach_conversations(client, user_id, sessions, active_session_id, label) -> None:
    log_event("VV entering ", "ui.pages", "_render_coach_conversations")
    with st.container(key="coach-conversation-list", gap=None):
        for chat_session in sessions:
            session_id = chat_session["id"]
            title = chat_session["title"]
            with st.container(key=f"coach-conversation-row-{session_id}"):
                if st.session_state.get("coach_rename_open") == session_id:
                    with st.form(f"coach-rename-form-{session_id}", border=False):
                        title_column, save_column, cancel_column = st.columns(
                            [1, 0.16, 0.16], gap="small", vertical_alignment="center"
                        )
                        with title_column:
                            renamed_title = st.text_input(
                                label("coach.conversation_title"), max_chars=120,
                                key=f"coach-rename-title-{session_id}",
                                label_visibility="collapsed",
                            )
                        with save_column:
                            rename_submitted = st.form_submit_button(
                                label("coach.save"), icon=":material/check:",
                                help=label("coach.save"), use_container_width=True,
                            )
                        with cancel_column:
                            cancelled = st.form_submit_button(
                                label("coach.cancel"), icon=":material/close:",
                                help=label("coach.cancel"), use_container_width=True,
                            )
                    if cancelled:
                        st.session_state.pop("coach_rename_open", None)
                        st.rerun()
                    if rename_submitted:
                        if not renamed_title.strip():
                            st.error(label("coach.title_required"))
                        elif backend_call(
                            lambda session_id=session_id, renamed_title=renamed_title: client.rename_chat_session(
                                user_id, session_id, renamed_title.strip()
                            )
                        ):
                            st.session_state.pop("coach_rename_open", None)
                            st.rerun()
                else:
                    if st.button(
                        title,
                        icon=(
                            ":material/chat_bubble:"
                            if session_id == active_session_id
                            else ":material/chat_bubble_outline:"
                        ),
                        help=title, key=f"coach-session-{session_id}",
                        type="primary" if session_id == active_session_id else "tertiary",
                        use_container_width=True,
                    ):
                        st.session_state.coach_active_session_id = session_id
                        st.session_state.pop("coach_pending_question", None)
                        st.session_state.pop("coach_pending_render", None)
                        st.session_state.pop("coach_rename_open", None)
                        st.session_state.pop("coach_delete_open", None)
                        st.rerun()
                    with st.container(
                        key=f"coach-conversation-actions-{session_id}",
                        horizontal=True, gap=None, vertical_alignment="center",
                    ):
                        st.button(
                            label("coach.rename"), icon=":material/edit:",
                            help=label("coach.rename_title", title=title),
                            key=f"coach-rename-action-{session_id}",
                            type="tertiary",
                            on_click=_open_coach_rename, args=(session_id, title),
                        )
                        st.button(
                            label("coach.delete"), icon=":material/delete:",
                            help=label("coach.delete_title", title=title),
                            key=f"coach-delete-action-{session_id}",
                            type="tertiary",
                            on_click=_open_coach_delete, args=(session_id,),
                        )

                if st.session_state.get("coach_delete_open") == session_id:
                    st.warning(label("coach.delete_question"))
                    if st.button(
                        label("coach.delete_conversation"), icon=":material/delete:",
                        type="primary", key=f"coach-confirm-delete-{session_id}",
                        use_container_width=True,
                    ):
                        backend_call(
                            lambda session_id=session_id: client.delete_chat_session(user_id, session_id)
                        )
                        if session_id == active_session_id:
                            st.session_state.coach_active_session_id = None
                            st.session_state.pop("coach_pending_render", None)
                        st.session_state.pop("coach_delete_open", None)
                        st.rerun()
                    if st.button(
                        label("coach.cancel"), key=f"coach-cancel-delete-{session_id}",
                        use_container_width=True,
                    ):
                        st.session_state.pop("coach_delete_open", None)
                        st.rerun()


def coach_page() -> None:
    log_event("VV entering ", "ui.pages", "coach_page")
    client = get_client()
    user_id = get_user_id()
    selection = current_selection(user_id)
    profile = backend_call(lambda: client.get_profile(user_id)) or {}
    if explicit_selection(user_id) is None:
        selection = resolve_locale("", preferred=profile.get("preferred_language"))
        if apply_profile_default(user_id, selection):
            st.rerun()
    ui_locale = selection

    def label(key, **values):
        log_event("VV entering ", "ui.pages", "coach_page.label")
        return translate(key, ui_locale, **values)
    
    # Check if there's a pending question from insight cards with navigation flag
    pending_question = st.session_state.pop("pending_coach_question", None)
    should_navigate = st.session_state.pop("navigate_to_coach", False)
    
    with st.container(key="coach-page-header"):
        page_header(label("coach.title"), label("coach.subtitle"), marker_class="coach-shell")
        period = (
            get_period_start().strftime("%Y-%m") if ui_locale == "zh-Hans"
            else get_period_start().strftime("%B %Y")
        )
        st.caption(label("coach.period", period=period), help=label("coach.period_help"))
    
    # If we have a pending question and navigation was triggered, auto-submit it
    if pending_question and should_navigate:
        st.info(label("coach.asking", question=pending_question))
        # Set the question to be sent
        st.session_state.coach_pending_question = pending_question
        # Trigger the send
        st.session_state.coach_auto_submit = True
        st.rerun()

    sessions = backend_call(lambda: client.list_chat_sessions(user_id)) or []
    session_by_id = {item["id"]: item for item in sessions}
    if "coach_active_session_id" not in st.session_state:
        st.session_state.coach_active_session_id = sessions[0]["id"] if sessions else None
    active_session_id = st.session_state.get("coach_active_session_id")
    response_locale = selection
    if active_session_id not in session_by_id:
        active_session_id = None
        st.session_state.coach_active_session_id = None

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-section coach-conversation-section">'
            + html.escape(label("coach.conversations")) + '</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            label("coach.new_chat"),
            icon=":material/edit_square:",
            disabled=active_session_id is None,
            key="coach-new-chat",
            use_container_width=True,
        ):
            st.session_state.coach_active_session_id = None
            st.session_state.pop("coach_pending_question", None)
            st.session_state.pop("coach_pending_render", None)
            st.session_state.pop("coach_rename_open", None)
            st.session_state.pop("coach_delete_open", None)
            st.rerun()

        if not sessions:
            st.caption(label("coach.no_conversations"))
        _render_coach_conversations(client, user_id, sessions, active_session_id, label)

    # Check for pending question (from insight cards or chat input)
    pending_question = st.session_state.pop("coach_pending_question", None)
    auto_submit = st.session_state.pop("coach_auto_submit", False)
    
    if pending_question and active_session_id is None:
        title = pending_question[:117] + "..." if len(pending_question) > 120 else pending_question
        created_session = backend_call(
            lambda: client.create_chat_session(user_id, title)
        )
        if created_session:
            active_session_id = created_session["id"]
            st.session_state.coach_active_session_id = active_session_id
    
    # Auto-submit if flag is set
    if pending_question and auto_submit:
        st.session_state.coach_pending_question = pending_question
        st.rerun()

    pending_render = st.session_state.get("coach_pending_render")
    if pending_render and pending_render["journey_id"] != st.session_state.get("journey_id"):
        st.session_state.pop("coach_pending_render", None)
        pending_render = None
    with (
        trace_context(**{key: value for key, value in pending_render.items() if key != "trace_id"})
        if pending_render else nullcontext()
    ):
        active_session = (
            backend_call(lambda: client.get_chat_session(user_id, active_session_id))
            if active_session_id
            else None
        )
    history = active_session.get("messages", []) if active_session else []

    for message in history:
        matches_pending = (
            pending_render
            and message["role"] == "assistant"
            and response_metadata(message).get("trace_id") == pending_render["trace_id"]
        )
        if matches_pending:
            with trace_context(**{key: value for key, value in pending_render.items() if key != "trace_id"}):
                _render_coach_message(message, ui_locale)
            st.session_state.pop("coach_pending_render", None)
            pending_render = None
        else:
            _render_coach_message(message, ui_locale)

    if pending_question and active_session_id:
        response_locale = resolve_locale(
            pending_question,
            selected=explicit_selection(user_id),
            preferred=profile.get("preferred_language"),
            history=history,
        )
        sync_response_locale(user_id, response_locale)
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(_user_message_markdown(pending_question))
        with trace_context(journey_id=st.session_state.get("journey_id")), call_span(
            f"{__name__}.coach_page"
        ):
            log_event("coach.request.submitted", input_characters=len(pending_question))
            with st.chat_message(
                "assistant", avatar=":material/account_balance_wallet:"
            ), st.spinner(label("coach.thinking")):
                response = backend_call(
                    lambda: client.ask_coach(
                        {**build_request(user_id, pending_question, active_session_id, response_locale=response_locale), "budget_period_start": get_period_start().isoformat()}
                    )
                )
            if response:
                metadata = response_metadata(response)
                log_event("coach.response_accepted", **metadata)
                current = context_fields()
                # Only trace metadata crosses the rerun. Match the persisted
                # explanation's trace ID before attributing a rendered answer.
                if metadata.get("trace_id"):
                    st.session_state.coach_pending_render = {
                        "correlation_id": current["correlation_id"],
                        "journey_id": current["journey_id"],
                        "parent_span_id": current["span_id"],
                        "caller_method": current["method"],
                        "trace_id": metadata["trace_id"],
                    }
                st.rerun()

    starter_question = None
    if not history:
        st.markdown(
            '<div class="coach-empty"><h2>' + html.escape(label("coach.empty_title"))
            + '</h2><p>' + html.escape(label("coach.empty_help")) + '</p></div>',
            unsafe_allow_html=True,
        )
        first, second = st.columns(2)
        for index, (starter_key, icon) in enumerate(COACH_STARTERS):
            starter = label(starter_key)
            column = first if index % 2 == 0 else second
            if column.button(
                starter,
                icon=icon,
                key=f"coach-starter-{index}",
                use_container_width=True,
            ):
                starter_question = starter

    question = st.chat_input(
        label("coach.input"),
        max_chars=5000,
        key=f"coach-input-{user_id}",
    )
    st.markdown(
        '<div class="coach-disclaimer">' + html.escape(label("coach.disclaimer")) + '</div>',
        unsafe_allow_html=True,
    )
    submitted_question = question or starter_question
    if submitted_question:
        normalized_question = submitted_question.strip()
        if normalized_question:
            st.session_state.pop("coach_pending_render", None)
            st.session_state.coach_pending_question = normalized_question
            st.rerun()


def profile_page() -> None:
    log_event("VV entering ", "ui.pages", "profile_page")
    client = get_client()
    user_id = get_user_id()
    page_header(ui_text('Profile settings'), ui_text('Financial baseline'))
    st.caption(ui_text('Profile ID · {v0}', v0=user_id))
    saved_notice = st.session_state.pop("profile_saved_notice", None)
    if saved_notice:
        st.success(ui_text(saved_notice))

    profile = backend_call(lambda: client.get_profile(user_id))
    if not profile:
        st.info(ui_text('This profile has not been created yet.'))
        return
    context_tab, fairness_tab, privacy_tab = st.tabs(
        [ui_text('Financial context'), ui_text('Fairness data'), ui_text('Privacy & data')]
    )

    with context_tab:
        income = profile.get("monthly_income") or {"amount": 0.0}
        preferences = profile.get("preferences", {})
        current_risk = profile.get("risk_tolerance")
        with st.form("profile"):
            display_name = st.text_input(
                ui_text('Display name'), value=preferences.get("display_name", ""), max_chars=80,
                key=f"profile-{user_id}-display-name",
            )
            first, second = st.columns(2)
            monthly_income = first.number_input(
                ui_text('Monthly income (SGD)'),
                min_value=0.0,
                value=float(income["amount"]),
                step=100.0,
                key=f"profile-{user_id}-monthly-income",
            )
            income_frequency = second.selectbox(
                ui_text('Income frequency'),
                INCOME_FREQUENCY_OPTIONS,
                format_func=option_formatter(),
                index=_option_index(INCOME_FREQUENCY_OPTIONS, profile.get("income_frequency")),
                key=f"profile-{user_id}-income-frequency-v2",
            )
            third, fourth = st.columns(2)
            employment_status = third.selectbox(
                ui_text('Employment status'),
                EMPLOYMENT_OPTIONS,
                index=_option_index(EMPLOYMENT_OPTIONS, profile.get("employment_status")),
                format_func=option_formatter(),
                key=f"profile-{user_id}-employment-status-v2",
            )
            occupation_category = fourth.selectbox(
                ui_text('Occupation category'),
                OCCUPATION_OPTIONS,
                index=_option_index(OCCUPATION_OPTIONS, profile.get("occupation_category")),
                format_func=option_formatter(),
                key=f"profile-{user_id}-occupation-category-v2",
            )
            fifth, sixth = st.columns(2)
            income_stability = fifth.selectbox(
                ui_text('Income stability'),
                INCOME_STABILITY_OPTIONS,
                index=_option_index(INCOME_STABILITY_OPTIONS, profile.get("income_stability")),
                format_func=option_formatter(),
                key=f"profile-{user_id}-income-stability-v2",
            )
            housing_status = sixth.selectbox(
                ui_text('Housing status'),
                HOUSING_OPTIONS,
                index=_option_index(HOUSING_OPTIONS, profile.get("housing_status")),
                format_func=option_formatter(),
                key=f"profile-{user_id}-housing-status-v2",
            )
            seventh, eighth = st.columns(2)
            household_size = seventh.number_input(
                ui_text('Household size'),
                min_value=0,
                max_value=30,
                value=profile.get("household_size") or 0,
                key=f"profile-{user_id}-household-size",
            )
            dependants = eighth.number_input(
                ui_text('Dependants'),
                min_value=0,
                max_value=20,
                value=profile.get("dependants") or 0,
                key=f"profile-{user_id}-dependants",
            )
            ninth, tenth = st.columns(2)
            financial_literacy = ninth.selectbox(
                ui_text('Financial literacy'),
                LITERACY_OPTIONS,
                index=_option_index(LITERACY_OPTIONS, profile.get("financial_literacy")),
                format_func=option_formatter(),
                key=f"profile-{user_id}-financial-literacy-v2",
            )
            preferred_language = tenth.selectbox(
                ui_text('Preferred language'),
                LANGUAGE_OPTIONS,
                format_func=option_formatter(),
                index=_option_index(LANGUAGE_OPTIONS, profile.get("preferred_language")),
                key=f"profile-{user_id}-preferred-language-v2",
            )
            st.caption(translate("coach.language_preference_help", current_selection(user_id)))
            accessibility_preferences = st.multiselect(
                ui_text('Accessibility preferences'),
                ACCESSIBILITY_OPTIONS,
                default=profile.get("accessibility_preferences", []),
                format_func=option_formatter(),
                key=f"profile-{user_id}-accessibility-preferences",
            )
            risk_tolerance = st.segmented_control(
                ui_text('Risk comfort'),
                RISK_OPTIONS,
                default=current_risk,
                format_func=option_formatter(),
                selection_mode="single",
                key=f"profile-{user_id}-risk-comfort-v2",
            )
            saved = st.form_submit_button(
                ui_text('Save profile'), type="primary", icon=":material/save:"
            )
        if saved:
            if dependants and not household_size:
                st.warning(ui_text('Enter a household size when dependants are provided.'))
            elif household_size and dependants > household_size:
                st.warning(ui_text('Dependants cannot exceed household size.'))
            else:
                normalized_name = display_name.strip()
                payload = {
                    "monthly_income": {"currency": "SGD", "amount": monthly_income},
                    "risk_tolerance": risk_tolerance,
                    "employment_status": employment_status,
                    "occupation_category": occupation_category,
                    "income_frequency": income_frequency,
                    "income_stability": income_stability,
                    "household_size": household_size or None,
                    "dependants": dependants,
                    "housing_status": housing_status,
                    "financial_literacy": financial_literacy,
                    "preferred_language": preferred_language,
                    "accessibility_preferences": accessibility_preferences,
                    "preferences": (
                        {"display_name": normalized_name} if normalized_name else {}
                    ),
                }
                result = backend_call(lambda: client.save_profile(user_id, payload))
                if result:
                    st.session_state.profile_saved_notice = "Profile saved."
                    st.session_state.profile_switcher_version = (
                        st.session_state.get("profile_switcher_version", 0) + 1
                    )
                    st.rerun()

    with fairness_tab:
        fairness = backend_call(lambda: client.get_fairness_profile(user_id))
        if fairness:
            consent = fairness["consent"]
            demographics = fairness.get("demographics") or {}
            st.info(
                ui_text('Optional demographic data is stored separately for fairness evaluation. It is never included in normal coaching requests.')
            )
            with st.form("fairness-consent"):
                granted = st.toggle(
                    ui_text('Allow my demographic data to be stored for fairness testing'),
                    value=consent["granted"],
                    key=f"fairness-{user_id}-consent",
                )
                consent_saved = st.form_submit_button(
                    ui_text('Update consent'), icon=":material/privacy_tip:"
                )
            if consent_saved:
                result = backend_call(
                    lambda: client.save_fairness_consent(user_id, granted)
                )
                if result:
                    message = (
                        "Fairness-testing consent granted."
                        if granted
                        else "Consent withdrawn and demographic data deleted."
                    )
                    st.session_state.profile_saved_notice = message
                    st.rerun()

            if consent["granted"]:
                with st.form("demographics"):
                    age_band = st.selectbox(
                        ui_text('Age band'),
                        AGE_BANDS,
                        format_func=option_formatter(),
                        index=_option_index(AGE_BANDS, demographics.get("age_band")),
                        key=f"fairness-{user_id}-age-band-v2",
                    )
                    gender_identity = st.selectbox(
                        ui_text('Gender identity'),
                        GENDER_OPTIONS,
                        format_func=option_formatter(),
                        index=_option_index(GENDER_OPTIONS, demographics.get("gender_identity")),
                        key=f"fairness-{user_id}-gender-identity-v2",
                    )
                    race_ethnicity = st.multiselect(
                        ui_text('Race or ethnicity'),
                        RACE_ETHNICITY_OPTIONS,
                        format_func=option_formatter(),
                        default=demographics.get("race_ethnicity", []),
                        key=f"fairness-{user_id}-race-ethnicity",
                    )
                    nationality_residency = st.selectbox(
                        ui_text('Nationality or residency'),
                        RESIDENCY_OPTIONS,
                        format_func=option_formatter(),
                        index=_option_index(
                            RESIDENCY_OPTIONS,
                            demographics.get("nationality_residency"),
                        ),
                        key=f"fairness-{user_id}-nationality-residency-v2",
                    )
                    disability_status = st.selectbox(
                        ui_text('Disability status'),
                        DISABILITY_OPTIONS,
                        format_func=option_formatter(),
                        index=_option_index(
                            DISABILITY_OPTIONS, demographics.get("disability_status")
                        ),
                        key=f"fairness-{user_id}-disability-status-v2",
                    )
                    marital_status = st.selectbox(
                        ui_text('Marital or family status'),
                        MARITAL_OPTIONS,
                        format_func=option_formatter(),
                        index=_option_index(MARITAL_OPTIONS, demographics.get("marital_status")),
                        key=f"fairness-{user_id}-marital-status-v2",
                    )
                    residential_region = st.selectbox(
                        ui_text('Broad residential region'),
                        REGION_OPTIONS,
                        format_func=option_formatter(),
                        index=_option_index(REGION_OPTIONS, demographics.get("residential_region")),
                        key=f"fairness-{user_id}-residential-region-v2",
                    )
                    demographics_saved = st.form_submit_button(
                        ui_text('Save fairness data'), type="primary", icon=":material/save:"
                    )
                if demographics_saved:
                    payload = {
                        "age_band": age_band,
                        "gender_identity": gender_identity,
                        "race_ethnicity": race_ethnicity,
                        "nationality_residency": nationality_residency,
                        "disability_status": disability_status,
                        "marital_status": marital_status,
                        "residential_region": residential_region,
                    }
                    if backend_call(lambda: client.save_demographics(user_id, payload)):
                        st.success(ui_text('Fairness data saved.'))

    with privacy_tab:
        lifecycle = backend_call(lambda: client.get_data_lifecycle(user_id))
        if not lifecycle:
            return
        retention = lifecycle["retention"]
        st.subheader(ui_text('Data lifecycle'))
        st.caption(ui_text('Policy version · {v0}', v0=lifecycle['policy_version']))
        st.write(
            ui_text('Your financial workspace is kept until you delete it. Conversation history is kept for {v0} days, and detailed AI decision traces for {v1} days.', v0=retention['chat_history_days'], v1=retention['orchestration_traces_days'])
        )

        memory = lifecycle["durable_memory"]
        if not memory["feature_enabled"]:
            st.info(
                ui_text('Durable agent memory is currently disabled. Your preference is recorded for a future release, but granting consent does not activate memory.')
            )
        with st.form("durable-memory-consent"):
            memory_granted = st.toggle(
                ui_text('Allow durable agent memory when the feature becomes available'),
                value=memory["granted"],
            )
            memory_saved = st.form_submit_button(
                ui_text('Update memory consent'), icon=":material/privacy_tip:"
            )
        if memory_saved:
            result = backend_call(
                lambda: client.save_memory_consent(user_id, memory_granted)
            )
            if result:
                st.session_state.profile_saved_notice = (
                    "Durable-memory consent preference updated."
                )
                st.rerun()

        st.divider()
        st.subheader(ui_text('Export your data'))
        st.write(
            ui_text('Prepare a portable JSON copy of your profile, financial records, conversations, consents, and available AI decision traces.')
        )
        export_key = f"profile-data-export-{user_id}"
        if st.button(
            ui_text('Prepare data export'),
            icon=":material/download:",
            key=f"prepare-data-export-{user_id}",
        ):
            export = backend_call(lambda: client.export_user_data(user_id))
            if export:
                st.session_state[export_key] = export
        prepared_export = st.session_state.get(export_key)
        if prepared_export:
            st.download_button(
                ui_text('Download JSON export'),
                data=json.dumps(prepared_export, indent=2),
                file_name=f"{user_id}-data-export.json",
                mime="application/json",
                icon=":material/download:",
                key=f"download-data-export-{user_id}",
            )

        st.divider()
        st.subheader(ui_text('Delete your workspace'))
        st.warning(
            ui_text('This permanently deletes the profile, transactions, goals, budgets, fairness data, consent records, conversations, and available AI decision traces. This action cannot be undone.')
        )
        confirmed = st.checkbox(
            ui_text('I understand that all data for this workspace will be deleted'),
            key=f"delete-profile-confirmed-{user_id}",
        )
        delete_requested = st.button(
            ui_text('Delete workspace data'),
            icon=":material/delete_forever:",
            disabled=not confirmed,
            key=f"delete-profile-{user_id}",
        )
        if delete_requested and backend_call(
            lambda: client.delete_user_data(user_id, lifecycle["policy_version"])
        ):
            st.session_state.pop("active_user_id", None)
            st.session_state.pop("coach_active_session_id", None)
            st.session_state.pop("coach_history", None)
            st.session_state.pop("coach_pending_question", None)
            st.session_state.pop("coach_pending_render", None)
            st.session_state.pop("coach_rename_open", None)
            st.session_state.pop("coach_delete_open", None)
            st.session_state.pop(export_key, None)
            st.session_state.profile_switcher_version = (
                st.session_state.get("profile_switcher_version", 0) + 1
            )
            st.session_state.profile_deleted_notice = "Workspace data deleted."
            st.session_state.profile_deleted_redirect = True
            st.rerun()


def create_profile_page() -> None:
    log_event("VV entering ", "ui.pages", "create_profile_page")
    client = get_client()
    page_header(ui_text('Create profile'), ui_text('New financial workspace'))
    created_notice = st.session_state.pop("profile_created_notice", None)
    if created_notice:
        st.success(ui_text(created_notice))

    with st.form("create-profile", clear_on_submit=False):
        profile_id = st.text_input(
            ui_text('Profile ID'),
            max_chars=128,
            help=ui_text('Letters, numbers, dots, underscores, and hyphens.'),
            key="create-profile-id",
        )
        display_name = st.text_input(ui_text('Display name'), max_chars=80, key="create-profile-display-name")
        monthly_income = st.number_input(
            ui_text('Monthly income (SGD)'), min_value=0.0, step=100.0, key="create-profile-monthly-income"
        )
        risk_tolerance = st.segmented_control(
            ui_text('Risk comfort'),
            RISK_OPTIONS,
            default=None,
            format_func=option_formatter(),
            selection_mode="single",
            key="create-profile-risk-comfort-v2",
        )
        created = st.form_submit_button(
            ui_text('Create profile'), type="primary", icon=":material/person_add:"
        )

    if not created:
        return

    normalized_id = profile_id.strip()
    normalized_name = display_name.strip()
    if not PROFILE_ID_PATTERN.fullmatch(normalized_id):
        st.warning(ui_text('Enter a valid profile ID.'))
        return
    if not normalized_name:
        st.warning(ui_text('Enter a display name.'))
        return

    payload = {
        "user_id": normalized_id,
        "monthly_income": {"currency": "SGD", "amount": monthly_income},
        "risk_tolerance": risk_tolerance,
        "preferences": {"display_name": normalized_name},
    }
    try:
        result = client.create_profile(payload)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 409:
            st.error(ui_text('That profile ID is already in use.'))
        else:
            st.error(ui_text('The request could not be completed ({v0}).', v0=error.response.status_code))
        return
    except httpx.HTTPError:
        st.error(ui_text('The application service is temporarily unavailable.'))
        return

    st.session_state.active_user_id = result["user_id"]
    st.session_state.profile_switcher_version = (
        st.session_state.get("profile_switcher_version", 0) + 1
    )
    st.session_state.pop("coach_active_session_id", None)
    st.session_state.pop("coach_history", None)
    st.session_state.pop("coach_pending_question", None)
    st.session_state.pop("coach_pending_render", None)
    st.session_state.pop("coach_rename_open", None)
    st.session_state.pop("coach_delete_open", None)
    st.session_state.profile_created_notice = (
        f"{normalized_name} was created and is now active."
    )
    st.rerun()
