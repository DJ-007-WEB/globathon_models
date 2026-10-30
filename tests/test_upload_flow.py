from fastapi.testclient import TestClient

import main


def test_upload_runs_ml_before_llm_and_returns_both_results(monkeypatch):
    calls = []
    ml_result = {
        "schema_version": "2.0.0",
        "analysis_status": "partial",
        "analysis_mode": "full",
        "summary": "Full analysis covered 100 rows.",
        "energy": {"actual": {"value_kwh": 12.5}},
        "anomalies": [],
        "hypotheses": [],
        "evidence": [],
        "limitations": [],
    }

    async def fake_ml(*args, **kwargs):
        calls.append("ml")
        return ml_result

    async def fake_llm(payload):
        calls.append("llm")
        assert payload["ml_results"]["schema_version"] == "2.0.0"
        assert payload["observations"]["energy"]["actual"]["value_kwh"] == 12.5
        return {
            "request_id": payload["request_id"],
            "plant_id": payload["plant_id"],
            "model": "local-test",
            "analysis": {
                "summary": "The measured energy is available for review.",
                "observations": ["The ML pipeline calculated 12.5 kWh actual energy."],
                "possible_causes": [],
                "supporting_evidence": ["ml_results.energy.actual"],
                "recommended_checks": ["Review the data-quality report."],
                "limitations": ["Forecast data was not supplied."],
                "confidence": "low",
            },
        }

    monkeypatch.setattr(main, "forward_to_ml", fake_ml)
    monkeypatch.setattr(main, "forward_to_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("plant.csv", b"timestamp,ac_power_kw\n2026-01-01T00:00:00Z,1\n", "text/csv")},
            data={"plant_id": "plant-test", "mode": "full"},
        )

    assert response.status_code == 200
    assert calls == ["ml", "llm"]
    body = response.json()
    assert body["ml_analysis"]["schema_version"] == "2.0.0"
    assert body["analysis"]["summary"] == "The measured energy is available for review."


def test_upload_rejects_non_csv_xlsx(monkeypatch):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyze/upload",
            files={"file": ("private.pdf", b"not a spreadsheet", "application/pdf")},
            data={"plant_id": "plant-test"},
        )
    assert response.status_code == 415
