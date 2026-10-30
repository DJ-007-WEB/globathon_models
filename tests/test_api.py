from fastapi.testclient import TestClient
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
    with TestClient(main.app) as client:
        denied = client.post("/api/v1/analyze/upload", files={"file": ("plant.csv", b"t,p\\n1,2", "text/csv")})
        allowed = client.post(
            "/api/v1/analyze/upload",
            headers={"Authorization": "Bearer test-access-token"},
            files={"file": ("plant.csv", b"t,p\\n1,2", "text/csv")},
        )
    assert denied.status_code == 401
    # The authorized request proceeds to ML and fails because no ML server is running.
    assert allowed.status_code == 503
