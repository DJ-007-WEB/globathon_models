"""Anomaly detection primitives."""

from __future__ import annotations


def peer_mad(frame):
    """Placeholder peer/MAD anomaly score computation."""
    return {"rows": len(frame), "anomaly_score": 0.0}


def cusum(frame):
    """Placeholder CUSUM detection logic."""
    return {"rows": len(frame), "cusum": 0.0}
