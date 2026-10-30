import pandas as pd

from src.attribution import explain_interval


def test_explain_interval_returns_causes():
    result = explain_interval({"timestamp": "x"})
    assert "causes" in result
    assert "confidence" in result


def test_event_log_alone_does_not_prove_cause():
    interval = {
        "timestamp_utc": "2024-01-01T12:00:00Z",
        "inverter_id": "INV-01",
        "ac_power_kw": 80.0,
        "expected_power_kw": 80.0,
        "poa_irradiance_w_m2": 800.0,
        "solar_elevation_deg": 45.0,
        "status": "assessed",
    }
    event_log = pd.DataFrame(
        [
            {
                "start_utc": "2024-01-01T12:00:00Z",
                "end_utc": "2024-01-01T12:30:00Z",
                "event_type": "inverter_outage",
                "asset_id": "INV-01",
                "description": "Logged outage",
                "source": "operator",
            }
        ]
    )
    result = explain_interval(interval, event_log=event_log)

    assert result["primary_cause"] is None
    assert result["status"] == "unresolved"
    assert all(not hypothesis["root_cause_confirmed"] for hypothesis in result["hypotheses"])
    assert any(
        hypothesis["cause"] == "logged_outage_or_curtailment"
        and hypothesis["status"] == "unresolved"
        for hypothesis in result["hypotheses"]
    )
