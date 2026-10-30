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
    with TestClient(main.app) as client:
        allowed = client.post(
            "/api/v1/analyze/upload",
            headers={"Authorization": "Bearer test-access-token"},
            files={"file": ("plant.csv", b"t,p\\n1,2", "text/csv")},
        )
    assert allowed.status_code == 503


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
        response = client.get("/api/v1/analyses")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert db.analyses.query == {"business_id": "business-a"}


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
