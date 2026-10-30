"""API contract tests; inference is mocked so tests need no GPU."""
from fastapi.testclient import TestClient
from api import app
from schemas import AnalysisResponse


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_returns_frontend_contract(monkeypatch):
    expected = AnalysisResponse(
        summary="The supplied classifier flags a possible issue; verify against site evidence.",
        observations=["The inverter status was supplied as normal."],
        possible_causes=["possible_inverter_underperformance"],
        supporting_evidence=["ml_results.fault_classifier.predicted_label"],
        recommended_checks=["Review inverter event logs and verify sensor quality."],
        limitations=["The input does not establish a confirmed root cause."],
        confidence="low",
    )

    def fake_analyze(_request):
        return expected

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.llm_service, "analyze", fake_analyze)
        response = client.post("/api/v1/analyze", json={
            "request_id": "test-1",
            "plant_id": "plant-1",
            "observations": {"inverter_status": "normal"},
            "ml_results": {"fault_classifier": {
                "predicted_label": "possible_inverter_underperformance"
            }},
        })

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "test-1"
    assert body["plant_id"] == "plant-1"
    assert body["analysis"]["summary"] == expected.summary
    assert body["analysis"]["confidence"] == "low"


def test_analyze_rejects_missing_observations():
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json={"plant_id": "plant-1"})
    assert response.status_code == 422

def test_internal_service_token_is_required_when_configured(monkeypatch):
    monkeypatch.setattr("api.SERVICE_TOKEN", "test-secret")
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json={
            "request_id": "auth-test",
            "plant_id": "plant-1",
            "observations": {"source": "test"},
            "ml_results": {},
        })
    assert response.status_code == 401
