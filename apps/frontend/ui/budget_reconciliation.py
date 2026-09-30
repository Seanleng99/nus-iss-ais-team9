"""Review explicit transaction-to-bill allocations before confirmation."""

import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_reconciliation(client, user_id):
    key = f"matches-{user_id}"
    st.subheader("Match recorded payments and refunds")
    if st.button("Open bill matching", key=key + "-open"):
        st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id))
        st.session_state.pop(key + "-preview", None)
    data = st.session_state.get(key)
    if not data:
        return
    schedules = [
        s
        for s in (data["settings"].get("cashflow") or {}).get("schedules", [])
        if s["kind"] == "expense"
    ]
    records = data["reconciliation"]["transactions"]
    st.caption(
        "Choose a recorded expense or refund and the bill occurrence it belongs to. Partial amounts are supported; unmatched amounts remain available. No money is moved."
    )
    if schedules and records:
        with st.form(key + "-match"):
            record_choices = {
                f"{r['occurred_on']} · {r['description']} · {r['type']} · {money(r['unallocated'])} available ({r['id'][:8]})": r
                for r in records
            }
            bill_choices = {f"{s['name']} ({s['id'][:8]})": s for s in schedules}
            record = record_choices.get(
                st.selectbox("Recorded payment or refund", ["Choose a record", *record_choices])
            )
            bill = bill_choices.get(st.selectbox("Bill", ["Choose a bill", *bill_choices]))
            due = st.date_input("Bill occurrence due date", value=None)
            amount = st.number_input("Amount to match (SGD)", min_value=0.01, value=None)
            labels = {
                "payment": "Payment",
                "refund_reopens": "Refund — amount becomes payable again",
                "refund_reduces_due": "Refund — bill amount is reduced",
            }
            effect_label = st.selectbox(
                "How should this record affect the bill?", ["Choose an effect", *labels.values()]
            )
            effect = next((k for k, v in labels.items() if v == effect_label), None)
            preview = st.form_submit_button("Preview bill match")
        if preview:
            st.session_state.pop(key + "-preview", None)
            if record and bill and due and amount is not None and effect:
                st.session_state[key + "-preview"] = backend_call(
                    lambda: client.preview_workspace_change(
                        user_id,
                        "reconcile",
                        {
                            "transaction_id": record["id"],
                            "schedule_id": bill["id"],
                            "due_on": due.isoformat(),
                            "amount": amount,
                            "effect": effect,
                        },
                    )
                )
            else:
                st.warning("Choose the record, bill, occurrence date, amount and effect.")
    existing = data["reconciliation"]["links"]
    if existing:
        names = {s["id"]: s["name"] for s in schedules}
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Bill": names.get(r["schedule_id"], "Bill"),
                        "Due": r["due_on"],
                        "Amount": r["amount"],
                        "Effect": r["effect"],
                    }
                    for r in existing
                ]
            ),
            hide_index=True,
        )
        removal_choices = {
            f"{names.get(r['schedule_id'], 'Bill')} · {r['due_on']} · {money(r['amount'])} · {r['effect']} · {r['id'][:8]}": r
            for r in existing
        }
        selected = removal_choices.get(
            st.selectbox("Match to remove", ["Choose a match", *removal_choices])
        )
        if st.button("Preview removal", key=key + "-remove") and selected:
            st.session_state[key + "-preview"] = backend_call(
                lambda: client.preview_workspace_change(
                    user_id, "unlink", {"link_id": selected["id"]}
                )
            )
    pending = st.session_state.get(key + "-preview")
    if pending:
        details = pending["details"]
        if pending["operation"] == "reconcile":
            st.write(f"{details['transaction']} → {details['bill']}")
            st.write(
                f"Match {money(details['match']['amount'])} to {details['match']['due_on']}; {details['match']['effect'].replace('_', ' ')}."
            )
            st.metric(
                "Remaining bill amount",
                money(details["after"]["remaining"]),
                delta=details["after"]["remaining"] - details["before"]["remaining"],
                delta_color="inverse",
            )
        else:
            st.warning(
                "Remove the selected match. Its recorded transaction will be kept; the bill projection will be recalculated."
            )
        if st.button("Confirm reviewed change", key=key + "-confirm"):
            result = backend_call(
                lambda: client.confirm_workspace_change(user_id, pending["preview_id"])
            )
            st.session_state.pop(key + "-preview", None)
            if result:
                st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id))
                st.session_state.pop(f"cashflow-{user_id}-projection", None)
                st.success("Confirmed. Recalculate cash flow to see the updated projection.")
                st.rerun()
