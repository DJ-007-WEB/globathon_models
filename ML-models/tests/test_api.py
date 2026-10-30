"""HTTP adapter tests; deterministic pipeline work is mocked."""
from fastapi.testclient import TestClient
import api


def test_health_and_ready():
    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["pipeline_available"] is True


def test_upload_calls_existing_pipeline(monkeypatch):
    captured = {}

    def fake_pipeline(path, output_path=None, **kwargs):
        captured.update(kwargs)
        with open(path, "rb") as handle:
            captured["content"] = handle.read()
        return {"schema_version": "2.0.0", "analysis_status": "partial", "analysis_mode": "snapshot"}

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", b"timestamp,ac_power_kw\n2026-10-30T10:00:00Z,12\n", "text/csv")},
            data={"plant_id": "plant-test", "mode": "snapshot", "timezone": "Asia/Kolkata"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "partial"
    assert captured["plant_id"] == "plant-test"
    assert captured["mode"] == "snapshot"
    assert captured["timezone"] == "Asia/Kolkata"
    assert captured["content"].startswith(b"timestamp")


def test_upload_rejects_unsupported_file():
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.json", b"{}", "application/json")},
        )
    assert response.status_code == 415


def test_service_token_is_enforced(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", "test-secret")
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", b"a,b\n1,2\n", "text/csv")},
        )
    assert response.status_code == 401
