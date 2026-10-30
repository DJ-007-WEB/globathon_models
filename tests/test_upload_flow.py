"""Tests for ML-first upload orchestration; no external services or model weights."""
from fastapi.testclient import TestClient
import main


def test_upload_runs_ml_before_llm_and_returns_both(monkeypatch):
    events = []
    ml_result = {
        "schema_version": "2.0.0",
        "analysis_status": "partial",
        "analysis_mode": "full",
        "summary": "ML calculated actual and expected energy.",
        "energy": {"actual": {"value_kwh": 12.5}},
        "limitations": ["Forecast input unavailable."],
    }

    async def fake_ml(content, filename, **kwargs):
        events.append(("ml", filename, content))
        return ml_result

    async def fake_llm(payload):
        events.append(("llm", payload["ml_results"]))
        return {
            "request_id": payload["request_id"],
            "plant_id": payload["plant_id"],
            "model": "local-test-model",
            "analysis": {
                "summary": "The measured result is below the available reference.",
                "observations": ["ML reported 12.5 kWh actual energy."],
                "possible_causes": [],
                "supporting_evidence": ["ml_results.energy.actual"],
                "recommended_checks": ["Review the forecast source."],
                "limitations": ["Forecast input unavailable."],
                "confidence": "low",
            },
        }

    monkeypatch.setattr(main, "_run_ml", fake_ml)
    monkeypatch.setattr(main, "_post_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("operating.csv", b"timestamp,ac_power_kw\n2026-10-30T10:00:00Z,12.5\n", "text/csv")},
            data={"plant_id": "plant-01", "mode": "full"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [event[0] for event in events] == ["ml", "llm"]
    assert events[1][1] == ml_result
    assert body["ml_analysis"] == ml_result
    assert body["analysis"]["summary"].startswith("The measured")
    assert body["analysis_mode"] == "full"


def test_upload_rejects_unsupported_extension():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.json", b"{}", "application/json")},
        )
    assert response.status_code == 415
