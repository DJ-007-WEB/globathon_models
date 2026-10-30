"""API contract tests; model loading and inference are mocked for CPU CI."""
from fastapi.testclient import TestClient

from api import app
from schemas import AnalysisResponse


def valid_payload():
    return {
        "request_id": "test-1",
        "plant_id": "plant-1",
        "timestamp": None,
        "plant_context": {"analysis_mode": "snapshot"},
        "observations": {"analysis_status": "partial", "summary": "ML evidence summary"},
        "ml_results": {
            "schema_version": "2.0.0",
            "analysis_status": "partial",
            "actual_energy": 123.45,
            "expected_energy": 150.0,
            "units": {"energy": "kWh"},
        },
        "retrieved_context": [],
    }


def test_health_and_lazy_readiness():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["model_loaded"] is False
        assert ready.json()["status"] == "not_loaded"


def test_analyze_returns_backend_contract(monkeypatch):
    expected = AnalysisResponse(
        summary="The supplied ML result reports partial underperformance; verify the evidence.",
        observations=["The ML analysis status is partial."],
        possible_causes=["A contributing cause requires verification."],
        supporting_evidence=["ml_results.actual_energy"],
        recommended_checks=["Review the inverter event logs."],
        limitations=["The input does not establish a confirmed root cause."],
        confidence="low",
    )
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.llm_service, "analyze", lambda _request: expected)
        response = client.post("/api/v1/analyze", json=valid_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"] == "test-1"
    assert body["plant_id"] == "plant-1"
    assert body["analysis"]["summary"] == expected.summary
    assert body["model"]


def test_analyze_accepts_backend_internal_token(monkeypatch):
    monkeypatch.setattr("api.SERVICE_TOKEN", "test-secret")
    expected = AnalysisResponse(summary="Evidence-based explanation.")
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.llm_service, "analyze", lambda _request: expected)
        response = client.post(
            "/api/v1/analyze",
            json=valid_payload(),
            headers={"X-Service-Token": "test-secret"},
        )
    assert response.status_code == 200, response.text


def test_analyze_rejects_missing_internal_token(monkeypatch):
    monkeypatch.setattr("api.SERVICE_TOKEN", "test-secret")
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json=valid_payload())
    assert response.status_code == 401


def test_analyze_rejects_invalid_internal_token(monkeypatch):
    monkeypatch.setattr("api.SERVICE_TOKEN", "test-secret")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analyze",
            json=valid_payload(),
            headers={"X-Service-Token": "wrong-secret"},
        )
    assert response.status_code == 401


def test_analyze_rejects_missing_observations():
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json={"plant_id": "plant-1"})
    assert response.status_code == 422


def test_analyze_rejects_unexpected_fields():
    payload = valid_payload()
    payload["raw_uploaded_file"] = "must-not-be-forwarded"
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 422


def test_analyze_rejects_oversized_evidence_payload():
    payload = valid_payload()
    payload["ml_results"]["oversized"] = "x" * 61000
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 422


def test_model_output_schema_rejects_extra_fields():
    try:
        AnalysisResponse.model_validate({"summary": "ok", "invented_metric": 99})
    except Exception:
        pass
    else:
        raise AssertionError("Extra generated output fields must be rejected.")
