import pytest

import api


@pytest.fixture(autouse=True)
def isolate_local_environment(monkeypatch):
    monkeypatch.setattr(api, "SERVICE_TOKEN", None)
    monkeypatch.setattr(api, "WARMUP_ON_STARTUP", False)
