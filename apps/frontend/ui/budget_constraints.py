"""Confirmed commitments, alternative previews and adoption into the existing editor."""

import pandas as pd
import streamlit as st

from ui.components import backend_call


def render_commitments(client, user_id, period, categories, draft_key):
    key = f"commitments-{user_id}-{period}"
    with st.expander("Fund goals and protect commitments", icon=":material/shield:"):
        if st.button("Open commitments", key=key + "-open"):
            stored = backend_call(lambda: client.get_budget_commitments(user_id, period))
            goals = backend_call(lambda: client.list_goals(user_id))
            if stored is not None and goals is not None:
                st.session_state[key] = stored
                st.session_state[key + "-goals"] = goals
        if key not in st.session_state:
            return
        policy = st.session_state[key].get("policy", {})
        st.caption(
            "Set minimums, including zero where appropriate. The reduction limit is measured against the saved limits when you confirm these commitments. Goal contributions share the savings allocation."
        )
        with st.form(key + "-form"):
            protected = st.multiselect(
                "Protected categories",
                sorted(set(categories) | set(policy.get("protected_categories", []))),
                default=policy.get("protected_categories", []),
            )
            minimum = st.number_input(
                "Minimum monthly savings (SGD)", min_value=0.0, value=policy.get("minimum_savings")
            )
            maximum = st.number_input(
                "Maximum reduction per adjustable category (%)",
                min_value=0.0,
                max_value=100.0,
                value=policy.get("max_reduction_percent"),
            )
            floors = st.data_editor(
                pd.DataFrame(
                    [
                        {"category": k, "minimum": v}
                        for k, v in policy.get("category_floors", {}).items()
                    ],
                    columns=["category", "minimum"],
                ),
                num_rows="dynamic",
                hide_index=True,
                key=key + "-floors",
            )
            st.caption(
                "Debt minimums are expense commitments. Put repayments in the same category as any corresponding scheduled bill to avoid counting that bill twice."
            )
            debts = st.data_editor(
                pd.DataFrame(
                    policy.get("debts", []),
                    columns=["name", "category", "balance", "minimum_payment"],
                ),
                num_rows="dynamic",
                hide_index=True,
                key=key + "-debts",
            )
            contributions = []
            prior = {g["goal_id"]: g["monthly_amount"] for g in policy.get("goals", [])}
            for goal in st.session_state[key + "-goals"]:
                if goal["target_amount"]["currency"] != "SGD":
                    continue
                enabled = st.checkbox(
                    "Fund goal: " + goal["name"],
                    value=goal["id"] in prior,
                    key=key + goal["id"] + "-enabled",
                )
                amount = st.number_input(
                    "Monthly contribution: " + goal["name"],
                    min_value=0.0,
                    value=prior.get(goal["id"]),
                    key=key + goal["id"] + "-amount",
                )
                if enabled:
                    contributions.append({"goal_id": goal["id"], "monthly_amount": amount})
            confirmed = st.checkbox(
                "I confirm these minimums, protected categories, reduction limit, selected goals and debt commitments."
            )
            save = st.form_submit_button("Save commitments")
        if save:
            if not confirmed or minimum is None or maximum is None:
                st.warning(
                    "Enter the savings minimum and reduction limit, then confirm your commitments."
                )
            else:
                try:
                    floor_rows = floors.to_dict("records")
                    if (
                        floors.isna().any().any()
                        or debts.isna().any().any()
                        or any(g["monthly_amount"] is None for g in contributions)
                    ):
                        raise ValueError(
                            "Complete every minimum, debt and selected goal amount, or remove the incomplete row."
                        )
                    if len(
                        {" ".join(str(r["category"]).split()).lower() for r in floor_rows}
                    ) != len(floor_rows):
                        raise ValueError("Use one minimum per category.")
                    payload = {
                        "period_start": period.isoformat(),
                        "confirmed": True,
                        "minimum_savings": minimum,
                        "max_reduction_percent": maximum,
                        "protected_categories": protected,
                        "category_floors": {r["category"]: float(r["minimum"]) for r in floor_rows},
                        "goals": contributions,
                        "debts": debts.to_dict("records"),
                    }
                    result = backend_call(lambda: client.save_budget_commitments(user_id, payload))
                    if result:
                        st.session_state[key] = result
                        st.session_state.pop(key + "-result", None)
                        st.success("Commitments saved. Budget limits have not changed.")
                except (ValueError, TypeError) as error:
                    st.warning(str(error))
        income = st.number_input(
            "Alternative take-home income, if changing (SGD)",
            min_value=0.0,
            value=None,
            key=key + "-income",
        )
        savings = st.number_input(
            "Alternative savings target, if changing (SGD)",
            min_value=0.0,
            value=None,
            key=key + "-savings",
        )
        if st.button("Find funded alternatives", key=key + "-calculate"):
            result = backend_call(
                lambda: client.budget_alternatives(
                    user_id,
                    {
                        "period_start": period.isoformat(),
                        "take_home_income": income,
                        "savings_target": savings,
                    },
                )
            )
            st.session_state[key + "-result"] = result
        result = st.session_state.get(key + "-result")
        if not result:
            return
        for question in result.get("questions", []):
            st.info(question)
        commitments = result.get("commitments", {})
        if commitments.get("goals"):
            st.dataframe(
                pd.DataFrame(commitments["goals"]).drop(columns=["goal_id"]), hide_index=True
            )
        options = result.get("results", [])
        if not options:
            return
        rows = [{"Option": item["name"], **(item.get("totals") or {})} for item in options]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        chosen = st.selectbox(
            "Funded option", [item["name"] for item in options], key=key + "-choice"
        )
        candidate = next(item for item in options if item["name"] == chosen)
        st.dataframe(
            pd.DataFrame(candidate["draft"]["categories"])[["category", "limit_amount"]],
            hide_index=True,
        )
        for question in candidate.get("questions", []):
            st.warning(question)
        st.caption(
            "Use an option as a draft, then confirm actual income, coverage and Save in the editor above. An unfunded option cannot be saved."
        )
        if st.button("Use funded option in editor", key=key + "-adopt"):
            st.session_state[draft_key] = candidate["draft"]
            st.rerun()
