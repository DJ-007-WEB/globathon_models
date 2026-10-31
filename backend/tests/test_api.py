import asyncio

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import main


def test_health_does_not_require_dependencies():
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_manual_measurement_endpoint_is_not_exposed():
    with TestClient(main.app) as client:
        response = client.post("/api/v1/analyze", json={"plant_id": "x", "observations": {"power_kw": 5}})
    assert response.status_code == 404


def test_ready_reports_degraded_when_services_are_offline(monkeypatch):
    monkeypatch.setattr(main, "ML_API_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(main, "LLM_API_URL", "http://127.0.0.1:1")
    with TestClient(main.app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ml_service_reachable"] is False


@pytest.mark.parametrize(
    "llm_payload,expected_status",
    [
        ({"status": "not_loaded", "model_loaded": False}, "degraded"),
        ({"status": "ready", "model_loaded": True}, "ready"),
    ],
)
def test_ready_requires_loaded_llm_model(monkeypatch, llm_payload, expected_status):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self.payload

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url):
            if url.endswith(":8002/ready"):
                return Response({"status": "ready"})
            return Response(llm_payload)

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(main, "ML_API_URL", "http://ml:8002")
    monkeypatch.setattr(main, "LLM_API_URL", "http://llm:8000")
    with TestClient(main.app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert response.json()["llm_status"] == llm_payload["status"]


def test_production_browser_access_requires_bearer(monkeypatch):
    monkeypatch.setattr(main, "ENVIRONMENT", "production")
    monkeypatch.setattr(main, "API_ACCESS_TOKEN", "test-access-token")
    monkeypatch.setattr(main, "SERVICE_TOKEN", "test-internal-token")
    with pytest.raises(HTTPException) as denied:
        main._authorize_browser(None)
    assert denied.value.status_code == 401
    claims = main._authorize_browser("Bearer test-access-token")
    assert claims["business_id"] == "legacy-deployment-workspace"

    # The legacy deployment gate still passes its request through the normal ML-first flow.
    monkeypatch.setattr(main, "ENVIRONMENT", "development")
    monkeypatch.setattr(main, "ML_API_URL", "http://127.0.0.1:1")
    with TestClient(main.app) as client:
        allowed = client.post(
            "/api/v1/analyze/upload",
            headers={"Authorization": "Bearer test-access-token"},
            files={"file": ("plant.csv", b"t,p\\n1,2", "text/csv")},
        )
    assert allowed.status_code == 503, allowed.text


def test_auth_endpoints_fail_closed_without_mongodb(monkeypatch):
    monkeypatch.setattr(main, "database", None)
    with TestClient(main.app) as client:
        response = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert response.status_code == 503
    assert "MONGODB_URI" in response.json()["detail"]


def test_jwt_requires_valid_signed_token(monkeypatch):
    monkeypatch.setattr(main, "API_ACCESS_TOKEN", "")
    monkeypatch.setattr(main, "JWT_SECRET", "x" * 48)
    token = main.jwt.encode(
        {"sub": "user-1", "business_id": "business-1", "exp": 4102444800},
        main.JWT_SECRET, algorithm=main.JWT_ALGORITHM,
    )
    claims = main._authorize_browser("Bearer " + token)
    assert claims["user_id"] == "user-1"
    assert claims["business_id"] == "business-1"
    with pytest.raises(HTTPException) as denied:
        main._authorize_browser("Bearer invalid")
    assert denied.value.status_code == 401


def test_analysis_list_is_scoped_to_authenticated_business(monkeypatch):
    class Cursor:
        def sort(self, *args): return self
        def skip(self, *args): return self
        def limit(self, *args): return self
        def __iter__(self): return iter([])
    class Collection:
        query = None
        def find(self, query, projection):
            self.query = query
            return Cursor()
        def count_documents(self, query):
            assert query == self.query
            return 0
    class Database:
        analyses = Collection()
    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    with TestClient(main.app) as client:
        response = client.get("/api/v1/analyses?plant_id=plant-west")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert db.analyses.query == {"business_id": "business-a", "plant_id": "plant-west"}


def test_analysis_detail_cannot_cross_business_boundary(monkeypatch):
    class Collection:
        query = None
        def find_one(self, query, projection):
            self.query = query
            return None
    class Database:
        analyses = Collection()
    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-b", "business_id": "business-b"
    })
    with TestClient(main.app) as client:
        response = client.get("/api/v1/analyses/request-from-business-a")
    assert response.status_code == 404
    assert db.analyses.query == {
        "business_id": "business-b", "request_id": "request-from-business-a"
    }


def test_analysis_history_rejects_invalid_pagination(monkeypatch):
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    with TestClient(main.app) as client:
        response = client.get("/api/v1/analyses?limit=500")
    assert response.status_code == 422


def test_follow_up_chat_uses_saved_ml_evidence_and_persists_messages(monkeypatch):
    from datetime import datetime, timezone
    class Cursor:
        def __init__(self, values): self.values = values
        def sort(self, *args): return self
        def limit(self, *args): return self
        def __iter__(self): return iter(self.values)
    class Analyses:
        def find_one(self, query, projection):
            assert query == {"business_id": "business-a", "request_id": "analysis-1"}
            return {"request_id": "analysis-1", "business_id": "business-a",
                    "plant_id": "plant-1", "analysis_mode": "full",
                    "result": {"ml_analysis": {"analysis_status": "partial",
                        "summary": "Actual energy was measured.",
                        "energy": {"actual": {"value_kwh": 12.5}},
                        "limitations": ["Forecast unavailable."]},
                        "analysis": {"summary": "Initial explanation."}}}
    class Messages:
        inserted = None
        def find(self, query, projection):
            assert query == {"business_id": "business-a", "request_id": "analysis-1"}
            return Cursor([])
        def insert_many(self, records): self.inserted = records
    class Database:
        analyses = Analyses()
        analysis_messages = Messages()
    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    captured = {}
    async def fake_llm(payload):
        captured.update(payload)
        return {"request_id": "analysis-1", "plant_id": "plant-1", "model": "test-model",
                "analysis": {"summary": "The saved ML result reports 12.5 kWh actual energy.",
                    "observations": ["The saved result contains 12.5 kWh actual energy."],
                    "possible_causes": [], "supporting_evidence": ["ml_results.energy.actual"],
                    "recommended_checks": ["Review the forecast source."],
                    "limitations": ["Forecast unavailable."], "confidence": "low"}}
    monkeypatch.setattr(main, "_post_llm", fake_llm)
    with TestClient(main.app) as client:
        response = client.post("/api/v1/analyses/analysis-1/chat",
                               json={"question": "Why is the forecast unavailable?"})
    assert response.status_code == 200, response.text
    assert captured["plant_context"]["user_question"] == "Why is the forecast unavailable?"
    assert captured["ml_results"]["energy"]["actual"]["value_kwh"] == 12.5
    assert response.json()["answer"]["summary"].startswith("The saved ML result")
    assert len(db.analysis_messages.inserted) == 2
    assert [item["role"] for item in db.analysis_messages.inserted] == ["user", "assistant"]


def test_follow_up_chat_cannot_access_another_business_analysis(monkeypatch):
    class Analyses:
        def find_one(self, query, projection):
            assert query == {"business_id": "business-b", "request_id": "private-analysis"}
            return None
    class Messages:
        def find(self, *args): raise AssertionError("Must not load chat for an inaccessible report")
    class Database:
        analyses = Analyses()
        analysis_messages = Messages()
    monkeypatch.setattr(main, "database", Database())
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-b", "business_id": "business-b"
    })
    with TestClient(main.app) as client:
        response = client.post("/api/v1/analyses/private-analysis/chat",
                               json={"question": "Show me the plant's readings"})
    assert response.status_code == 404


def test_follow_up_chat_rejects_empty_or_oversized_question(monkeypatch):
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    with TestClient(main.app) as client:
        empty = client.post("/api/v1/analyses/a/chat", json={"question": "  "})
        large = client.post("/api/v1/analyses/a/chat", json={"question": "x" * 2001})
    assert empty.status_code == 422
    assert large.status_code == 422


def test_create_plant_stores_business_scoped_metadata(monkeypatch):
    class Plants:
        inserted = None
        def insert_one(self, document): self.inserted = document
    class Database:
        plants = Plants()
    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-1", "business_id": "business-1"
    })
    with TestClient(main.app) as client:
        response = client.post("/api/v1/plants", json={
            "plant_id": "plant-west", "name": "West Solar Farm",
            "location": "Pune", "capacity_kw": 250, "timezone": "Asia/Kolkata"
        })
    assert response.status_code == 200, response.text
    assert response.json()["plant_id"] == "plant-west"
    assert db.plants.inserted["business_id"] == "business-1"
    assert db.plants.inserted["capacity_kw"] == 250


def test_plant_list_is_scoped_to_authenticated_business(monkeypatch):
    class Cursor:
        def sort(self, *args): return self
        def limit(self, *args): return self
        def __iter__(self): return iter([])
    class Plants:
        query = None
        def find(self, query, projection):
            self.query = query
            return Cursor()
    class Database:
        plants = Plants()
    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-2", "business_id": "business-2"
    })
    with TestClient(main.app) as client:
        response = client.get("/api/v1/plants")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert db.plants.query == {"business_id": "business-2"}


def test_plant_duplicate_identifier_returns_conflict(monkeypatch):
    from pymongo.errors import DuplicateKeyError
    class Plants:
        def insert_one(self, document): raise DuplicateKeyError("duplicate")
    class Database:
        plants = Plants()
    monkeypatch.setattr(main, "database", Database())
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-1", "business_id": "business-1"
    })
    with TestClient(main.app) as client:
        response = client.post("/api/v1/plants", json={
            "plant_id": "same", "name": "Solar Farm"
        })
    assert response.status_code == 409


def test_update_plant_cannot_cross_business_boundary(monkeypatch):
    class Result:
        matched_count = 0
    class Plants:
        def update_one(self, query, update):
            assert query == {"business_id": "business-b", "plant_id": "plant-a"}
            return Result()
    class Database:
        plants = Plants()
    monkeypatch.setattr(main, "database", Database())
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-b", "business_id": "business-b"
    })
    with TestClient(main.app) as client:
        response = client.patch("/api/v1/plants/plant-a", json={
            "plant_id": "plant-a", "name": "Renamed Plant"
        })
    assert response.status_code == 404


def test_analysis_history_rejects_invalid_plant_filter(monkeypatch):
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    with TestClient(main.app) as client:
        empty = client.get("/api/v1/analyses?plant_id=%20")
        oversized = client.get("/api/v1/analyses?plant_id=" + "x" * 129)
    assert empty.status_code == 422
    assert oversized.status_code == 422


def test_plant_capacity_rejects_non_finite_values(monkeypatch):
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })
    payload = main.PlantPayload(
        plant_id="plant-nan", name="Invalid Capacity", capacity_kw=float("nan")
    )
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(main.create_plant(payload, authorization=None))
    assert invalid.value.status_code == 422

def test_streaming_chat_emits_progressive_answer_and_final_structured_payload(monkeypatch):
    answer = {
        "summary": "Measured energy is below the expected level.",
        "observations": ["Measured energy was 12.5 kWh."],
        "possible_causes": [],
        "supporting_evidence": ["The ML service reported 12.5 kWh."],
        "recommended_checks": ["Review the inverter event log."],
        "limitations": ["Forecast coverage is incomplete."],
        "confidence": "moderate",
    }

    async def fake_chat(request_id, payload, authorization):
        assert request_id == "analysis-1"
        assert payload.question == "Why is output lower?"
        return {"answer": answer, "model": "test-model", "created_at": "2026-10-31T00:00:00+00:00"}

    monkeypatch.setattr(main, "ask_about_analysis", fake_chat)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyses/analysis-1/chat/stream",
            json={"question": "Why is output lower?"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "Measured energy was 12.5 kWh." in response.text
    assert "event: done" in response.text
    assert '"confidence": "moderate"' in response.text

def test_deterministic_chat_fallback_uses_only_saved_ml_values():
    answer = main._fallback_chat_answer(
        "What is driving the energy deviation?",
        {
            "analysis_status": "partial",
            "summary": "Measured energy is available but forecast data is missing.",
            "energy": {
                "forecast": {"value_kwh": None, "reason": "No forecast file was supplied."},
                "expected": {"value_kwh": 100.0, "reason": None},
                "actual": {"value_kwh": 92.5, "reason": None},
                "deviation": {"value_kwh": None, "reason": "Forecast energy is unavailable."},
            },
            "hypotheses": [],
            "anomalies": [],
            "limitations": ["Forecast data is missing."],
        },
    )
    assert "expected energy is 100.0 kWh" in answer["summary"]
    assert "measured actual energy is 92.5 kWh" in answer["summary"]
    assert answer["possible_causes"] == []
    assert answer["confidence"] == "insufficient_evidence"
    assert any("No forecast file was supplied." in item for item in answer["limitations"])

def test_follow_up_chat_returns_grounded_fallback_when_llm_is_unavailable(monkeypatch):
    from fastapi import HTTPException

    class Cursor:
        def sort(self, *args): return self
        def limit(self, *args): return self
        def __iter__(self): return iter([])

    class Analyses:
        def find_one(self, query, projection):
            return {
                "request_id": "analysis-fallback",
                "business_id": "business-a",
                "plant_id": "plant-1",
                "analysis_mode": "full",
                "result": {
                    "ml_analysis": {
                        "analysis_status": "partial",
                        "summary": "Measured energy is available; forecast is missing.",
                        "energy": {
                            "forecast": {"value_kwh": None, "reason": "No forecast file was supplied."},
                            "expected": {"value_kwh": 100.0, "reason": None},
                            "actual": {"value_kwh": 92.5, "reason": None},
                            "deviation": {"value_kwh": None, "reason": "Forecast energy is unavailable."},
                        },
                        "anomalies": [],
                        "hypotheses": [],
                        "evidence": [],
                        "limitations": ["Forecast data is missing."],
                    },
                    "analysis": {"recommended_checks": ["Upload the design forecast file."]},
                },
            }

    class Messages:
        inserted = None
        def find(self, *args): return Cursor()
        def insert_many(self, records): self.inserted = records

    class Database:
        analyses = Analyses()
        analysis_messages = Messages()

    db = Database()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_authorize_browser", lambda authorization: {
        "user_id": "user-a", "business_id": "business-a"
    })

    async def unavailable_llm(payload):
        raise HTTPException(status_code=503, detail="Local LLM unavailable.")

    monkeypatch.setattr(main, "_post_llm", unavailable_llm)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/analyses/analysis-fallback/chat",
            json={"question": "What is driving the energy deviation?"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "deterministic-fallback"
    assert "100.0 kWh" in body["answer"]["summary"]
    assert "92.5 kWh" in body["answer"]["summary"]
    assert body["answer"]["possible_causes"] == []
    assert len(db.analysis_messages.inserted) == 2

def test_invalid_llm_output_fallback_preserves_grounded_ml_evidence():
    result = main._unavailable_llm_explanation({
        "summary": "The analysis is partial because forecast coverage is missing.",
        "evidence": ["Measured energy: 125.0 kWh.", "Expected energy: unavailable."],
        "limitations": ["Forecast input was not supplied."],
    })
    assert result["summary"].startswith("The analysis is partial")
    assert result["observations"] == [
        "Measured energy: 125.0 kWh.",
        "Expected energy: unavailable.",
    ]
    assert result["possible_causes"] == []
    assert "Forecast input was not supplied." in result["limitations"]
    assert result["confidence"] == "insufficient_evidence"


def test_invalid_llm_output_fallback_does_not_invent_metrics():
    result = main._unavailable_llm_explanation({
        "analysis_status": "partial",
        "actual_energy": 125.0,
        "expected_energy": None,
    })
    assert "could not be validated" in result["summary"]
    assert result["observations"] == []
    assert result["possible_causes"] == []
    assert result["supporting_evidence"] == []


def test_deterministic_fallback_answers_device_questions_from_saved_device_totals():
    answer = main._fallback_chat_answer(
        "Which inverter underperformed?",
        {
            "analysis_status": "partial",
            "energy": {"actual": {"value_kwh": 30.0}, "expected": {"value_kwh": 40.0}},
            "expected_deviation": {"value_kwh": -10.0, "status": "available"},
            "device_performance": [
                {"device_id": "INV-01", "actual_energy_kwh": 20.0, "expected_energy_kwh": 21.0, "deviation_kwh": -1.0},
                {"device_id": "INV-02", "actual_energy_kwh": 10.0, "expected_energy_kwh": 19.0, "deviation_kwh": -9.0},
            ],
            "anomalies": [], "hypotheses": [],
        },
    )
    assert "Device INV-02: measured 10.0 kWh, expected 19.0 kWh, measured minus expected -9.0 kWh." in answer["observations"]
    assert "Measured minus expected energy: -10.0 kWh." in answer["observations"]
    assert answer["possible_causes"] == []


def test_production_ready_does_not_relay_internal_llm_error_details(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self.payload

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url):
            if "ml" in url:
                return Response({"status": "ready"})
            return Response({"status": "not_ready", "model_loaded": True, "model_name": "/models/secret-path",
                             "last_inference_error": "ValueError: raw output start: '{\"summary\"'"})

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(main, "ML_API_URL", "http://ml:8002")
    monkeypatch.setattr(main, "LLM_API_URL", "http://llm:8000")
    monkeypatch.setattr(main, "ENVIRONMENT", "production")
    body = asyncio.run(main.ready())
    assert body["status"] == "degraded"
    assert "raw output" not in body["llm_error"]
    assert body["llm_model_name"] is None
