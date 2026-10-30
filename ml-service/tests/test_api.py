"""HTTP adapter tests; deterministic calculations are exercised separately."""
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import api


CSV = b"timestamp,ac_power_kw\n2026-10-30T10:00:00Z,12\n"


def test_health_and_ready():
    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["pipeline_available"] is True


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
            files={"file": ("plant.csv", CSV, "text/csv")},
            data={"plant_id": "plant-test", "mode": "snapshot", "timezone": "Asia/Kolkata"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "partial"
    assert captured["plant_id"] == "plant-test"
    assert captured["mode"] == "snapshot"
    assert captured["timezone"] == "Asia/Kolkata"
    assert captured["content"] == CSV


def test_upload_rejects_unsupported_file():
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.json", b"{}", "application/json")},
        )
    assert response.status_code == 415


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("plant.xlsx", b"not-a-workbook", 415),
        ("plant.csv", b"not a delimited header", 422),
        ("plant.csv", bytes((0xFF, 0xFE)), 415),
        ("plant.csv", bytes((0x50, 0x4B, 0x03, 0x04)) + b"not-csv", 415),
    ],
)
def test_upload_rejects_invalid_content(filename, content, expected_status):
    with TestClient(api.app) as client:
        response = client.post("/api/v1/analyze", files={"file": (filename, content)})
    assert response.status_code == expected_status


def test_upload_rejects_oversized_content(monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 8)
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", b"timestamp,power\n1,2\n")},
        )
    assert response.status_code == 413


def test_upload_rejects_non_finite_interval():
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", CSV)},
            data={"interval_minutes": "nan"},
        )
    assert response.status_code == 422


def test_temp_upload_is_removed_after_pipeline(monkeypatch):
    created = []
    real_named_temporary_file = api.tempfile.NamedTemporaryFile

    def tracking_temp_file(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(api.tempfile, "NamedTemporaryFile", tracking_temp_file)
    monkeypatch.setattr(
        api,
        "run_pipeline",
        lambda *args, **kwargs: {
            "schema_version": "2.0.0",
            "analysis_status": "partial",
            "analysis_mode": "snapshot",
        },
    )
    with TestClient(api.app) as client:
        response = client.post("/api/v1/analyze", files={"file": ("plant.csv", CSV)})
    assert response.status_code == 200
    assert len(created) == 1
    assert not created[0].exists()


def test_temp_upload_is_removed_when_pipeline_raises(monkeypatch):
    created = []
    real_named_temporary_file = api.tempfile.NamedTemporaryFile

    def tracking_temp_file(*args, **kwargs):
        handle = real_named_temporary_file(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    def broken_pipeline(*args, **kwargs):
        raise RuntimeError("sensitive parser details")

    monkeypatch.setattr(api.tempfile, "NamedTemporaryFile", tracking_temp_file)
    monkeypatch.setattr(api, "run_pipeline", broken_pipeline)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/analyze", files={"file": ("plant.csv", CSV)})
    assert response.status_code == 500
    assert "sensitive parser details" not in response.text
    assert len(created) == 1
    assert not created[0].exists()


def test_service_token_is_enforced(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", "test-secret")
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", CSV)},
        )
    assert response.status_code == 401


def test_service_token_accepts_valid_header(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", "test-secret")
    monkeypatch.setattr(
        api,
        "run_pipeline",
        lambda *args, **kwargs: {
            "schema_version": "2.0.0",
            "analysis_status": "partial",
            "analysis_mode": "snapshot",
        },
    )
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", CSV)},
            headers={"X-Service-Token": "test-secret"},
        )
    assert response.status_code == 200, response.text
