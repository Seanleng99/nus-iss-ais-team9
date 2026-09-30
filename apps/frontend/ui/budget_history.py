import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_history(client,user_id,period,draft_key):
    key=f"history-{user_id}-{period}"
    with st.expander("Spending patterns and plan history",icon=":material/history:"):
        lookback=st.number_input("Completed months to review",min_value=2,max_value=12,value=3,key=key+"-lookback")
        if st.button("Review repeated overspending",key=key+"-review"):
            st.session_state[key+"-review"]=backend_call(lambda:client.adaptive_budget_review(user_id,period,lookback))
        review=st.session_state.get(key+"-review")
        if review:
            for warning in review["warnings"]:
                st.caption(warning)
            if review["suggestions"]:
                st.dataframe(pd.DataFrame([{k:v for k,v in r.items() if k!="observations"} for r in review["suggestions"]]),hide_index=True)
                selected=st.multiselect("Suggested categories to include in a draft",[r["category"] for r in review["suggestions"]],key=key+"-selected")
                if st.button("Review selected adjustments in editor",key=key+"-adopt") and selected:
                    baseline=review["baseline"]
                    limits=dict(baseline["categories"])
                    limits.update({r["category"]:r["suggested_limit"] for r in review["suggestions"] if r["category"] in selected})
                    planning={k:v for k,v in (baseline["planning"] or {}).items() if k!="version"}
                    if planning:
                        planning.update(income_basis="unknown",expenses_confirmed=False)
                    st.session_state[draft_key]={"period_start":str(period),"currency":"SGD","categories":[{"category":k,"limit_amount":v} for k,v in limits.items()],"planning":planning or None}
                    st.rerun()
            else:
                st.info("No repeated overrun meets the evidence threshold.")
        if st.button("Open saved versions",key=key+"-open"):
            st.session_state[key+"-versions"]=backend_call(lambda:client.get_budget_history(user_id,period))
        versions=st.session_state.get(key+"-versions")
        if versions:
            options={f"{v['saved_at']} · {v['reason']} · {v['id'][:8]}":v for v in reversed(versions)}
            chosen=st.selectbox("Version to inspect",list(options),key=key+"-version")
            version=options[chosen]
            st.dataframe(pd.DataFrame([{"Category":k,"Limit":v} for k,v in version["snapshot"]["categories"].items()]),hide_index=True)
            if version["snapshot"]["planning"]:
                st.write("Saved income",money(version["snapshot"]["planning"]["take_home_income"]))
                st.write("Saved savings",money(version["snapshot"]["planning"]["savings_target"]))
            if st.button("Preview restoration",key=key+"-restore"):
                st.session_state[key+"-pending"]=backend_call(lambda:client.preview_workspace_change(user_id,"restore",{"period_start":str(period),"version_id":version["id"]}))
        pending=st.session_state.get(key+"-pending")
        if pending:
            st.warning("This replaces the current plan with the version below. Current commitments are still checked. Other months stay unchanged.")
            st.dataframe(pd.DataFrame(pending["details"]["proposed"]["categories"]),hide_index=True)
            st.write("Planning settings",pending["details"]["proposed"]["planning"])
            if st.button("Confirm restoration",key=key+"-confirm") and backend_call(lambda:client.confirm_workspace_change(user_id,pending["preview_id"])):
                st.session_state.pop(key+"-pending",None)
                st.session_state[key+"-versions"]=backend_call(lambda:client.get_budget_history(user_id,period))
                st.success("Restored as a new saved version.")
