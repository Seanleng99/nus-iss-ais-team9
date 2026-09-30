import pandas as pd
import streamlit as st

from ui.components import backend_call


def render_tradeoffs(client,user_id,period):
    key=f"tradeoffs-{user_id}-{period}"
    with st.expander("Compare debt repayment and goal contributions",icon=":material/balance:"):
        if st.button("Open repayment comparison",key=key+"-open"):
            data=backend_call(lambda:client.get_budget_workspace(user_id))
            if data is not None:
                st.session_state[key]=data
        data=st.session_state.get(key)
        if not data:
            return
        policy=(data["settings"].get("constraints:"+str(period)) or {}).get("policy",{})
        debts=policy.get("debts",[])
        if not debts:
            st.info("Save this month's debt commitments before comparing repayment choices.")
            return
        st.dataframe(pd.DataFrame(debts)[["name","balance","minimum_payment"]],hide_index=True)
        with st.form(key+"-form"):
            terms=st.data_editor(pd.DataFrame([{"commitment_name":d["name"],"annual_rate_percent":None,"monthly_fee":None} for d in debts]),hide_index=True,disabled=["commitment_name"],key=key+"-terms",
                column_config={"annual_rate_percent":st.column_config.NumberColumn("Annual rate (%)",min_value=0,max_value=300,required=True),"monthly_fee":st.column_config.NumberColumn("Fixed monthly fee (SGD)",min_value=0,required=True)})
            st.caption("Enter zero explicitly for no interest or fees. Each case keeps existing goal contributions unless you provide changes through Coach.")
            cases=st.data_editor(pd.DataFrame(columns=["name","savings_target","extra_debt_payment"]),num_rows="dynamic",hide_index=True,key=key+"-cases",
                column_config={"savings_target":st.column_config.NumberColumn("Total savings per month",min_value=0,required=True),"extra_debt_payment":st.column_config.NumberColumn("Extra debt payment per month",min_value=0,required=True)})
            horizon=st.number_input("Projection months",min_value=1,max_value=360,value=60)
            rollover=st.selectbox("After a debt is paid off",["Choose a rule","Keep its minimum payment available for other debts","Release its minimum payment from the repayment pool"])
            accepted=st.checkbox("Use nominal annual interest divided by 12, fixed fees and end-of-month payments for this illustration.")
            submit=st.form_submit_button("Compare repayment cases")
        if submit:
            st.session_state.pop(key+"-result",None)
            if terms.isna().any().any() or cases.empty or cases.isna().any().any() or rollover=="Choose a rule" or not accepted:
                st.warning("Supply every rate, fee and case amount, and choose the repayment assumptions.")
            else:
                result=backend_call(lambda:client.preview_workspace_change(user_id,"debt_compare",{"period_start":str(period),"terms":terms.to_dict("records"),"cases":cases.to_dict("records"),"horizon_months":horizon,"rollover_paid_minimums":rollover.startswith("Keep")}))
                st.session_state[key+"-result"]=result["details"] if result else None
        result=st.session_state.get(key+"-result")
        if result:
            for case in result["results"]:
                st.write(case["name"])
                if not case["monthly_funded"]:
                    st.warning(f"Unfunded case: monthly gap SGD {case['funding_gap']:,.2f}; savings allocation gap SGD {case['savings_allocation_gap']:,.2f}.")
                st.dataframe(pd.DataFrame([{k:v for k,v in s.items() if k not in {"timeline","paid_off_months"}} for s in case["strategies"]]),hide_index=True)
                chart=pd.concat([pd.DataFrame(s["timeline"]).set_index("month")["balance"].rename(s["strategy"]) for s in case["strategies"] if s["timeline"]],axis=1) if any(s["timeline"] for s in case["strategies"]) else None
                if chart is not None:
                    st.line_chart(chart)
                if case["goals"]:
                    st.dataframe(pd.DataFrame(case["goals"]).drop(columns=["goal_id"]),hide_index=True)
                for q in case["requires_commitment_changes"]:
                    st.info(q)
            for warning in result["warnings"]:
                st.caption(warning)
