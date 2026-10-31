import pytest

import main


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch):
    monkeypatch.setattr(main, "MONGODB_URI", "")
    monkeypatch.setattr(main, "database", None)
    monkeypatch.setattr(main, "mongo_client", None)
    monkeypatch.setattr(main, "API_ACCESS_TOKEN", "")
    monkeypatch.setattr(main, "SERVICE_TOKEN", "")
