from fastapi.testclient import TestClient

import api


def test_health():
    with TestClient(api.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "solar-sleuth-ml"


def test_upload_runs_existing_pipeline_and_returns_contract(monkeypatch):
    captured = {}

    def fake_pipeline(path, output_path=None, **kwargs):
        from pathlib import Path
        captured["exists_during_analysis"] = Path(path).is_file()
        captured["suffix"] = Path(path).suffix
        captured.update(kwargs)
        return {"schema_version": "2.0.0", "analysis_status": "partial", "analysis_mode": "full"}

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", b"timestamp,ac_power_kw\n2026-01-01T00:00:00Z,1\n", "text/csv")},
            data={"plant_id": "plant-test", "mode": "full", "timezone": "UTC"},
        )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "2.0.0"
    assert captured["exists_during_analysis"] is True
    assert captured["suffix"] == ".csv"
    assert captured["plant_id"] == "plant-test"
    assert captured["mode"] == "full"
    assert captured["timezone"] == "UTC"


def test_upload_rejects_unsupported_file(monkeypatch):
    monkeypatch.setattr(api, "run_pipeline", lambda *args, **kwargs: {})
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.pdf", b"%PDF", "application/pdf")},
            data={"plant_id": "plant-test"},
        )
    assert response.status_code == 415


def test_upload_requires_service_token_when_configured(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", "secret-for-test")
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            headers={"X-Service-Token": "wrong"},
            files={"file": ("plant.csv", b"a,b\n1,2\n", "text/csv")},
            data={"plant_id": "plant-test"},
        )
    assert response.status_code == 401
