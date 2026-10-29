import asyncio

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_health_is_independent_of_llm():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_forwards_payload_and_returns_normalized_result(monkeypatch):
    captured = {}

    async def fake_forward(payload):
        captured.update(payload)
        return {
            "request_id": None,
            "plant_id": payload["plant_id"],
            "model": "Qwen/Qwen3.5-0.8B",
            "analysis": {
                "summary": "Sample analysis.",
                "observations": ["power_output"],
                "possible_causes": [],
                "supporting_evidence": ["observations"],
                "recommended_checks": ["compare_with_expectation"],
                "limitations": ["sample data"],
                "confidence": "low",
            },
        }

    monkeypatch.setattr(main, "forward_to_llm", fake_forward)
    response = client.post(
        "/api/v1/analyze",
        json={
            "plant_id": "TEST-01",
            "observations": {"power_output_kw": 65, "expected_power_output_kw": 100},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"]
    assert body["plant_id"] == "TEST-01"
    assert body["analysis"]["summary"] == "Sample analysis."
    assert captured["observations"]["power_output_kw"] == 65
    assert captured["ml_results"] == {}


def test_analyze_rejects_missing_observations():
    response = client.post("/api/v1/analyze", json={"plant_id": "TEST-01"})
    assert response.status_code == 422


def test_analyze_returns_service_unavailable_when_llm_is_offline(monkeypatch):
    async def fake_forward(payload):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="LLM offline")

    monkeypatch.setattr(main, "forward_to_llm", fake_forward)
    response = client.post(
        "/api/v1/analyze",
        json={"plant_id": "TEST-02", "observations": {"power_output_kw": 65}},
    )
    assert response.status_code == 503
