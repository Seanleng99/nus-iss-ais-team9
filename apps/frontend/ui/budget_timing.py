
import pandas as pd
import streamlit as st

from ui.components import money


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
