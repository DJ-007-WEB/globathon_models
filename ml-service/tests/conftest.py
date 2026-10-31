import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def isolate_service_token(monkeypatch):
    import api
    monkeypatch.setattr(api, "SERVICE_TOKEN", None)


@pytest.fixture
def sample_frame():
    return pd.DataFrame(
        {
            "timestamp": ["2024-01-01T00:00:00", "2024-01-01T01:00:00"],
            "ghi": [0.0, 100.0],
            "temperature": [15.0, 20.0],
            "power": [0.0, 200.0],
        }
    )
