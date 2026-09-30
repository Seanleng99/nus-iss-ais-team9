from datetime import date
from uuid import uuid4

import pandas as pd
import streamlit as st

from ui.components import backend_call


def render_income_and_reserves(client, user_id, period, draft_key):
    key=f"income-{user_id}-{period}"
    with st.expander("Variable income and irregular costs", icon=":material/savings:"):
        with st.form(key+"-income"):
            low=st.number_input("Low take-home income (SGD)",min_value=0.0,value=None)
            expected=st.number_input("Expected take-home income (SGD)",min_value=0.0,value=None)
            high=st.number_input("High take-home income (SGD)",min_value=0.0,value=None)
            compare=st.form_submit_button("Compare income cases")
        if compare:
            if any(v is None for v in [low,expected,high]):
                st.warning("Supply all three hypothetical take-home amounts.")
            else:
                st.session_state[key+"-cases"]=backend_call(lambda: client.compare_income_cases(user_id,{"period_start":str(period),"low":low,"expected":expected,"high":high}))
        comparison=st.session_state.get(key+"-cases")
        if comparison:
            st.dataframe(pd.DataFrame([{"Case":r["name"],**(r["totals"] or {})} for r in comparison["results"]]),hide_index=True)
            for q in comparison["questions"]:
                st.caption(q)
            names={r["name"]:r for r in comparison["results"]}
            chosen=st.selectbox("Income case to review",list(names))
            from ui.budget_timing import render_timing_summary
            render_timing_summary(names[chosen].get("cashflow"))
            if st.button("Use income case as an unsaved draft",key=key+"-adopt"):
                draft=names[chosen]["draft"]
                draft["planning"]["income_basis"]="unknown"
                draft["planning"]["expenses_confirmed"]=False
                st.session_state[draft_key]=draft
                st.rerun()
        if st.button("Open irregular-expense reserves",key=key+"-open"):
            data=backend_call(lambda: client.get_budget_workspace(user_id))
            if data is not None:
                st.session_state[key+"-reserves"]=(data["settings"].get("reserves") or {}).get("reserves",[])
        if key+"-reserves" not in st.session_state:
            return
        st.caption("Set aside savings for annual bills or purchases. These contributions share your savings allocation with goals; no money is moved.")
        rows=[{**r,"start_period":date.fromisoformat(r["start_period"]),"due_on":date.fromisoformat(r["due_on"])} for r in st.session_state[key+"-reserves"]]
        with st.form(key+"-reserve-form"):
            edited=st.data_editor(pd.DataFrame(rows,columns=["id","name","target_amount","current_reserved","monthly_contribution","start_period","due_on"]),num_rows="dynamic",hide_index=True,
                column_config={"id":None,"start_period":st.column_config.DateColumn("Start month (first day)"),"due_on":st.column_config.DateColumn("Due date")})
            preview=st.form_submit_button("Preview reserves")
        if preview:
            st.session_state.pop(key+"-pending",None)
            if edited.drop(columns=["id"]).isna().any().any():
                st.warning("Complete each reserve's amounts and dates, or remove the row.")
            else:
                payload={"reserves":[{**r,"id":r["id"] if pd.notna(r.get("id")) else str(uuid4()),"start_period":r["start_period"].isoformat(),"due_on":r["due_on"].isoformat()} for r in edited.to_dict("records")]}
                st.session_state[key+"-pending"]=backend_call(lambda: client.preview_workspace_change(user_id,"reserves",payload))
        pending=st.session_state.get(key+"-pending")
        if pending:
            st.dataframe(pd.DataFrame(pending["target"]["reserves"]).drop(columns=["id"],errors="ignore"),hide_index=True)
            st.caption("This replaces the reserve list shown above. Existing goal contributions and reserves must fit in the same savings allocation.")
            if st.button("Confirm reserve changes",key=key+"-confirm") and backend_call(lambda: client.confirm_workspace_change(user_id,pending["preview_id"])):
                st.session_state[key+"-reserves"]=pending["target"]["reserves"]
                st.session_state.pop(key+"-pending",None)
                st.rerun()
