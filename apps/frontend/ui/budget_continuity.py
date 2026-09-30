"""Explicit multi-month previews and opt-in review scheduling."""

from datetime import date

import pandas as pd
import streamlit as st

from ui.components import backend_call

RULES = {
    "copy_limits": "Copy category limits",
    "carry_surplus": "Add recorded surplus to the first month",
    "carry_net": "Carry surplus or deduct overspending in the first month",
}


def render_continuity(client, user_id, period):
    key = f"continuity-{user_id}-{period}"
    with st.expander("Plan upcoming months", icon=":material/event_repeat:"):
        st.caption(
            f"Source: saved budget for {period:%B %Y}. Preview up to 12 months, then confirm the complete batch. Carry-forward needs a completed source month. Source commitments are month-specific and are not copied."
        )
        with st.form(key + "-form"):
            first = st.date_input(
                "First target month (choose its first day)", value=None, key=key + "-first"
            )
            months = st.number_input(
                "Number of months", min_value=1, max_value=12, value=1, key=key + "-months"
            )
            income = st.number_input(
                "Take-home income for each target month (SGD)",
                min_value=0.0,
                value=None,
                key=key + "-income",
            )
            savings = st.number_input(
                "Savings for each target month (SGD)",
                min_value=0.0,
                value=None,
                key=key + "-savings",
            )
            st.caption("Optional: supply different income and savings per month. If shared amounts above are blank, include every target month here.")
            overrides = st.data_editor(pd.DataFrame(columns=["period_start", "take_home_income", "savings_target"]), num_rows="dynamic", hide_index=True, key=key+"-monthly",
                column_config={"period_start": st.column_config.DateColumn("Month (first day)",required=True), "take_home_income": st.column_config.NumberColumn("Take-home income",min_value=0,required=True), "savings_target": st.column_config.NumberColumn("Savings",min_value=0,required=True)})
            rule = st.selectbox(
                "Carry-forward rule",
                list(RULES),
                format_func=RULES.get,
                index=None,
                placeholder="Choose a rule",
                key=key + "-rule",
            )
            replace = st.checkbox(
                "Allow replacement of existing target plans shown in the preview",
                key=key + "-replace",
            )
            calculate = st.form_submit_button("Preview monthly plans")
        if calculate:
            st.session_state.pop(key + "-preview", None)
            if first is None or ((income is None or savings is None) and overrides.empty) or rule is None or overrides.isna().any().any():
                st.warning("Supply the target month, income, savings and carry-forward rule.")
            else:
                st.session_state[key + "-preview"] = backend_call(
                    lambda: client.preview_budget_months(
                        user_id,
                        {
                            "source_period": period.isoformat(),
                            "first_period": first.isoformat(),
                            "months": months,
                            "take_home_income": income,
                            "savings_target": savings,
                            "carry_rule": rule,
                            "allow_overwrite": replace,
                            "month_inputs": [{**r, "period_start": r["period_start"].isoformat()} for r in overrides.to_dict("records")],
                        },
                    )
                )
        preview = st.session_state.get(key + "-preview")
        if preview:
            st.caption(
                "Confirmation applies to the preview below. After changing inputs above, calculate a new preview."
            )
            for warning in preview["warnings"]:
                st.caption(warning)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Month": row["budget"]["period_start"],
                            "Income": row["budget"]["planning"]["take_home_income"],
                            "Expenses": row["expenses"],
                            "Savings": row["budget"]["planning"]["savings_target"],
                            "Unallocated": row["unallocated"],
                            "Funding gap": row["funding_gap"],
                            "Replaces saved plan": row["replaces_existing"],
                        }
                        for row in preview["plans"]
                    ]
                ),
                hide_index=True,
            )
            for row in preview["plans"]:
                with st.expander("Exact plan: " + row["budget"]["period_start"]):
                    st.dataframe(pd.DataFrame(row["budget"]["categories"]), hide_index=True)
                    st.write("Method: " + row["budget"]["planning"]["method"]["name"])
                    if row["previous"]:
                        st.write("Saved plan being replaced", row["previous"])
            for question in preview["questions"]:
                st.warning(question)
            approved = st.checkbox(
                "I confirm the income, savings, complete expense coverage and exact limits for every month shown, including any replacements.",
                key=key + preview["preview_id"] + "-approve",
            )
            if st.button(
                "Confirm multi-month plan",
                disabled=not preview["ready"] or not approved,
                key=key + "-confirm",
            ):
                saved = backend_call(
                    lambda: client.confirm_budget_months(user_id, preview["preview_id"])
                )
                st.session_state.pop(key + "-preview", None)
                if saved:
                    st.success("Saved plans for " + ", ".join(saved["periods"]))


def render_review_preferences(client, user_id):
    key = "review-preferences-" + user_id
    with st.expander("Periodic budget reviews", icon=":material/notifications_active:"):
        st.caption(
            "Optional reminders appear in Overview and Budget when you open the app. Weekly reviews cover the current month; monthly reviews cover the last completed month. No background messages or automatic budget changes."
        )
        if st.button("Open review preferences", key=key + "-open"):
            prefs = backend_call(lambda: client.get_review_preferences(user_id))
            if prefs is not None:
                st.session_state[key] = prefs
                st.session_state[key + "-due"] = backend_call(
                    lambda: client.get_due_review(user_id)
                )
        if key not in st.session_state:
            return
        prefs = st.session_state[key]
        with st.form(key + "-form"):
            enabled = st.checkbox("Enable in-app budget review reminders", value=prefs["enabled"])
            cadence = st.selectbox(
                "Review frequency",
                ["weekly", "monthly"],
                index=["weekly", "monthly"].index(prefs["cadence"]),
            )
            next_on = st.date_input(
                "Next review date",
                value=date.fromisoformat(prefs["next_review_on"])
                if prefs.get("next_review_on")
                else None,
            )
            confirmed = st.checkbox("I confirm these review preferences.")
            save = st.form_submit_button("Save review preferences")
        if save:
            if not confirmed or (enabled and next_on is None):
                st.warning("Confirm the preferences and select a date when enabling reviews.")
            else:
                result = backend_call(
                    lambda: client.save_review_preferences(
                        user_id,
                        {
                            "enabled": enabled,
                            "cadence": cadence,
                            "next_review_on": next_on.isoformat() if next_on else None,
                            "confirmed": True,
                        },
                    )
                )
                if result:
                    st.session_state[key] = result
                    st.session_state[key + "-due"] = backend_call(
                        lambda: client.get_due_review(user_id)
                    )
                    st.success("Review preferences saved.")
        if st.button("Refresh due review", key=key + "-refresh"):
            st.session_state[key + "-due"] = backend_call(lambda: client.get_due_review(user_id))
        due = st.session_state.get(key + "-due") or {}
        if due.get("message"):
            st.info(due["message"])
        review = due.get("review")
        if review:
            st.write("Review month: " + due["period_start"])
            for warning in review.get("warnings", []):
                st.caption(warning)
            st.dataframe(pd.DataFrame(review.get("categories", [])), hide_index=True)
            st.caption(
                "Use the spending review panel to inspect suggested changes. Marking this review complete only schedules the next reminder."
            )
            if st.button("Mark reviewed", key=key + "-ack"):
                result = backend_call(
                    lambda: client.acknowledge_budget_review(user_id, due["evidence"])
                )
                if result:
                    st.session_state[key + "-due"] = result
                    st.session_state[key] = backend_call(
                        lambda: client.get_review_preferences(user_id)
                    )
                    st.rerun()
