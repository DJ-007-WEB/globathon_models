"""Attribution and evidence-based explanation helpers."""

from __future__ import annotations


def explain_interval(interval):
    """Return a minimal attribution payload placeholder."""
    return {"interval": interval, "causes": [], "confidence": 0.0}
