"""Baseline physics and residual model interface."""

from __future__ import annotations


def physics_baseline(frame):
    """Placeholder for physics-based expected output estimation."""
    return {"rows": len(frame), "baseline": 0.0}


def residual_model(frame):
    """Placeholder for LightGBM residual model logic."""
    return {"rows": len(frame), "residuals": 0.0}
