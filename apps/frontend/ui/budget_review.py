"""On-demand review UI; adoption fills an unsaved editor and never writes a budget."""

from copy import deepcopy

import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_budget_review(client, user_id, period, scope, draft_key):
    with st.expander("Review recorded spending", icon=":material/monitoring:"):
        st.caption(
            "Compare recorded expenses with saved limits, inspect illustrative month-end pace, and review possible adjustments."
        )
        result_key = f"{scope}-review"
        if st.button("Refresh spending review", key=f"{scope}-review-refresh"):
            result = backend_call(lambda: client.review_budget(user_id, period))
            if result:
                st.session_state[result_key] = result
        review = st.session_state.get(result_key)
        if not review:
            return
        st.caption(f"Through {review['as_of']} · {review['phase']} month · SGD records only")
        columns = st.columns(3)
        columns[0].metric("Recorded expenses", money(review["total_spent"]))
        columns[1].metric("Unbudgeted expenses", money(review["unbudgeted_spent"]))
        columns[2].metric(
            "Month-end pace illustration",
            money(review["total_pace_estimate"])
            if review["total_pace_estimate"] is not None
            else "Unavailable",
        )
        for warning in review["warnings"]:
            st.caption(warning)
        if not review["has_budget"]:
            st.info(
                "No saved budget exists for this month. Create a plan to compare category limits."
            )
        rows = review["categories"]
        if rows:
            import plotly.graph_objects as go

            chart = go.Figure()
            labels = [row["category"].title() for row in rows]
            for name, field, color in (
                ("Saved limit", "limit_amount", "#cbd5e1"),
                ("Recorded", "spent", "#0d9488"),
                ("Illustrative pace", "pace_estimate", "#d97706"),
            ):
                chart.add_bar(
                    name=name,
                    y=labels,
                    x=[row[field] for row in rows],
                    orientation="h",
                    marker_color=color,
                )
            chart.update_layout(
                barmode="group",
                height=max(280, len(rows) * 65),
                xaxis_title="SGD",
                margin={"t": 10, "b": 10},
            )
            chart.update_yaxes(autorange="reversed")
            st.plotly_chart(chart, use_container_width=True, key=f"{scope}-review-chart")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Category": row["category"],
                            "Status": row["status"].replace("_", " "),
                            "Recorded": row["spent"],
                            "Limit": row["limit_amount"],
                            "Remaining": row["remaining"],
                            "Pace illustration": row["pace_estimate"],
                            "Remaining per day": row["remaining_per_day"],
                            "Pace explanation": row["pace_note"],
                        }
                        for row in rows
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        for suggestion in review["suggestions"]:
            st.write(f"{suggestion['category'].title()}: {suggestion['reason']}")
        comparison = review.get("comparison")
        if not comparison or not comparison["results"]:
            return
        option = next(
            item for item in comparison["results"] if item["name"] == "Cover recorded spending"
        )
        st.markdown("**Proposed adjustment: cover recorded spending**")
        st.caption(
            "These suggested limits cover expenses already recorded. They do not include an allowance for future purchases or unpaid bills. Review every amount before saving."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Category": row["category"], "Proposed limit": row["limit_amount"]}
                    for row in option["draft"]["categories"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if option["totals"] and option["totals"]["funding_gap"]:
            st.warning(
                f"This proposal has a funding gap of {money(option['totals']['funding_gap'])}. Revise amounts before saving."
            )
        for question in option["questions"]:
            st.caption(question)
        if st.button("Review adjustment in editor", key=f"{scope}-review-adopt"):
            candidate = deepcopy(option["draft"])
            if (
                candidate["planning"]["take_home_income"] is None
                or candidate["planning"]["savings_target"] is None
            ):
                st.info(
                    "Supply take-home income and savings through Coach or the method explorer before adopting this adjustment."
                )
                return
            candidate["review_evidence"] = review["evidence_fingerprint"]
            st.session_state[draft_key] = candidate
            st.rerun()
