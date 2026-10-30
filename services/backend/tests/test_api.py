from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import main


def test_health_does_not_require_dependencies():
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_manual_measurement_endpoint_is_not_exposed():
    with TestClient(main.app) as client:
        response = client.post("/api/v1/analyze", json={"plant_id": "x", "observations": {"power_kw": 5}})
    assert response.status_code == 404


def test_ready_reports_degraded_when_services_are_offline(monkeypatch):
    monkeypatch.setattr(main, "ML_API_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(main, "LLM_API_URL", "http://127.0.0.1:1")
    with TestClient(main.app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ml_service_reachable"] is False


def test_production_browser_access_requires_bearer(monkeypatch):
    monkeypatch.setattr(main, "ENVIRONMENT", "production")
    monkeypatch.setattr(main, "API_ACCESS_TOKEN", "test-access-token")
    monkeypatch.setattr(main, "SERVICE_TOKEN", "test-internal-token")
    with pytest.raises(HTTPException) as denied:
        main._authorize_browser(None)
    assert denied.value.status_code == 401
    claims = main._authorize_browser("Bearer test-access-token")
    assert claims["business_id"] == "legacy-deployment-workspace"

    # The legacy deployment gate still passes its request through the normal ML-first flow.
    monkeypatch.setattr(main, "ENVIRONMENT", "development")
    with TestClient(main.app) as client:
        allowed = client.post(
            "/api/v1/analyze/upload",
            headers={"Authorization": "Bearer test-access-token"},
            files={"file": ("plant.csv", b"t,p\\n1,2", "text/csv")},
        )
    assert allowed.status_code == 503


def test_auth_endpoints_fail_closed_without_mongodb(monkeypatch):
    monkeypatch.setattr(main, "database", None)
    with TestClient(main.app) as client:
        response = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert response.status_code == 503
    assert "MONGODB_URI" in response.json()["detail"]


def test_jwt_requires_valid_signed_token(monkeypatch):
    monkeypatch.setattr(main, "API_ACCESS_TOKEN", "")
    monkeypatch.setattr(main, "JWT_SECRET", "x" * 48)
    token = main.jwt.encode(
        {"sub": "user-1", "business_id": "business-1", "exp": 4102444800},
        main.JWT_SECRET, algorithm=main.JWT_ALGORITHM,
    )
    claims = main._authorize_browser("Bearer " + token)
    assert claims["user_id"] == "user-1"
    assert claims["business_id"] == "business-1"
    with pytest.raises(HTTPException) as denied:
        main._authorize_browser("Bearer invalid")
    assert denied.value.status_code == 401
