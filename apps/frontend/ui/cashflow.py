from datetime import date, timedelta
from uuid import uuid4

import pandas as pd
import streamlit as st

from ui.components import backend_call, money


def render_cashflow(client, user_id):
    with st.expander("Cash flow, paydays and bills", icon=":material/calendar_month:"):
        key = f"cashflow-{user_id}"
        if st.button("Open cash-flow planner", key=f"{key}-open"):
            st.session_state[key] = (
                backend_call(lambda: client.get_cashflow_settings(user_id)) or {}
            )
        if key not in st.session_state:
            return
        saved = st.session_state[key]
        st.caption(
            "Opening balance is at the start of its date. Add explicit schedules; mark paid/received occurrences settled after recording them to prevent double counting."
        )
        with st.form(f"{key}-settings"):
            opening_on = st.date_input(
                "Opening balance date",
                value=date.fromisoformat(saved["opening_on"]) if saved else None,
            )
            balance = st.number_input(
                "Opening combined balance (SGD)",
                value=float(saved["opening_balance"]) if saved else None,
            )
            rows = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "kind": item["kind"],
                    "category": item["category"],
                    "amount": item["amount"],
                    "first_on": date.fromisoformat(item["first_on"]),
                    "frequency": item["frequency"],
                }
                for item in saved.get("schedules", [])
            ]
            frame = pd.DataFrame(
                rows, columns=["id", "name", "kind", "category", "amount", "first_on", "frequency"]
            )
            edited = st.data_editor(
                frame,
                num_rows="dynamic",
                hide_index=True,
                key=f"{key}-events",
                column_config={
                    "id": None,
                    "kind": st.column_config.SelectboxColumn(
                        "Flow", options=["income", "expense"], required=True
                    ),
                    "frequency": st.column_config.SelectboxColumn(
                        "Frequency",
                        options=["once", "weekly", "fortnightly", "monthly", "yearly"],
                        required=True,
                    ),
                    "first_on": st.column_config.DateColumn("First due date", required=True),
                    "amount": st.column_config.NumberColumn(
                        "Amount (SGD)", min_value=0.01, required=True
                    ),
                },
            )
            confirmed = st.checkbox(
                "I confirm the opening balance and schedule amounts, dates and frequencies."
            )
            save = st.form_submit_button("Save cash-flow settings")
        if save:
            if opening_on is None or balance is None or not confirmed:
                st.warning("Supply and confirm the opening date, balance and schedules.")
            else:
                schedules = []
                prior = {row["id"]: row for row in saved.get("schedules", [])}
                try:
                    for row in edited.to_dict("records"):
                        if any(
                            pd.isna(row.get(field))
                            for field in (
                                "name",
                                "kind",
                                "category",
                                "amount",
                                "first_on",
                                "frequency",
                            )
                        ):
                            raise ValueError("Complete every schedule row or remove it.")
                        identifier = row["id"] if pd.notna(row.get("id")) else str(uuid4())
                        schedules.append(
                            {
                                **prior.get(identifier, {}),
                                **row,
                                "id": identifier,
                                "first_on": row["first_on"].isoformat(),
                            }
                        )
                    result = backend_call(
                        lambda: client.save_cashflow_settings(
                            user_id,
                            {
                                "opening_on": opening_on.isoformat(),
                                "opening_balance": balance,
                                "confirmed": True,
                                "schedules": schedules,
                            },
                        )
                    )
                    if result:
                        st.session_state[key] = result
                        st.session_state.pop(f"{key}-projection", None)
                        st.success("Cash-flow settings saved.")
                except (ValueError, AttributeError) as error:
                    st.warning(str(error))
        through = st.date_input(
            "Project through",
            value=date.fromisoformat(saved["opening_on"]) + timedelta(days=60) if saved else None,
            key=f"{key}-through",
        )
        if st.button("Calculate cash flow", key=f"{key}-calculate") and through:
            st.session_state[f"{key}-projection"] = backend_call(
                lambda: client.get_cashflow(user_id, through)
            )
        projection = st.session_state.get(f"{key}-projection")
        if projection:
            for warning in projection.get("warnings", projection.get("questions", [])):
                st.caption(warning)
            if not projection.get("needs_input"):
                st.metric("Lowest projected balance", money(projection["lowest_balance"]))
                if projection["first_shortfall_on"]:
                    st.warning("Projected cash shortage begins " + projection["first_shortfall_on"])
                st.line_chart(
                    pd.DataFrame(projection["days"]).set_index("date")[
                        ["projected_closing_balance"]
                    ]
                )
                st.dataframe(
                    pd.DataFrame(projection["days"])[
                        ["date", "recorded_net", "projected_closing_balance"]
                    ],
                    hide_index=True,
                )
        if saved.get("schedules"):
            choices = {item["id"]: item["name"] for item in saved["schedules"]}
            selected = st.selectbox(
                "Paid or received schedule",
                list(choices),
                format_func=choices.get,
                key=f"{key}-settled-id",
            )
            settled_on = st.date_input("Occurrence due date", value=None, key=f"{key}-settled-date")
            if st.button("Mark occurrence settled", key=f"{key}-settle") and settled_on:
                result = backend_call(lambda: client.settle_cashflow(user_id, selected, settled_on))
                if result:
                    st.session_state[key] = result
                    st.session_state.pop(f"{key}-projection", None)
                    st.success("Occurrence marked settled. Recalculate the projection.")
