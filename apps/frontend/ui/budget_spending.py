"""Saved-plan spending facts, independent of the unsaved monthly editor."""
import streamlit as st

from ui.components import clamp_progress, money
from ui.i18n import option_label, ui_text


def render_spending(budget, currency, scope, create_pie_chart):
    st.subheader(ui_text('Spending this month'), anchor=False)
    st.caption(ui_text('These figures use saved limits. Unsaved changes are excluded.'))
    rows = budget.get("categories", [])
    planned = float(budget.get("total_limit", sum(float(r["limit_amount"]) for r in rows)))
    category_spent = sum(float(r["spent_amount"]) for r in rows)
    spent = float(budget.get("total_spent", category_spent))
    remaining = planned - spent
    with st.container(key="budget-spending-summary"):
        metrics = st.columns(3)
        metrics[0].metric(ui_text('Budgeted'), money(planned, currency))
        metrics[1].metric(ui_text('Spent'), money(spent, currency))
        metrics[2].metric(
            ui_text('Over budget') if remaining < 0 else ui_text('Remaining'), money(abs(remaining), currency)
        )
    if planned > 0:
        st.progress(clamp_progress(spent / planned), text=ui_text('{v0:.0%} of budget used', v0=spent / planned))
    st.caption(
        ui_text('Recorded expenses may be incomplete. Remaining budget is not an available bank balance.')
    )
    unbudgeted = max(0.0, round(spent - category_spent, 2))
    st.caption(
        ui_text("Totals include all spending for the selected month.")
        + (
            ui_text(" Includes {v0} in categories without limits.", v0=money(unbudgeted, currency))
            if unbudgeted
            else ""
        )
    )
    over = [r for r in rows if float(r["spent_amount"]) > float(r["limit_amount"])]
    if over:
        st.warning(
            ui_text("Over limit: {v0}", v0="; ".join(
                ui_text("{v0} — {v1} over", v0=option_label(r['category']), v1=money(float(r['spent_amount']) - float(r['limit_amount']), currency))
                for r in over
            )),
            icon=":material/warning:",
        )
    planning = budget.get("planning")
    if planning:
        st.caption(
            ui_text('Saved plan · income {v0} · savings allocation {v1}', v0=money(planning['take_home_income'], currency), v1=money(planning['savings_target'], currency))
        )
    if unbudgeted:
        st.info(
            ui_text('Without category limits: {v0} recorded spending. No limit is set.', v0=money(unbudgeted, currency))
        )
    zero_limits = [option_label(r["category"]) for r in rows if float(r["limit_amount"]) == 0]
    if zero_limits:
        st.caption(ui_text("Zero limits: {v0}.", v0=", ".join(zero_limits)))

    spending_column, allocation_column = st.columns([3, 2])
    with spending_column:
        st.markdown(ui_text('**Category spending**'))
        if rows or unbudgeted:
            import plotly.graph_objects as go

            ordered = sorted(rows, key=lambda r: (r not in over, r["category"]))
            labels = [option_label(r["category"]) for r in ordered]
            limits = [r["limit_amount"] for r in ordered]
            actuals = [r["spent_amount"] for r in ordered]
            colors = ["#dc2626" if r in over else "#0d9488" for r in ordered]
            if unbudgeted:
                labels.append(ui_text("Without category limits"))
                limits.append(None)  # No category limit is distinct from an explicit zero.
                actuals.append(unbudgeted)
                colors.append("#d97706")
            chart = go.Figure()
            chart.add_bar(
                name=ui_text("Budgeted"),
                y=labels,
                x=limits,
                orientation="h",
                marker_color="#cbd5e1",
                texttemplate="%{x:,.2f}",
                textposition="auto",
            )
            chart.add_bar(
                name=ui_text("Spent"),
                y=labels,
                x=actuals,
                orientation="h",
                marker_color=colors,
                texttemplate="%{x:,.2f}",
                textposition="auto",
            )
            chart.update_layout(
                barmode="group",
                height=max(320, len(labels) * 55),
                margin={"l": 0, "r": 10, "t": 40, "b": 25},
                legend={
                    "orientation": "h",
                    "x": 0,
                    "xanchor": "left",
                    "y": 1.02,
                    "yanchor": "bottom",
                },
            )
            chart.update_yaxes(autorange="reversed")
            st.plotly_chart(
                chart,
                width="stretch",
                key=scope + "-spending-chart",
                config={"displayModeBar": False},
            )
            st.caption(
                ui_text('Category amounts in {v0}. Saved limits compared with recorded spending.', v0=currency)
            )
            if unbudgeted:
                st.caption(
                    ui_text('Without category limits has no budgeted amount; it is included in Spent.')
                )
        else:
            st.info(ui_text('Add category limits or record expenses to see spending here.'))
    with allocation_column:
        st.markdown(ui_text('**Budget allocation**'))
        positive = [r for r in rows if float(r["limit_amount"]) > 0]
        if positive:
            chart = create_pie_chart(
                [option_label(r["category"]) for r in positive],
                [float(r["limit_amount"]) for r in positive],
                currency,
            )
            if chart is not None:
                chart.update_traces(hole=0.62, textposition="inside")
                chart.update_layout(
                    showlegend=True,
                    legend={
                        "orientation": "h",
                        "x": 0,
                        "xanchor": "left",
                        "y": -0.05,
                        "yanchor": "top",
                    },
                    margin={"l": 10, "r": 10, "t": 20, "b": 30},
                    height=max(320, 250 + len(positive) * 18),
                )
                st.plotly_chart(
                    chart,
                    width="stretch",
                    key=scope + "-allocation",
                    config={"displayModeBar": False},
                )
                st.caption(ui_text('Share of saved expense limits. Your savings allocation is separate.'))
        else:
            st.info(ui_text('Set a positive category limit to see the allocation chart.'))
