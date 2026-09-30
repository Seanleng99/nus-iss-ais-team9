
import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_timing_summary(result, *, chart=False):
    if not result:
        return
    if result["status"] == "needs_input":
        for question in result["questions"]:
            st.info(question)
    if result.get("lowest_available") is None:
        return
    st.metric("Lowest projected spendable balance", money(result["lowest_available"]))
    st.caption(f"Minimum balance: {money(result['minimum_balance'])} · Calculated as of {result['as_of']}")
    if result["first_below_buffer_on"]:
        st.warning(f"Projected below your minimum on {result['first_below_buffer_on']}; gap {money(result['buffer_gap'])}.")
    elif result["status"] == "within_buffer":
        st.success("This plan stays within your chosen minimum balance under the selected timing.")
    if chart and result["days"]:
        frame = pd.DataFrame(result["days"]).set_index("date")
        frame["minimum_balance"] = result["minimum_balance"]
        st.line_chart(frame[["projected_available", "minimum_balance"]])
    if result.get("upcoming_bills"):
        st.dataframe(pd.DataFrame(result["upcoming_bills"])[["name", "due_on", "amount", "status"]], hide_index=True)
    for text in result.get("suggestions", []) + result.get("warnings", []):
        st.caption(text)


def render_timing(client, user_id, period):
    key = f"timing-{user_id}-{period}"
    with st.expander("Can this plan last until payday?", icon=":material/event_available:"):
        if st.button("Open timing assessment", key=key+"-open"):
            st.session_state[key] = backend_call(lambda: client.get_budget_timing(user_id, period))
        if key not in st.session_state:
            return
        with st.form(key+"-settings"):
            start = st.date_input("Start planning remaining spending on", value=None)
            minimum = st.number_input("Minimum spendable balance (SGD)", min_value=0.0, value=None)
            patterns = {"Evenly each day": "even_daily", "All at the start": "start_of_period", "All at month end": "end_of_period"}
            pattern = st.selectbox("When will remaining expense limits be spent?", ["Choose timing", *patterns])
            savings = st.date_input("Reserve this month's full savings allocation on", value=None)
            complete = st.checkbox("My recorded expenses and unpaid bill/payday schedules cover this month, without duplicate recorded income.")
            submit = st.form_submit_button("Preview timing assumptions")
        if submit:
            st.session_state.pop(key+"-pending", None)
            if not start or minimum is None or pattern not in patterns or not savings or not complete:
                st.warning("Choose every timing input and confirm record coverage.")
            else:
                pending = backend_call(lambda: client.preview_workspace_change(user_id, "timing", {"period_start": str(period), "start_on": str(start), "minimum_balance": minimum, "expense_pattern": patterns[pattern], "savings_on": str(savings), "records_complete": True}))
                st.session_state[key+"-pending"] = pending
        pending = st.session_state.get(key+"-pending")
        if pending:
            target = pending["target"]
            st.write(f"From {target['start_on']}: {target['expense_pattern'].replace('_', ' ')} spending; savings reserved {target['savings_on']}; minimum {money(target['minimum_balance'])}.")
            if st.button("Confirm timing assumptions", key=key+"-confirm") and backend_call(lambda: client.confirm_workspace_change(user_id, pending["preview_id"])):
                st.session_state.pop(key+"-pending", None)
                st.session_state[key] = backend_call(lambda: client.get_budget_timing(user_id, period))
                st.rerun()
        render_timing_summary(st.session_state.get(key), chart=True)
