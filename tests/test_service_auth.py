from fastapi.testclient import TestClient

import api


def test_lifespan_registers_llm_service(monkeypatch):
    class FakeLLMService:
        def __init__(self, model_name, adapter_path):
            self.model_name = model_name
            self.adapter_path = adapter_path
            self.is_loaded = False

    monkeypatch.setattr(api, "LLMService", FakeLLMService)
    with TestClient(api.app):
        assert isinstance(api.app.state.llm_service, FakeLLMService)


def test_inference_requires_internal_service_token(monkeypatch):
    monkeypatch.setattr(api, "INTERNAL_SERVICE_TOKEN", "expected-secret")
    with TestClient(api.app) as client:
        response = client.post(
            "/api/v1/analyze",
            headers={"X-Service-Token": "incorrect"},
            json={"plant_id": "plant-1", "observations": {"actual_power_kw": 10}},
        )
    assert response.status_code == 401
