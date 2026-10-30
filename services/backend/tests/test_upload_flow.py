"""Tests for ML-first orchestration and safe failure handling."""
from fastapi.testclient import TestClient
import pytest
import main


@pytest.fixture(autouse=True)
def authenticated_test_request(monkeypatch):
    # These tests exercise the upload/orchestration contract independently of JWT.
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "test-user", "business_id": "test-business"
    })


VALID_ML = {
    "schema_version": "2.0.0",
    "analysis_status": "partial",
    "analysis_mode": "full",
    "summary": "ML calculated actual and expected energy.",
    "energy": {"actual": {"value_kwh": 12.5}},
    "limitations": ["Forecast input unavailable."],
}


def llm_response(payload):
    return {
        "request_id": payload["request_id"],
        "plant_id": payload["plant_id"],
        "model": "local-test-model",
        "analysis": {
            "summary": "The ML result reports 12.5 kWh actual energy.",
            "observations": ["ML reported 12.5 kWh actual energy."],
            "possible_causes": [],
            "supporting_evidence": ["ml_results.energy.actual"],
            "recommended_checks": ["Review the forecast source."],
            "limitations": ["Forecast input unavailable."],
            "confidence": "low",
        },
    }


def test_upload_runs_ml_before_llm_and_returns_unchanged_ml(monkeypatch):
    events = []

    async def fake_ml(content, filename, **kwargs):
        events.append(("ml", filename, content))
        return VALID_ML

    async def fake_llm(payload):
        events.append(("llm", payload["ml_results"]))
        return llm_response(payload)

    monkeypatch.setattr(main, "_run_ml", fake_ml)
    monkeypatch.setattr(main, "_post_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("../operating.csv", b"timestamp,ac_power_kw\\n2026-10-30T10:00:00Z,12.5\\n", "text/csv")},
            data={"plant_id": "plant-01", "mode": "full"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [event[0] for event in events] == ["ml", "llm"]
    assert events[0][1] == "operating.csv"
    assert events[1][1]["energy"] == VALID_ML["energy"]
    assert body["ml_analysis"] == VALID_ML
    assert body["analysis"]["summary"].startswith("The ML result")
    assert body["analysis_mode"] == "full"


def test_invalid_ml_result_never_calls_llm(monkeypatch):
    called = False

    async def fake_ml(*args, **kwargs):
        return {"analysis_status": "invalid_input", "summary": "Bad dataset"}

    async def fake_llm(payload):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(main, "_run_ml", fake_ml)
    monkeypatch.setattr(main, "_post_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.csv", b"time,power\\n1,2", "text/csv")},
        )
    assert response.status_code == 422
    assert called is False


def test_llm_outage_preserves_successful_ml_result(monkeypatch):
    async def fake_ml(*args, **kwargs):
        return VALID_ML

    async def fake_llm(payload):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr(main, "_run_ml", fake_ml)
    monkeypatch.setattr(main, "_post_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.csv", b"time,power\\n1,2", "text/csv")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ml_analysis"] == VALID_ML
    assert body["model"] == "unavailable"
    assert body["analysis"]["confidence"] == "insufficient_evidence"


def test_upload_rejects_extension_and_signature_mismatch():
    with TestClient(main.app) as client:
        bad_extension = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.json", b"{}", "application/json")},
        )
        bad_signature = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.xlsx", b"not-an-xlsx", "application/octet-stream")},
        )
    assert bad_extension.status_code == 415
    assert bad_signature.status_code == 415


def test_upload_rejects_empty_and_oversized(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 8)
    with TestClient(main.app) as client:
        empty = client.post("/api/v1/analyze/upload", files={"file": ("plant.csv", b"", "text/csv")})
        large = client.post("/api/v1/analyze/upload", files={"file": ("plant.csv", b"timestamp,power", "text/csv")})
    assert empty.status_code == 422
    assert large.status_code == 413
