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


def test_warmup_loads_model_and_updates_readiness(monkeypatch):
    with TestClient(app) as client:
        service = app.state.llm_service

        def fake_load():
            service.tokenizer = object()
            service.model = object()
            service.resolved_model_name = "test-model"
            service.last_load_error = None

        monkeypatch.setattr(service, "_load", fake_load)
        response = client.post("/warmup")
        assert response.status_code == 200, response.text
        assert response.json()["model_loaded"] is True

        ready = client.get("/ready").json()
        assert ready["status"] == "ready"
        assert ready["model_loaded"] is True
        assert ready["last_inference_error"] is None


def test_response_normalization_removes_bare_keys_and_maps_confidence():
    from llm_service import LLMService

    normalized = LLMService._normalize_response({
        "summary": "analysis_status is partial; actual_energy is 12.5 kWh.",
        "observations": ["actual_energy", "Measured energy is 12.5 kWh."],
        "possible_causes": [],
        "supporting_evidence": ["ml_results shows a persistent finding."],
        "recommended_checks": ["Review device_id INV-01."],
        "limitations": [],
        "confidence": "medium",
    })
    assert "analysis status" in normalized["summary"]
    assert "measured energy is 12.5 kWh" in normalized["summary"]
    assert normalized["observations"] == ["Measured energy is 12.5 kWh."]
    assert "deterministic ML findings" in normalized["supporting_evidence"][0]
    assert "device identifier INV-01" in normalized["recommended_checks"][0]
    assert normalized["confidence"] == "moderate"


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

def test_schema_repair_fills_missing_fields_without_inventing_evidence():
    from llm_service import LLMService
    from schemas import AnalysisRequest

    request = AnalysisRequest(
        plant_id="plant-1",
        observations={"analysis_status": "partial", "summary": "Expected energy is unavailable."},
        ml_results={"actual_energy": 123.45},
    )
    repaired = LLMService._coerce_response(
        {"observations": "Measured energy is 123.45 kWh.", "confidence": "medium"},
        request,
    )
    validated = AnalysisResponse.model_validate(repaired)
    assert "partial" in validated.summary
    assert validated.observations == ["Measured energy is 123.45 kWh."]
    assert validated.possible_causes == []
    assert validated.confidence == "moderate"


def test_schema_repair_discards_unknown_model_fields():
    from llm_service import LLMService
    from schemas import AnalysisRequest

    request = AnalysisRequest(
        plant_id="plant-1",
        observations={"summary": "The analysis is partial."},
    )
    repaired = LLMService._coerce_response(
        {"summary": "Grounded summary.", "extra_metric": 999},
        request,
    )
    assert "extra_metric" not in repaired
    assert repaired["observations"] == []
    assert repaired["limitations"] == []

def test_opt_in_startup_warmup_loads_model(monkeypatch):
    import api

    monkeypatch.setattr(api, "ENVIRONMENT", "development")
    monkeypatch.setattr(api, "WARMUP_ON_STARTUP", True)

    def fake_load(service):
        service.tokenizer = object()
        service.model = object()
        service.resolved_model_name = "startup-test-model"
        service.last_load_error = None

    monkeypatch.setattr(api.LLMService, "_load", fake_load)
    with TestClient(api.app) as client:
        ready = client.get("/ready").json()
    assert ready["model_loaded"] is True
    assert ready["model_name"] == "startup-test-model"

def test_prompt_builder_preserves_ml_evidence_and_avoids_silent_truncation():
    from llm_service import LLMService
    from schemas import AnalysisRequest

    class Tokenizer:
        chat_template = None
        @staticmethod
        def encode(text, add_special_tokens=False):
            return list(range(max(1, len(text) // 4)))

    service = LLMService.__new__(LLMService)
    service.tokenizer = Tokenizer()
    service.max_input_tokens = 1800
    request = AnalysisRequest(
        plant_id="plant-1",
        observations={"analysis_status": "partial", "summary": "ML completed."},
        ml_results={
            "analysis_status": "partial",
            "energy": {
                "actual": {"value_kwh": 123.45, "unit": "kWh"},
                "expected": {"value_kwh": 150.0, "unit": "kWh"},
                "forecast": {"value_kwh": None, "reason": "No forecast file was supplied."},
            },
            "expected_deviation_kwh": -26.55,
            "evidence": ["long evidence item " + str(i) + " x" * 90 for i in range(100)],
        },
        retrieved_context=["old chat " + "x" * 1000 for _ in range(10)],
    )
    prompt, token_count = service._prepare_prompt(request)
    assert token_count <= service.max_input_tokens
    user_payload_start = prompt.index("\nUser:\n")
    user_payload = prompt[user_payload_start:]
    assert user_payload.index('"ml_results"') < user_payload.index('"observations"')
    assert '"value_kwh":123.45' in prompt
    assert '"expected_deviation_kwh":-26.55' in prompt
    assert "No forecast file was supplied." in prompt
    assert '"retrieved_context":[]' in prompt


def test_prompt_builder_refuses_when_core_ml_payload_alone_exceeds_budget():
    from llm_service import LLMService
    from schemas import AnalysisRequest

    class Tokenizer:
        chat_template = None
        @staticmethod
        def encode(text, add_special_tokens=False):
            return list(range(max(1, len(text) // 4)))

    service = LLMService.__new__(LLMService)
    service.tokenizer = Tokenizer()
    service.max_input_tokens = 100
    request = AnalysisRequest(
        plant_id="plant-1",
        observations={"summary": "x" * 5000},
        ml_results={"energy": {"actual": {"value_kwh": 1.0}}},
    )
    try:
        service._prepare_prompt(request)
    except ValueError as exc:
        assert "refusing to silently truncate" in str(exc).lower()
    else:
        raise AssertionError("Oversized prompts must fail explicitly, not be truncated.")
