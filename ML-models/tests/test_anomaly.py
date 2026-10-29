import numpy as np
import pandas as pd

from src.anomaly import cusum, detect_anomalies, peer_mad


def test_peer_mad_returns_score(sample_frame):
    result = peer_mad(sample_frame)
    assert "anomaly_score" in result


def test_cusum_returns_summary(sample_frame):
    result = cusum(sample_frame)
    assert "cusum" in result


def _peer_frame(actual_values, poa_values=None):
    timestamps = pd.to_datetime(
        ["2024-01-01T12:00:00Z", "2024-01-01T12:30:00Z", "2024-01-01T13:00:00Z"],
        utc=True,
    )
    devices = ["INV-01", "INV-02", "INV-03"]
    rows = []
    for index, timestamp in enumerate(timestamps):
        for position, device in enumerate(devices):
            actual = actual_values[index][position]
            poa = 800.0 if poa_values is None else poa_values[index]
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "inverter_id": device,
                    "ac_power_kw": actual,
                    "expected_power_kw": 80.0,
                    "rated_ac_power_kw": 100.0,
                    "poa_irradiance_w_m2": poa,
                    "solar_elevation_deg": 45.0,
                }
            )
    return pd.DataFrame(rows)


def test_dead_inverter_is_flagged():
    frame = _peer_frame(
        [
            [80.0, 80.0, 0.0],
            [80.0, 80.0, 0.0],
            [80.0, 80.0, 0.0],
        ]
    )
    result = detect_anomalies(
        frame,
        config={"anomaly": {"peer_min_devices": 3, "persistence_n": 2}},
    )

    assert result["alerts"]
    assert any(alert["inverter_id"] == "INV-03" for alert in result["alerts"])
    dead_rows = result["assessments"]["inverter_id"].eq("INV-03")
    assert result["assessments"].loc[dead_rows, "status"].eq("assessed").all()
    assert result["assessments"].loc[dead_rows, "alert"].any()


def test_low_irradiance_suppresses_alerts():
    frame = _peer_frame(
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        poa_values=[10.0, 10.0, 10.0],
    )
    result = detect_anomalies(
        frame,
        config={"anomaly": {"peer_min_devices": 3, "persistence_n": 2}},
    )

    assert result["alerts"] == []
    assert result["assessments"]["status"].eq("suppressed_low_irradiance").all()


def test_missing_data_is_not_treated_as_zero():
    frame = _peer_frame(
        [
            [80.0, 80.0, np.nan],
            [80.0, 80.0, np.nan],
            [80.0, 80.0, np.nan],
        ]
    )
    result = detect_anomalies(
        frame,
        config={"anomaly": {"peer_min_devices": 3, "persistence_n": 2}},
    )

    missing_rows = result["assessments"]["inverter_id"].eq("INV-03")
    assert result["assessments"].loc[missing_rows, "status"].eq("unavailable").all()
    assert result["assessments"].loc[missing_rows, "actual_power_kw"].isna().all()
    assert not result["assessments"].loc[missing_rows, "alert"].any()
