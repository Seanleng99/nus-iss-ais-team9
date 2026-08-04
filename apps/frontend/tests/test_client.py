from unittest.mock import Mock, patch

from client import ask_coach, build_request, build_snapshot


def test_build_snapshot_omits_zero_values() -> None:
    snapshot = build_snapshot(monthly_income=4000, housing=1200, food=0, transport=150)
    assert snapshot["monthly_income"]["amount"] == 4000
    assert [expense["category"] for expense in snapshot["recurring_expenses"]] == [
        "housing",
        "transport",
    ]


def test_build_request_normalizes_empty_user() -> None:
    payload = build_request("  ", "  Create a budget  ", {})
    assert payload["user_id"] == "demo-user"
    assert payload["message"] == "Create a budget"
    assert payload["session_id"]


@patch("client.httpx.post")
def test_ask_coach_calls_application_backend(post: Mock) -> None:
    post.return_value.json.return_value = {"answer": "guidance"}

    response = ask_coach({"message": "Create a budget"})

    assert response == {"answer": "guidance"}
    assert post.call_args.args[0] == "http://localhost:8080/api/coach"
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "change-me-locally"}
