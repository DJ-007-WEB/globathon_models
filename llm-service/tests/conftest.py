import pytest

import api


@pytest.fixture(autouse=True)
def isolate_local_environment(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", None)
