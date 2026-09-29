from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


class FakeBackendClient:
    def list_profiles(self) -> list[dict]:
        return [
            {
                "user_id": "alex",
                "display_name": "Alex Lee",
                "monthly_income": {"currency": "SGD", "amount": 6200},
                "risk_tolerance": "growth",
            },
            {
                "user_id": "sam",
                "display_name": "Sam Tan",
                "monthly_income": {"currency": "SGD", "amount": 4800},
                "risk_tolerance": "moderate",
            },
        ]

    def get_dashboard(self, user_id: str, period_start: object) -> None:
        return None


class NoProfilesClient:
    def list_profiles(self) -> list[dict]:
        return []


class SparseProfileClient:
    def __init__(self) -> None:
        self.saved_profile: dict | None = None
        self.deleted_user_id: str | None = None

    def get_profile(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "monthly_income": None,
            "risk_tolerance": None,
            "accessibility_preferences": [],
            "preferences": {},
        }

    def get_fairness_profile(self, user_id: str) -> dict:
        return {
            "consent": {"granted": True},
            "demographics": None,
        }

    def save_profile(self, user_id: str, payload: dict) -> dict:
        self.saved_profile = payload
        return {"user_id": user_id, **payload}

    def delete_profile(self, user_id: str) -> bool:
        self.deleted_user_id = user_id
        return True

    def get_data_lifecycle(self, user_id: str) -> dict:
        return {
            "policy_version": "data-lifecycle-v1",
            "retention": {
                "chat_history_days": 90,
                "orchestration_traces_days": 30,
            },
            "durable_memory": {"granted": False, "feature_enabled": False},
        }

    def delete_user_data(self, user_id: str, policy_version: str) -> dict:
        self.deleted_user_id = user_id
        return {"policy_version": policy_version, "deleted_counts": {"profiles": 1}}


class WorkspaceDefaultsClient:
    def get_dashboard(self, user_id: str, period_start: date) -> None:
        return None

    def list_transactions(self, user_id: str, period_start: date) -> list[dict]:
        return [
            {
                "id": "transaction-1",
                "occurred_on": "2026-08-01",
                "description": "Saved transaction",
                "category": "housing",
                "amount": {"currency": "SGD", "amount": 1200},
                "recurring": True,
            }
        ]

    def get_budget(self, user_id: str, period_start: date) -> dict:
        return {
            "categories": [
                {
                    "category": "housing",
                    "limit_amount": 1800,
                    "spent_amount": 1200,
                    "remaining_amount": 600,
                }
            ]
        }

    def list_goals(self, user_id: str) -> list[dict]:
        return [
            {
                "id": "goal-1",
                "name": "Saved goal",
                "target_amount": {"currency": "SGD", "amount": 10000},
                "current_amount": {"currency": "SGD", "amount": 1000},
                "target_months": 12,
            }
        ]


class CoachClient:
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.sessions: dict[str, dict] = {}

    def list_chat_sessions(self, user_id: str) -> list[dict]:
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "message_count": len(item["messages"]),
            }
            for item in self.sessions.values()
        ]

    def create_chat_session(
        self, user_id: str, title: str, session_id: str | None = None
    ) -> dict:
        session_id = session_id or "coach-session-1"
        session = {"id": session_id, "title": title, "messages": []}
        self.sessions[session_id] = session
        return session

    def get_chat_session(self, user_id: str, session_id: str) -> dict:
        return self.sessions[session_id]

    def rename_chat_session(self, user_id: str, session_id: str, title: str) -> dict:
        self.sessions[session_id]["title"] = title
        return self.sessions[session_id]

    def delete_chat_session(self, user_id: str, session_id: str) -> None:
        del self.sessions[session_id]

    def ask_coach(self, payload: dict) -> dict:
        self.questions.append(payload["message"])
        session = self.sessions[payload["session_id"]]
        sources = [
            {
                "source_id": "cpf-beginners-guide-to-investing",
                "title": "A beginner's guide to investing in Singapore",
                "issuing_organization": "CPF Board",
                "canonical_url": "https://www.cpf.gov.sg/example",
                "published_at": "2026-05-07",
                "document_filename": "cpf-investing-guide.md",
                "content_kind": "source_document",
            }
        ]
        session["messages"].extend(
            [
                {"role": "user", "content": payload["message"]},
                {
                    "role": "assistant",
                    "content": "Start by comparing essential spending with monthly income.",
                    "sources": sources,
                    "explanation": {
                        "trace_id": "trace-coach-session-1",
                        "selected_agents": ["budget"],
                        "routing_rationale": ["The question asks for budget guidance."],
                        "agent_results": [
                            {
                                "agent": "budget",
                                "rationale": ["The saved monthly income was used."],
                                "confidence": 0.76,
                                "blocked": False,
                            },
                            {
                                "agent": "risk_compliance",
                                "rationale": ["The answer remains educational."],
                                "confidence": 0.91,
                                "blocked": False,
                            },
                        ],
                        "blocked": False,
                        "prompt_set_version": "v4",
                    },
                },
            ]
        )
        return {
            "answer": "Start by comparing essential spending with monthly income.",
            "sources": sources,
        }


def test_multipage_app_renders_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = FakeBackendClient()
    app.run(timeout=30)

    assert not app.exception
    assert app.sidebar.selectbox[0].label == "Active profile"
    assert app.sidebar.selectbox[0].options == ["Alex Lee · alex", "Sam Tan · sam"]
    assert app.sidebar.selectbox[1].label == "Period"
    assert app.sidebar.selectbox[1].disabled is False
    assert app.session_state["active_user_id"] == "alex"
    page_links = {item.label: item for item in app.sidebar.get("page_link")}
    assert page_links["Overview"].proto.page == ""


def test_no_profiles_defaults_to_create_profile_and_disables_workspace() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = NoProfilesClient()
    app.session_state["active_user_id"] = "stale-profile"
    app.run(timeout=30)

    assert not app.exception
    assert "active_user_id" not in app.session_state
    assert [item.label for item in app.sidebar.selectbox] == ["Period"]
    assert app.sidebar.selectbox[0].disabled is True

    page_links = {item.label: item for item in app.sidebar.get("page_link")}
    assert page_links["Create profile"].proto.page == ""
    for label in [
        "Profile settings",
        "Overview",
        "Transactions",
        "Budget",
        "Goals",
        "Coach",
    ]:
        assert page_links[label].disabled is True
    assert page_links["Create profile"].disabled is False


def test_sparse_profile_inputs_start_empty_or_zero() -> None:
    app = AppTest.from_string("from ui.pages import profile_page\nprofile_page()")
    app.session_state["backend_client"] = SparseProfileClient()
    app.session_state["active_user_id"] = "sparse-user"
    app.run(timeout=30)

    assert not app.exception
    assert app.text_input[0].label == "Display name"
    assert app.text_input[0].value == ""
    assert [(item.label, item.value) for item in app.number_input] == [
        ("Monthly income (SGD)", 0.0),
        ("Household size", 0),
        ("Dependants", 0),
    ]
    assert all(item.value is None for item in app.selectbox)
    assert [item.value for item in app.multiselect] == [[], []]

    app.button(key="FormSubmitter:profile-Save profile").click().run(timeout=30)
    saved = app.session_state["backend_client"].saved_profile
    assert saved["risk_tolerance"] is None
    assert saved["household_size"] is None
    assert saved["preferences"] == {}


def test_profile_deletion_requires_confirmation() -> None:
    app = AppTest.from_string(
        "from ui.pages import profile_page\nprofile_page()"
    )
    app.session_state["backend_client"] = SparseProfileClient()
    app.session_state["active_user_id"] = "delete-user"
    app.session_state["coach_history"] = [{"role": "user", "content": "hello"}]
    app.session_state["coach_rename_open"] = True
    app.session_state["coach_delete_open"] = True
    app.run(timeout=30)

    delete_button = app.button(key="delete-profile-delete-user")
    assert not app.exception
    assert delete_button.disabled is True

    app.checkbox(key="delete-profile-confirmed-delete-user").check().run(timeout=30)
    app.button(key="delete-profile-delete-user").click().run(timeout=30)

    assert app.session_state["backend_client"].deleted_user_id == "delete-user"
    assert "active_user_id" not in app.session_state
    assert "coach_history" not in app.session_state
    assert "coach_rename_open" not in app.session_state
    assert "coach_delete_open" not in app.session_state
    assert app.session_state["profile_deleted_notice"] == "Workspace data deleted."
    assert app.session_state["profile_deleted_redirect"] is True


def _workspace_page(source: str) -> AppTest:
    app = AppTest.from_string(f"from ui.pages import {source}\n{source}()")
    app.session_state["backend_client"] = WorkspaceDefaultsClient()
    app.session_state["active_user_id"] = "workspace-user"
    app.session_state["active_period"] = date(2026, 8, 1)
    return app.run(timeout=30)


def test_overview_has_no_unsaved_input_defaults() -> None:
    app = _workspace_page("dashboard_page")

    assert not app.exception
    assert not app.text_input
    assert not app.number_input
    assert not app.selectbox
    assert not app.date_input


def test_transaction_inputs_start_empty_or_zero() -> None:
    app = _workspace_page("transactions_page")

    assert not app.exception
    assert [(item.label, item.value) for item in app.text_input] == [("Description", "")]
    assert {item.label: item.value for item in app.selectbox} == {
        "Category": None,
        "Filter by month": "2026-08",
        "Transaction": None,
    }
    assert [(item.label, item.value) for item in app.number_input] == [("Amount (SGD)", 0.0)]
    assert [(item.label, item.value) for item in app.date_input] == [("Date", None)]
    assert app.toggle[0].value is False


def test_budget_defaults_to_zero_except_saved_values() -> None:
    app = _workspace_page("budget_page")

    assert not app.exception
    values = {item.label: item.value for item in app.number_input}
    assert values["Housing (SGD)"] == 1800.0
    assert values["Scenario monthly take-home income (SGD)"] is None
    app.multiselect[0].set_value(["housing", "food"]).run()
    assert next(item.value for item in app.number_input if item.label == "Food (SGD)") == 0.0


def test_goal_inputs_start_empty_or_zero() -> None:
    app = _workspace_page("goals_page")

    assert not app.exception
    assert [(item.label, item.value) for item in app.text_input] == [("Goal name", "")]
    assert [(item.label, item.value) for item in app.number_input] == [
        ("Target (SGD)", 0.0),
        ("Saved (SGD)", 0.0),
        ("Time horizon (months)", 0),
    ]
    assert [(item.label, item.value) for item in app.selectbox] == [("Goal", None)]


def test_coach_starter_persists_conversation_and_new_chat_keeps_history() -> None:
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = CoachClient()
    app.session_state["active_user_id"] = "coach-user"
    app.run(timeout=30)

    assert not app.exception
    assert app.chat_input[0].placeholder == "Message your financial coach"
    assert app.sidebar.button(key="coach-new-chat").disabled is True

    app.button(key="coach-starter-0").click().run(timeout=30)

    assert app.session_state["backend_client"].questions == ["Review my monthly spending"]
    assert app.session_state["coach_active_session_id"] == "coach-session-1"
    assert app.session_state["backend_client"].sessions["coach-session-1"]["messages"] == [
        {"role": "user", "content": "Review my monthly spending"},
        {
            "role": "assistant",
            "content": "Start by comparing essential spending with monthly income.",
            "sources": [
                {
                    "source_id": "cpf-beginners-guide-to-investing",
                    "title": "A beginner's guide to investing in Singapore",
                    "issuing_organization": "CPF Board",
                    "canonical_url": "https://www.cpf.gov.sg/example",
                    "published_at": "2026-05-07",
                    "document_filename": "cpf-investing-guide.md",
                    "content_kind": "source_document",
                }
            ],
            "explanation": {
                "trace_id": "trace-coach-session-1",
                "selected_agents": ["budget"],
                "routing_rationale": ["The question asks for budget guidance."],
                "agent_results": [
                    {
                        "agent": "budget",
                        "rationale": ["The saved monthly income was used."],
                        "confidence": 0.76,
                        "blocked": False,
                    },
                    {
                        "agent": "risk_compliance",
                        "rationale": ["The answer remains educational."],
                        "confidence": 0.91,
                        "blocked": False,
                    },
                ],
                "blocked": False,
                "prompt_set_version": "v4",
            },
        },
    ]
    assert app.sidebar.button(key="coach-new-chat").disabled is False
    assert app.sidebar.button(key="coach-session-coach-session-1").label == (
        "Review my monthly spending"
    )
    assert app.sidebar.button(key="coach-rename-action-coach-session-1").label == "Rename"
    assert app.sidebar.button(key="coach-delete-action-coach-session-1").label == "Delete"

    app.sidebar.button(key="coach-rename-action-coach-session-1").click().run(timeout=30)
    assert app.session_state["coach_rename_open"] == "coach-session-1"
    assert app.sidebar.text_input[0].value == "Review my monthly spending"

    app.sidebar.button(key="coach-delete-action-coach-session-1").click().run(timeout=30)
    assert "coach_rename_open" not in app.session_state
    assert app.session_state["coach_delete_open"] == "coach-session-1"

    app.sidebar.button(key="coach-new-chat").click().run(timeout=30)
    assert app.session_state["coach_active_session_id"] is None
    assert len(app.session_state["backend_client"].sessions) == 1


def test_coach_answer_and_reopened_history_display_approved_source_links() -> None:
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = CoachClient()
    app.session_state["active_user_id"] = "coach-user"
    app.run(timeout=30)

    app.button(key="coach-starter-0").click().run(timeout=30)

    source_line = (
        "- [A beginner's guide to investing in Singapore](https://www.cpf.gov.sg/example) — "
        "Saved source document · CPF Board, 2026-05-07 · cpf-investing-guide.md · "
        "Source ID: cpf-beginners-guide-to-investing"
    )
    assert not app.exception
    assert source_line in [item.value for item in app.markdown]
    assert "RAG knowledge base references — no live web search" in [
        item.value for item in app.caption
    ]

    app.sidebar.button(key="coach-new-chat").click().run(timeout=30)
    app.sidebar.button(key="coach-session-coach-session-1").click().run(timeout=30)

    assert not app.exception
    assert source_line in [item.value for item in app.markdown]
    assert "RAG knowledge base references — no live web search" in [
        item.value for item in app.caption
    ]
    assert len(app.session_state["backend_client"].questions) == 1


def test_model_only_coach_message_does_not_display_reference_sources() -> None:
    app = AppTest.from_string(
        "from ui.pages import _render_coach_message\n"
        "_render_coach_message({'role': 'assistant', "
        "'content': 'General educational background: ETF fees reduce returns.', 'sources': []})"
    ).run(timeout=30)

    assert not app.exception
    assert [item.value for item in app.markdown] == [
        "General educational background: ETF fees reduce returns."
    ]
    assert not app.caption


def test_coach_source_labels_summary_and_legacy_citations_without_inventing_metadata() -> None:
    app = AppTest.from_string(
        "from ui.pages import _render_coach_message\n"
        "_render_coach_message({'role': 'assistant', 'content': 'Answer.', 'sources': ["
        "{'source_id': 'summary', 'title': 'Summary', 'issuing_organization': 'Team 9', "
        "'canonical_url': 'https://example.com/source', 'published_at': '2026-01-01', "
        "'document_filename': 'summary.md', 'content_kind': 'project_summary'}, "
        "{'source_id': 'legacy', 'title': 'Legacy', 'issuing_organization': 'Agency', "
        "'canonical_url': 'https://example.com/legacy', 'published_at': '2025-01-01'}]})"
    ).run(timeout=30)

    rendered = "\n".join(item.value for item in app.markdown)
    captions = [item.value for item in app.caption]
    assert not app.exception
    assert "Project-written summary based on the linked source" in rendered
    assert "summary.md" in rendered
    assert "Retrieved reference sources" in captions
    assert "RAG knowledge base references — no live web search" in captions
    assert "Saved source document" not in rendered


def test_source_filename_and_title_cannot_inject_markdown_or_html() -> None:
    app = AppTest.from_string(
        "from ui.pages import _render_coach_message\n"
        "_render_coach_message({'role': 'assistant', 'content': 'Answer.', 'sources': [{"
        "'source_id': 'hostile', 'title': 'evil](javascript:alert(1))<img src=x>', "
        "'issuing_organization': 'Agency', 'canonical_url': 'https://example.com/a(b)', "
        "'published_at': '2026-01-01', 'document_filename': 'bad`[x](y).md', "
        "'content_kind': 'source_document'}]})"
    ).run(timeout=30)

    rendered = "\n".join(item.value for item in app.markdown)
    assert not app.exception
    assert "](javascript:" not in rendered
    assert "<img src=x>" not in rendered
    assert "bad\\`\\[x\\]\\(y\\).md" in rendered
    assert "https://example.com/a%28b%29" in rendered


def test_coach_answer_explains_rationale_confidence_and_reference() -> None:
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = CoachClient()
    app.session_state["active_user_id"] = "coach-user"
    app.run(timeout=30)

    app.button(key="coach-starter-0").click().run(timeout=30)

    rendered_markdown = "\n".join(item.value for item in app.markdown)
    rendered_captions = "\n".join(item.value for item in app.caption)
    assert "Areas used:** Budget planning" in rendered_markdown
    assert "Moderate confidence (self-assessed score 0.76)" in rendered_markdown
    assert "Safety review — High confidence (self-assessed score 0.91)" in rendered_markdown
    assert "not a probability" in rendered_captions
    assert "Reference ID: trace-coach-session-1 · Prompt set: v4" in rendered_captions


@pytest.mark.parametrize("language, warning", [
    (None, "safety review blocked this response"),
    ("English", "safety review blocked this response"),
    ("Chinese", "此回复未通过安全审查"),
])
def test_blocked_coach_explanation_hides_poison_and_keeps_safety_reference(
    language, warning,
) -> None:
    app = AppTest.from_string(
        "from ui.pages import _render_coach_explanation\n"
        "_render_coach_explanation({"
        "'trace_id': 'trace-blocked', "
        "'prompt_set_version': 'v9', "
        "'blocked': True, "
        f"'response_language': {language!r}, "
        "'routing_rationale': ['POISONED_MODEL_RATIONALE'], "
        "'agent_results': [{'agent': 'budget', 'rationale': ['POISONED_MODEL_RATIONALE']}]"
        "})"
    )
    app.run(timeout=30)

    rendered_markdown = "\n".join(item.value for item in app.markdown)
    rendered_warnings = "\n".join(item.value for item in app.warning)
    rendered_captions = "\n".join(item.value for item in app.caption)
    assert "POISONED_MODEL_RATIONALE" not in rendered_markdown
    assert "POISONED_MODEL_RATIONALE" not in rendered_warnings
    assert warning in rendered_warnings
    assert "Reference ID: trace-blocked · Prompt set: v9" in rendered_captions

def test_budget_charts_custom_category_and_save_round_trip() -> None:
    class CustomBudgetClient(WorkspaceDefaultsClient):
        def __init__(self):
            self.saved = None

        def get_budget(self, user_id, period_start):
            if self.saved:
                return {**self.saved, "categories": [
                    {**item, "spent_amount": 0, "remaining_amount": item["limit_amount"]}
                    for item in self.saved["categories"]
                ]}
            return {"currency": "SGD", "categories": [
                {"category": "pet care", "limit_amount": 100,
                 "spent_amount": 125, "remaining_amount": -25},
            ]}

        def save_budget(self, user_id, payload):
            self.saved = payload
            return self.get_budget(user_id, None)

    client = CustomBudgetClient()
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "workspace-user"
    app.session_state["active_period"] = date(2026, 10, 1)
    app.run(timeout=30)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    assert "Over limit: Pet Care" in app.warning[0].value
    assert app.multiselect[0].value == ["pet care"]
    app.multiselect[0].set_value(["pet care", "Hobbies"]).run()
    assert not app.exception
    inputs = {item.label: item for item in app.number_input}
    inputs["Hobbies (SGD)"].set_value(75)
    app.button[0].click().run()
    assert not app.exception
    assert client.saved["categories"] == [
        {"category": "pet care", "limit_amount": 100},
        {"category": "hobbies", "limit_amount": 75},
    ]

def test_budget_plan_edit_checks_commitments_and_funding_gap():
    class PlannedClient(WorkspaceDefaultsClient):
        saved = None

        def get_budget(self, user_id, period):
            return {"currency": "SGD", "categories": [{
                "category": "housing", "limit_amount": 3000,
                "spent_amount": 500, "remaining_amount": 2500,
            }], "planning": {"take_home_income": 4000, "savings_target": 800,
                              "income_basis": "take_home", "expenses_confirmed": True,
                              "version": "budget-planning-v1"}}

        def save_budget(self, user_id, payload):
            self.saved = payload

    client = PlannedClient()
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "workspace-user"
    app.session_state["active_period"] = date(2026, 10, 1)
    app.run(timeout=30)
    assert not app.exception
    app.button[0].click().run()
    assert client.saved is None
    assert "Confirm that the expense limits" in app.warning[0].value
    app.checkbox[0].check()
    next(item for item in app.number_input if item.label == "Housing (SGD)").set_value(3500)
    app.button[0].click().run()
    assert client.saved is None
    assert "funding gap of SGD 300.00" in app.warning[0].value
    next(item for item in app.number_input if item.label == "Housing (SGD)").set_value(3200)
    app.button[0].click().run()
    assert client.saved["planning"]["savings_target"] == 800
    assert client.saved["categories"][0]["limit_amount"] == 3200
