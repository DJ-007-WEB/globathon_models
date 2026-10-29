"""Feature engineering for the energy anomaly and forecasting pipeline."""

from __future__ import annotations

from typing import Iterable


def clear_sky_index(ghi: float, clear_sky_ghi: float) -> float:
    """Return the normalized ratio of actual to clear-sky irradiance."""
    if clear_sky_ghi == 0:
        return 0.0
    return float(ghi / clear_sky_ghi)


def hour_sin_cos(hour: int) -> tuple[float, float]:
    """Encode the hour-of-day using sine and cosine terms."""
    angle = (hour % 24) / 24.0 * 2.0 * 3.141592653589793
    return (float(__import__("math").sin(angle)), float(__import__("math").cos(angle)))


def normalize(values: Iterable[float]) -> list[float]:
    """Simple min-max normalization for a numeric sequence."""
    values_list = list(values)
    if not values_list:
        return []
    minimum = min(values_list)
    maximum = max(values_list)
    if maximum == minimum:
        return [0.0 for _ in values_list]
    return [(value - minimum) / (maximum - minimum) for value in values_list]
