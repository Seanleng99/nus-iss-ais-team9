import pytest

from infra.scripts.budget_multiturn_acceptance import run


def test_failure_erases_only_the_unique_synthetic_profile():
    calls = []

    def request(url, key, method, payload=None):
        calls.append((url, method, payload))
        if url.endswith("/coach"):
            raise ValueError("Simulated model failure")
        if url.endswith("/preview"):
            return {"preview_id": "p"}
        if url.endswith("/data-lifecycle"):
            return {"policy_version": "v"}
        return {}

    result = run("https://example.test/api/coach", "test-key", request=request)
    assert not result["passed"]
    assert result["checks"][-1] == {"check": "synthetic_profile_erased", "passed": True}
    created = calls[0][0].removesuffix("/profile")
    assert "/users/live-evaluation-budget-" in created
    deletes = [c for c in calls if c[1] == "DELETE"]
    assert len(deletes) == 1 and deletes[0][0] == created + "/data"
    assert deletes[0][2]["confirm_user_id"] == created.rsplit("/", 1)[1]
    assert "test-key" not in str(result)


def test_invalid_url_never_makes_requests():
    def request(*args):
        pytest.fail("Invalid URL must never be requested")

    with pytest.raises(ValueError):
        run("file:///tmp/coach", "key", request=request)
