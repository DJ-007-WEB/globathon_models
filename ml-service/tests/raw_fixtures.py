"""Generic raw-input fixtures that mimic common vendor exports.

They deliberately use features that tripped ingestion in the field: a units row
under the header, day-first dates whose first days are ambiguous, wide per-inverter
power columns with suffix device labels, companion workbook sheets (info, devices,
events), hourly weather stamped at :30 with GHI only, and an hourly design forecast.
Nothing in the service may depend on these exact names.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

LOCAL_TZ = "Asia/Kolkata"


def _sun(local_times: pd.DatetimeIndex) -> np.ndarray:
    hour = local_times.hour + local_times.minute / 60.0
    # Daylight roughly 07:00-18:12 local in March at ~28 N; avoids night-time artefacts.
    return np.clip(np.sin((hour - 7.0) / 11.2 * np.pi), 0.0, None)


def write_raw_inputs(
    directory: Path,
    *,
    days: int = 31,
    seed: int = 11,
    sheet_names: tuple[str, str, str, str] = ("Data", "Info", "Devices", "Events"),
) -> dict[str, Path]:
    """Write a measured workbook, a weather CSV and a forecast CSV; return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    # --- measured workbook: 15-minute, local time, day-first text dates -------------
    local = pd.date_range("2026-03-01 00:00", periods=days * 96, freq="15min")
    sun = _sun(local)
    cloud = rng.uniform(0.85, 1.0, len(local))
    gti = 1000.0 * sun * cloud
    ghi = 0.85 * gti
    t_amb = np.asarray(20.0 + 10.0 * sun + rng.normal(0.0, 0.3, len(local)))
    t_array = np.asarray(t_amb + 25.0 * sun)
    capacity_ac, capacity_dc = 500.0, 600.0
    healthy = capacity_dc * gti / 1000.0 * 0.96 * (1 - 0.004 * (t_array - 25.0))
    ac1 = np.minimum(np.asarray(healthy) * 0.97, capacity_ac)
    ac2 = ac1.copy()
    fault = np.asarray((local >= "2026-03-04 10:00") & (local < "2026-03-04 14:00"))
    ac2[fault] = 0.0  # INV2 trip, logged in the event sheet
    states2 = np.where(fault, "FAULT", np.where(sun > 0, "RUN", "STANDBY"))
    states1 = np.where(sun > 0, "RUN", "STANDBY")
    data = pd.DataFrame({
        "Date": local.strftime("%d-%m-%Y %H:%M"),
        "GTI": gti.round(2), "GHI": ghi.round(2), "T_Amb": t_amb.round(2), "TArray": t_array.round(2),
        "E_Grid_INV1": ac1.round(3), "E_Grid_INV2": ac2.round(3),
        "EArray_INV1": (ac1 / 0.97).round(3), "EArray_INV2": (ac2 / 0.97).round(3),
        "State_INV1": states1, "State_INV2": states2,
    })
    units = pd.DataFrame([["dd-mm-yyyy hh:mm", "W/m²", "W/m²", "°C", "°C", "kW", "kW", "kW", "kW", "", ""]],
                         columns=data.columns)
    blank = pd.DataFrame([[None] * len(data.columns)], columns=data.columns)
    data = pd.concat([units, blank, data], ignore_index=True)  # header, units row, blank row, data
    info = pd.DataFrame({
        "Parameter": ["Timezone", "Interval", "Latitude", "Longitude", "Plant AC capacity (kW)",
                      "Plant DC capacity (kWp)", "E_Grid_*", "EArray_*"],
        "Value": [LOCAL_TZ, "15 min", 28.46, 77.03, 1000, 1200,
                  "Average AC grid power over each 15-minute interval (kW), not energy",
                  "Average DC array power over each 15-minute interval (kW), not energy"],
    })
    devices = pd.DataFrame({
        "device_id": ["INV1", "INV2", "WS1"],
        "device_type": ["inverter", "inverter", "weather_station"],
        "rated_ac_kw": [capacity_ac, capacity_ac, None],
        "dc_kwp": [capacity_dc, capacity_dc, None],
    })
    events = pd.DataFrame({
        "start": ["04-03-2026 10:00", "15-03-2026 11:00", "20-03-2026 09:00", "27-03-2026 12:00"],
        "end": ["04-03-2026 14:00", "15-03-2026 12:00", "20-03-2026 10:00", "27-03-2026 13:00"],
        "device_id": ["INV2", "", "INV1", "INV2"],
        "event_type": ["inverter_trip", "grid_curtailment", "maintenance", "derate"],
        "description": ["INV2 tripped on DC isolation fault", "Grid operator curtailment",
                        "Scheduled cleaning of INV1 array", "Thermal derate"],
    })
    workbook = directory / "plant_measured_data_15min.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        data_sheet, info_sheet, devices_sheet, events_sheet = sheet_names
        # Companion sheets come first on purpose: discovery must use content, not order.
        events.to_excel(writer, sheet_name=events_sheet, index=False)
        info.to_excel(writer, sheet_name=info_sheet, index=False)
        data.to_excel(writer, sheet_name=data_sheet, index=False)
        devices.to_excel(writer, sheet_name=devices_sheet, index=False)

    # --- weather: hourly at :30, units row, GHI only (no POA) ------------------------
    hourly = pd.date_range("2026-01-01 00:30", "2026-12-31 23:30", freq="1h")
    wsun = _sun(hourly)
    weather = pd.DataFrame({
        "date": hourly.strftime("%d-%m-%Y %H:%M"),
        "GHI": (850.0 * wsun).round(1), "DNI": (700.0 * wsun).round(1), "DHI": (150.0 * wsun).round(1),
        "T_Amb": (20.0 + 10.0 * wsun).round(1), "WS": 2.0,
    })
    weather_units = pd.DataFrame([["", "W/m²", "W/m²", "W/m²", "°C", "m/s"]], columns=weather.columns)
    weather_blank = pd.DataFrame([[None] * len(weather.columns)], columns=weather.columns)
    weather_path = directory / "weather_city_typical_year_hourly.csv"
    pd.concat([weather_units, weather_blank, weather], ignore_index=True).to_csv(weather_path, index=False)

    # --- design forecast: hourly, local, expected AC power -----------------------------
    fh = pd.date_range("2026-01-01 00:30", "2026-12-31 23:30", freq="1h")
    fsun = _sun(fh + pd.Timedelta(minutes=30))
    forecast = pd.DataFrame({
        # ISO with an explicit offset, stamped at :30 like the weather file.
        "timestamp": fh.strftime("%Y-%m-%d %H:%M:%S") + "+05:30",
        "design_poa_w_m2": (1000.0 * fsun).round(2),
        "design_cell_temp_c": (25.0 + 30.0 * fsun).round(2),
        "design_expected_ac_kw": (2 * capacity_dc * fsun * 0.93).round(3),
    })
    forecast_path = directory / "design_forecast_hourly.csv"
    forecast.to_csv(forecast_path, index=False)
    return {"operating": workbook, "weather": weather_path, "forecast": forecast_path}
