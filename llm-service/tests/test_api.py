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

def _grounding_request(**ml_overrides):
    from schemas import AnalysisRequest

    ml = {"analysis_status": "success", "actual_energy": 5374.120967,
          "expected_energy": 5379.164165, "data_quality": {"status": "pass"},
          "anomalies": [], "hypotheses": []}
    ml.update(ml_overrides)
    return AnalysisRequest(plant_id="plant-1", observations={"analysis_status": ml["analysis_status"]},
                           ml_results=ml)


def test_grounding_removes_invented_measurements_and_keeps_rounded_supplied_values():
    import json
    from llm_service import LLMService

    raw = json.dumps({
        "summary": "Measured energy was 5,374.12 kWh. Peak output reached 812.5 kW.",
        "observations": ["Measured energy was 5374.12 kWh.", "Irradiance peaked at 1043 W/m2."],
        "possible_causes": [], "supporting_evidence": [], "recommended_checks": [],
        "limitations": [], "confidence": "high",
    })
    result = LLMService._finalize(LLMService.__new__(LLMService), raw, _grounding_request())
    assert result.summary == "Measured energy was 5,374.12 kWh."
    assert result.observations == ["Measured energy was 5374.12 kWh."]
    assert any("2 generated statement(s)" in item for item in result.limitations)
    assert result.confidence == "high"


def test_grounding_clears_causes_without_ml_findings_and_caps_partial_confidence():
    import json
    from llm_service import LLMService

    raw = json.dumps({"summary": "Output looks low.", "possible_causes": ["Soiling is the confirmed cause."],
                      "confidence": "high"})
    result = LLMService._finalize(LLMService.__new__(LLMService), raw,
                                  _grounding_request(analysis_status="partial"))
    assert result.possible_causes == []
    assert result.confidence == "moderate"
    assert any("no anomaly or cause hypothesis" in item for item in result.limitations)


def test_grounding_keeps_causes_backed_by_ml_hypotheses_and_lowers_failed_quality():
    import json
    from llm_service import LLMService

    raw = json.dumps({"summary": "A shortfall was flagged.", "possible_causes": ["Possible soiling on INV-02."],
                      "confidence": "high"})
    request = _grounding_request(hypotheses=[{"summary": "soiling"}], data_quality={"status": "fail"})
    result = LLMService._finalize(LLMService.__new__(LLMService), raw, request)
    assert result.possible_causes == ["Possible soiling on INV-02."]

    raw = json.dumps({"summary": "A shortfall was flagged.", "possible_causes": ["Soiling is the confirmed cause."]})
    hedged = LLMService._finalize(LLMService.__new__(LLMService), raw, request)
    assert hedged.possible_causes == ["Unconfirmed hypothesis: Soiling is the confirmed cause."]
    assert result.confidence == "low"


def test_truncated_model_json_keeps_complete_fields_and_validates():
    from llm_service import LLMService

    raw = ('<think></think>{"summary": "Measured energy was 5374.12 kWh.", '
           '"observations": ["Measured energy was 5374.12 kWh.", "Expected energy was 5379.16 kWh."], '
           '"possible_causes": [], "recommended_checks": ["Compare inverter logs for the analysed interval and the')
    result = LLMService._finalize(LLMService.__new__(LLMService), raw, _grounding_request())
    assert result.summary == "Measured energy was 5374.12 kWh."
    assert result.observations == ["Measured energy was 5374.12 kWh.", "Expected energy was 5379.16 kWh."]
    assert result.recommended_checks == ["Compare inverter logs for the analysed interval and the…"]


def test_truncated_json_never_treats_array_values_as_keys():
    from llm_service import LLMService

    assert LLMService._extract_json('{"summary": "S", "observations": ["x", "y"') == {
        "summary": "S", "observations": ["x", "y"]}
    assert LLMService._extract_json('{"summary": "S", "limit') == {"summary": "S"}


class _Tokenizer:
    chat_template = None
    pad_token_id = eos_token_id = 0

    @staticmethod
    def encode(text, add_special_tokens=False):
        return list(range(max(1, len(text) // 4)))


def _service(outputs, **kwargs):
    """LLMService whose model returns the scripted outputs, recording each call."""
    from llm_service import LLMService

    service = LLMService(model_name=None, adapter_path="unused", **kwargs)
    service.tokenizer, service.model = _Tokenizer(), object()
    service.calls = []

    def run_model(text, *, use_adapter):
        service.calls.append({"text": text, "adapter": use_adapter})
        clean = outputs.pop(0) if outputs else ""
        return clean, "<|im_end|>" if not clean else clean[:20], 1 if not clean else 50

    service._run_model = run_model
    return service


def _rich_request(question=None):
    from schemas import AnalysisRequest

    return AnalysisRequest(
        plant_id="plant-1",
        plant_context={"user_question": question} if question else {},
        observations={"analysis_status": "success"},
        ml_results={
            "analysis_status": "success",
            "interval": {"start_utc": "2026-03-01T00:00:00+00:00", "end_utc": "2026-03-31T23:45:00+00:00",
                         "device_count": 2, "row_count": 5952},
            "energy": {"actual": {"value_kwh": 205884.98325}, "expected": {"value_kwh": 192644.5757},
                       "forecast": {"value_kwh": None, "reason": "No forecast file was supplied."}},
            "expected_deviation_kwh": 13240.4075,
            "device_performance": [{"device_id": "INV2", "actual_energy_kwh": 102088.93,
                                    "expected_energy_kwh": 96322.29, "deviation_kwh": 5766.64}],
            "anomaly_summary": {"total_alerts": 16, "alerts_by_device": {"INV2": 16}},
            "anomaly_runs": [{"device_id": "INV2", "start_utc": "2026-03-04T04:30:00+00:00",
                              "end_utc": "2026-03-04T08:15:00+00:00", "intervals": 16,
                              "overlapping_events": ["inverter_trip (INV2)"]}],
            "hypotheses": [{"label": "Logged outage or curtailment", "devices": ["INV2"]}],
            "data_quality": {"status": "pass"},
        },
    )


def test_evidence_brief_is_plain_text_with_supplied_values_only():
    from llm_service import LLMService

    brief = LLMService._evidence_brief(_rich_request())
    assert "measured energy 205,884.98 kWh" in brief
    assert "forecast energy unavailable (No forecast file was supplied.)" in brief
    assert "Inverter INV2: measured 102,088.93 kWh" in brief
    assert "overlapping logged event inverter_trip (INV2)" in brief
    assert "Logged outage or curtailment on INV2" in brief
    assert "{" not in brief and "value_kwh" not in brief


def test_case_explanation_uses_the_adapter_in_its_training_format():
    good = '{"summary": "INV2 was the only inverter with alerts, during its logged trip on 2026-03-04.", "confidence": "moderate"}'
    service = _service([good])
    result = service.analyze(_rich_request())
    assert result.summary.startswith("INV2 was the only inverter")
    first = service.calls[0]
    assert first["adapter"] is True
    assert "You are a solar plant analysis assistant." in first["text"]
    assert "Analyse this solar plant performance case." in first["text"]
    assert "Plant observations: Analysis status: success." in first["text"]
    assert service.last_generation_path == "adapter (training format)"


def test_follow_up_questions_go_to_the_base_model_first():
    answer = 'INV2 is the only inverter with alerts.", "confidence": "moderate"}'
    service = _service([answer])
    result = service.analyze(_rich_request("Which inverter underperformed?"))
    assert result.summary == "INV2 is the only inverter with alerts."
    assert service.calls[0]["adapter"] is False
    assert "Question: Which inverter underperformed?" in service.calls[0]["text"]
    assert service.last_generation_path == "base model (adapter disabled)"


def test_an_answer_repeating_the_previous_turn_is_rejected():
    request = _rich_request("What should I check first?")
    request.retrieved_context = ["USER: Which inverter underperformed?",
                                 "ASSISTANT: INV2 is the only inverter with alerts during its logged trip."]
    repeated = 'INV2 is the only inverter with alerts during its logged trip.", "confidence": "moderate"}'
    fresh = '{"summary": "Check INV2 alarm history for 2026-03-04 first.", "confidence": "moderate"}'
    service = _service([repeated, fresh[len('{"summary": "'):]])
    result = service.analyze(request)
    assert result.summary == "Check INV2 alarm history for 2026-03-04 first."
    assert "repeated an earlier answer" not in (service.last_inference_error or "")


def test_training_boilerplate_checks_are_removed():
    raw = ('{"summary": "INV2 had alerts during its trip.", "recommended_checks": '
           '["Verify timestamps, units and sensor-quality flags.", "Inspect INV2 for the 2026-03-04 trip."], '
           '"confidence": "moderate"}')
    service = _service([raw])
    result = service.analyze(_rich_request())
    assert result.recommended_checks == ["Inspect INV2 for the 2026-03-04 trip."]

def test_empty_adapter_output_falls_back_to_primed_then_base_model():
    # Attempt 1 and 2 (adapter) return nothing; attempt 3 (base model) answers. The
    # base attempt is primed with '{"summary": "', so the model continues from there.
    base_continuation = 'Measured energy was 205,884.98 kWh, above expected.", "confidence": "moderate"}'
    service = _service(["", "", base_continuation])
    result = service.analyze(_rich_request())
    assert result.summary == "Measured energy was 205,884.98 kWh, above expected."
    assert [call["adapter"] for call in service.calls] == [True, True, False]
    assert service.calls[1]["text"].endswith('{"summary": "')
    assert service.last_inference_error is None
    assert service.last_generation_path == "base model (adapter disabled)"


def test_memorized_training_answers_are_rejected():
    canned = '{"summary": "Low irradiance may explain part of the reduced output. Compare generation.", "confidence": "moderate"}'
    real = 'INV2 had 16 alert intervals during its logged trip.", "confidence": "moderate"}'
    service = _service([canned, canned[len('{"summary": "'):], real])
    result = service.analyze(_rich_request())
    assert result.summary == "INV2 had 16 alert intervals during its logged trip."


def test_all_failed_attempts_are_reported_with_reasons():
    import pytest

    service = _service(["", "", ""])
    with pytest.raises(ValueError):
        service.analyze(_rich_request())
    error = service.last_inference_error
    assert error.startswith("All local generation attempts failed")
    assert error.count("empty output") == 3
    assert "base model (adapter disabled)" in error


def test_time_budget_stops_further_attempts():
    service = _service(["", "", ""], time_budget_seconds=0.0)
    import pytest

    with pytest.raises(ValueError):
        service.analyze(_rich_request())
    assert len(service.calls) == 1
    assert "time budget" in service.last_inference_error


def test_adapter_mode_base_skips_the_adapter():
    service = _service(['ok answer about INV2.", "confidence": "low"}'], adapter_mode="base")
    service.analyze(_rich_request())
    assert [call["adapter"] for call in service.calls] == [False]


def test_identical_requests_reuse_the_validated_explanation():
    service = _service(['{"summary": "INV2 had alerts during its trip.", "confidence": "low"}'])
    first = service.analyze(_rich_request("What happened?"))
    second = service.analyze(_rich_request("What happened?"))
    assert first == second and len(service.calls) == 1


def test_oversized_brief_fails_explicitly():
    import pytest

    service = _service([], max_input_tokens=600)
    request = _rich_request()
    request.ml_results["limitations"] = ["x" * 3000] * 4
    with pytest.raises(ValueError, match="too large"):
        service.analyze(request)

