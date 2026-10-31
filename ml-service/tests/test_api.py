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
        assert Path(path).is_dir()
        with open(Path(path) / "operating__plant.csv", "rb") as handle:
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
    real_temporary_directory = api.tempfile.TemporaryDirectory

    def tracking_temp_directory(*args, **kwargs):
        handle = real_temporary_directory(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(api.tempfile, "TemporaryDirectory", tracking_temp_directory)
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


def test_temp_upload_is_removed_when_pipeline_raises(monkeypatch, caplog):
    created = []
    real_temporary_directory = api.tempfile.TemporaryDirectory

    def tracking_temp_directory(*args, **kwargs):
        handle = real_temporary_directory(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    def broken_pipeline(*args, **kwargs):
        raise RuntimeError("sensitive parser details")

    monkeypatch.setattr(api.tempfile, "TemporaryDirectory", tracking_temp_directory)
    monkeypatch.setattr(api, "run_pipeline", broken_pipeline)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/analyze", files={"file": ("plant.csv", CSV)})
    assert response.status_code == 500
    assert "sensitive parser details" not in response.text
    assert "RuntimeError" in response.json()["detail"]
    assert any(record.exc_info for record in caplog.records), "pipeline traceback must be logged"
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

def test_upload_passes_optional_context_files_as_named_directory_inputs(monkeypatch):
    captured = {}

    def fake_pipeline(path, output_path=None, **kwargs):
        captured["path"] = Path(path)
        captured["files"] = sorted(item.name for item in Path(path).iterdir())
        return {"schema_version": "2.1.0", "analysis_status": "partial", "analysis_mode": "full"}

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={
                "file": ("plant.csv", CSV, "text/csv"),
                "forecast_file": ("forecast.csv", b"timestamp,forecast_energy_kwh\\n2026-10-30T10:00:00Z,15\\n", "text/csv"),
                "weather_file": ("weather.csv", b"timestamp,poa_irradiance_w_m2\\n2026-10-30T10:00:00Z,800\\n", "text/csv"),
            },
        )
    assert response.status_code == 200, response.text
    assert "operating__plant.csv" in captured["files"]
    assert "forecast__forecast.csv" in captured["files"]
    assert "weather__weather.csv" in captured["files"]


def test_upload_enforces_row_column_and_decompression_limits(monkeypatch):
    import io
    import zipfile

    monkeypatch.setattr(api, "MAX_ROWS", 2)
    monkeypatch.setattr(api, "MAX_COLUMNS", 3)
    monkeypatch.setattr(api, "MAX_XLSX_UNCOMPRESSED_BYTES", 1000)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 5000)
    with TestClient(api.app) as client:
        wide = client.post("/api/v1/analyze", files={"file": ("wide.csv", b"a,b,c,d\n1,2,3,4\n")})
        tall = client.post("/api/v1/analyze", files={"file": ("tall.csv", b"a,b\n1,2\n3,4\n5,6\n7,8\n")})
        expanded = client.post("/api/v1/analyze", files={"file": ("bomb.xlsx", bomb.getvalue())})
    assert wide.status_code == 413
    assert tall.status_code == 413
    assert expanded.status_code == 413


def test_role_prefix_wins_over_words_in_the_uploaded_file_name(tmp_path):
    from src.service import _classify_directory

    for name in ("operating__weather_station_logger.csv", "weather__forecast_city.csv", "forecast__design.csv"):
        (tmp_path / name).write_text("timestamp,value\n2026-01-01T00:00:00Z,1\n")
    operating, optional, _ = _classify_directory(tmp_path)
    assert operating.name == "operating__weather_station_logger.csv"
    assert optional["weather"].name == "weather__forecast_city.csv"
    assert optional["forecast"].name == "forecast__design.csv"


def test_analysis_output_never_exposes_server_temp_paths():
    import json

    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            files={"file": ("plant.csv", b"timestamp,ac_power_kw\n2026-01-01T10:00:00Z,1\n2026-01-01T10:15:00Z,2\n")},
        )
    text = json.dumps(response.json())
    assert "solarsleuth-ml-" not in text and "/tmp/" not in text
    assert "plant.csv" in response.json()["request"]["source_files"]
    assert "operating__plant.csv" not in text
