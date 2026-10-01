"""Review explicit transaction-to-bill allocations before confirmation."""

import json

import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_reconciliation(client, user_id):
    key = f"matches-{user_id}"
    st.subheader("Match payments, income and refunds")
    if st.button("Open bill matching", key=key + "-open"):
        st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id))
        st.session_state.pop(key + "-preview", None)
    data = st.session_state.get(key)
    if not data:
        return
    schedules = [
        s
        for s in (data["settings"].get("cashflow") or {}).get("schedules", [])
    ]
    search = st.text_input("Search recorded descriptions", key=key+"-search")
    if st.button("Search records", key=key+"-search-button"):
        st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id, search=search))
        st.session_state.pop(key+"-preview", None)
        st.rerun()
    page = data["reconciliation"]
    st.caption(f"Showing from record {page.get('offset', 0)+1}; {page.get('total', len(page['transactions']))} matches.")
    if page.get("offset",0) and st.button("Previous records", key=key+"-previous"):
        st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id, search=search, offset=max(page["offset"]-100,0)))
        st.session_state.pop(key+"-preview",None)
        st.rerun()
    if page.get("has_more") and st.button("Next records", key=key+"-next"):
        st.session_state[key] = backend_call(lambda: client.get_budget_workspace(user_id, search=search, offset=page["offset"]+100))
        st.session_state.pop(key+"-preview",None)
        st.rerun()
    records = data["reconciliation"]["transactions"]
    st.caption(
        "Choose a recorded expense, income or refund and its bill/payday occurrence. Partial amounts are supported; unmatched amounts remain available. No money is moved."
    )
    if schedules and records:
        with st.container(border=True):
            record_choices = {
                r["id"]: r for r in records
            }
            bill_choices = {s["id"]: s for s in schedules}
            record_labels = {r["id"]: f"{r['occurred_on']} · {r['description']} · {r['type']} · {money(r['unallocated'])} available · record {i+1}" for i, r in enumerate(records)}
            bill_labels = {s["id"]: s["name"] + (f" · bill {i+1}" if sum(t["name"] == s["name"] for t in schedules) > 1 else "") for i, s in enumerate(schedules)}
            record = record_choices.get(
                st.selectbox("Recorded payment or refund", ["Choose a record", *record_choices], format_func=lambda value: record_labels.get(value, value))
            )
            bill = bill_choices.get(st.selectbox("Bill", ["Choose a bill", *bill_choices], format_func=lambda value: bill_labels.get(value, value)))
            due = st.date_input("Bill occurrence due date", value=None)
            amount = st.number_input("Amount to match (SGD)", min_value=0.01, value=None)
            labels = {
                "payment": "Payment",
                "income": "Income received",
                "refund_reopens": "Refund — amount becomes payable again",
                "refund_reduces_due": "Refund — bill amount is reduced",
            }
            effect = {"expense": "payment", "income": "income"}.get(record["type"]) if record else None
            spending = None
            if record and record["type"] == "refund":
                effect_label = st.selectbox("After this refund, is the amount still payable?", ["Choose", labels["refund_reopens"], labels["refund_reduces_due"]])
                effect = next((k for k, v in labels.items() if v == effect_label), None)
                treatment = st.selectbox("Should this refund reduce recorded budget spending?", ["Choose", "Keep recorded spending unchanged", "Reduce spending in the refund month"])
                spending = {"Keep recorded spending unchanged":"cash_only", "Reduce spending in the refund month":"reduce_expense"}.get(treatment)
            preview = st.button("Preview bill match", key=key + "-match-preview")
        selection = json.dumps([record["id"] if record else None, bill["id"] if bill else None, str(due), amount, effect, spending])
        old = st.session_state.get(key + "-preview")
        if old and old.get("_source") == "manual" and old.get("_selection") != selection:
            st.session_state.pop(key + "-preview", None)
        if preview:
            st.session_state.pop(key + "-preview", None)
            if record and bill and due and amount is not None and effect and (record["type"] != "refund" or spending):
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
                            "spending_treatment": spending,
                        },
                    )
                )
                if st.session_state.get(key + "-preview"):
                    st.session_state[key + "-preview"].update(_source="manual", _selection=selection)
            else:
                st.warning("Choose the record, bill, occurrence date, amount and effect.")
    if records:
        choices = {r["id"]: r for r in records}
        descriptions = {r["id"]: f"{r['occurred_on']} · {r['description']} · record {i+1}" for i, r in enumerate(records)}
        chosen_record = choices.get(st.selectbox("Find possible matches for", ["Choose a record", *choices], format_func=lambda value: descriptions.get(value, value), key=key+"-suggest-record"))
        if st.button("Find possible matches", key=key+"-suggest") and chosen_record:
            found = backend_call(lambda: client.get_match_candidates(user_id, chosen_record["id"]))
            st.session_state[key+"-candidates"] = {"record_id":chosen_record["id"], "result":found} if found else None
        stored_candidates = st.session_state.get(key+"-candidates")
        if stored_candidates and chosen_record and stored_candidates["record_id"] == chosen_record["id"]:
            found = stored_candidates["result"]
            st.caption(found.get("warning", "No automatic matches."))
            options = {f"{c['name']} · {c['due_on']} · {money(c['suggested_amount'])}":c for c in found["candidates"]}
            candidate = options.get(st.selectbox("Possible occurrence", ["Choose an occurrence", *options], key=key+"-candidate"))
            if candidate:
                amount = st.number_input("Suggested match amount (SGD)", min_value=0.01, value=float(candidate["suggested_amount"]), key=key+"-candidate-amount")
                effect = {"expense": "payment", "income": "income"}.get(chosen_record["type"])
                treatment = None
                if chosen_record["type"] == "refund":
                    effects = {"Refund makes the amount payable again": "refund_reopens", "Refund reduces the bill amount": "refund_reduces_due"}
                    choice = st.selectbox("Refund effect", ["Choose", *effects], key=key+"-candidate-effect")
                    effect = effects.get(choice)
                    treatments = {"Keep recorded spending unchanged": "cash_only", "Reduce spending in the refund month": "reduce_expense"}
                    choice = st.selectbox("Refund spending choice", ["Choose", *treatments], key=key+"-candidate-treatment")
                    treatment = treatments.get(choice)
                selection = json.dumps([chosen_record["id"], candidate["schedule_id"], candidate["due_on"], amount, effect, treatment])
                old = st.session_state.get(key+"-preview")
                if old and old.get("_source") == "suggestion" and old.get("_selection") != selection:
                    st.session_state.pop(key+"-preview", None)
                if st.button("Preview selected suggestion", key=key+"-candidate-preview"):
                    if effect and (chosen_record["type"] != "refund" or treatment):
                        st.session_state[key+"-preview"] = backend_call(lambda: client.preview_workspace_change(user_id,"reconcile",{"transaction_id":chosen_record["id"],"schedule_id":candidate["schedule_id"],"due_on":candidate["due_on"],"amount":amount,"effect":effect,"spending_treatment":treatment}))
                        if st.session_state.get(key+"-preview"):
                            st.session_state[key+"-preview"].update(_source="suggestion", _selection=selection)
                    else:
                        st.warning("Choose both refund effects before previewing the match.")
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
            f"{names.get(r['schedule_id'], 'Bill')} · {r['due_on']} · {money(r['amount'])} · {r['effect'].replace('_', ' ')} · match {i+1}": r
            for i, r in enumerate(existing)
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
            if details["match"].get("spending_treatment"):
                st.caption("Refund spending treatment: " + details["match"]["spending_treatment"].replace("_", " "))
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
