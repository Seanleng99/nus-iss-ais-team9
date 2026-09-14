from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize("supplied", ["x" * 129, "bad correlation id"])
def test_invalid_correlation_ids_are_replaced(supplied):
    response = TestClient(app).get("/health", headers={"X-Correlation-ID": supplied})
    assert response.status_code == 200
    assert UUID(response.headers["X-Correlation-ID"])
