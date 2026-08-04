import httpx
import streamlit as st

from client import ask_coach, build_request, build_snapshot

st.set_page_config(page_title="AI Financial Wellness Coach", layout="wide")

st.title("AI Financial Wellness Coach")
st.caption("Financial education for budgeting, spending, goals, and investing basics")

with st.sidebar:
    st.subheader("Monthly snapshot")
    user_id = st.text_input("Profile", value="demo-user")
    monthly_income = st.number_input("Income (SGD)", min_value=0.0, step=100.0, value=4200.0)
    housing = st.number_input("Housing (SGD)", min_value=0.0, step=50.0, value=1400.0)
    food = st.number_input("Food (SGD)", min_value=0.0, step=25.0, value=600.0)
    transport = st.number_input("Transport (SGD)", min_value=0.0, step=25.0, value=180.0)

with st.form("coach-request"):
    message = st.text_area(
        "Your question",
        value="Help me create a monthly budget and save for an emergency fund.",
        height=120,
        max_chars=5000,
    )
    submitted = st.form_submit_button("Get guidance", use_container_width=True)

if submitted:
    if not message.strip():
        st.warning("Enter a financial wellness question.")
    else:
        snapshot = build_snapshot(monthly_income, housing, food, transport)
        payload = build_request(user_id, message, snapshot)
        try:
            with st.spinner("Reviewing your financial snapshot..."):
                response = ask_coach(payload)
        except httpx.HTTPStatusError as error:
            st.error(f"The coach rejected the request ({error.response.status_code}).")
        except httpx.HTTPError:
            st.error("The coaching service is temporarily unavailable.")
        else:
            if response.get("blocked"):
                st.warning(response["answer"])
            else:
                st.success(response["answer"])

            agents = response.get("selected_agents", [])
            if agents:
                agent_names = ", ".join(
                    name.replace("_", " ").title() for name in agents
                )
                st.caption(f"Agents: {agent_names}")

            result_tab, rationale_tab, audit_tab = st.tabs(
                ["Agent results", "Rationale", "Audit"]
            )
            with result_tab:
                for result in response.get("agent_results", []):
                    st.subheader(result["agent"].replace("_", " ").title())
                    st.write(result["summary"])
                    st.progress(result.get("confidence", 0.0), text="Confidence")
            with rationale_tab:
                for result in response.get("agent_results", []):
                    for reason in result.get("rationale", []):
                        st.write(f"- {reason}")
                for disclaimer in response.get("disclaimers", []):
                    st.info(disclaimer)
            with audit_tab:
                st.json(response.get("audit", {}), expanded=False)
