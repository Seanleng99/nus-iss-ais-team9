import pandas as pd
import streamlit as st

from ui.components import money
from ui.i18n import display_frame, ui_message, ui_text


def render_timing_summary(result, *, chart=False):
    if not result:
        return
    if result["status"] == "needs_input":
        for question in result["questions"]:
            st.info(ui_message(question))
    if result.get("lowest_available") is None:
        return
    st.metric(ui_text('Lowest projected spendable balance'), money(result["lowest_available"]))
    st.caption(ui_text('Minimum balance: {v0} · Calculated as of {v1}', v0=money(result['minimum_balance']), v1=result['as_of']))
    if result["first_below_buffer_on"]:
        st.warning(ui_text('Projected below your minimum on {v0}; gap {v1}.', v0=result['first_below_buffer_on'], v1=money(result['buffer_gap'])))
    elif result["status"] == "within_buffer":
        st.success(ui_text('This plan stays within your chosen minimum balance under the selected timing.'))
    if chart and result["days"]:
        frame = pd.DataFrame(result["days"]).set_index("date")
        frame["minimum_balance"] = result["minimum_balance"]
        st.line_chart(display_frame(frame[["projected_available", "minimum_balance"]]))
    if result.get("upcoming_bills"):
        st.dataframe(display_frame(pd.DataFrame(result["upcoming_bills"])[["name", "due_on", "amount", "status"]]), hide_index=True)
    for text in result.get("suggestions", []) + result.get("warnings", []):
        st.caption(ui_message(text))
