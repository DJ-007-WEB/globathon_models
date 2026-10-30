"""Configuration loading and JSON-safe serialization helpers.

The pipeline keeps every tunable threshold in ``configs/defaults.yaml`` and
every semantic column-name variant in ``configs/schema_vocab.yaml``.  Modules
must not embed plant-specific capacity, column names, units or timestamps.
"""

from __future__ import annotations

import copy
import math
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "defaults.yaml"
DEFAULT_VOCAB_PATH = PROJECT_ROOT / "configs" / "schema_vocab.yaml"


def _read_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a mapping at the top level of {path}")
    return loaded


@lru_cache(maxsize=8)
def _load_yaml_cached(path_string: str) -> dict[str, Any]:
    return _read_yaml(Path(path_string))


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping and return a defensive copy."""

    return copy.deepcopy(_load_yaml_cached(str(Path(path).resolve())))


def load_defaults(path: str | Path | None = None) -> dict[str, Any]:
    """Load the pipeline defaults."""

    return load_yaml(path or DEFAULT_CONFIG_PATH)


def load_vocab(path: str | Path | None = None) -> dict[str, Any]:
    """Load the semantic schema vocabulary."""

    return load_yaml(path or DEFAULT_VOCAB_PATH)


def get_path(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Read a nested config value using a dotted path."""

    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python objects.

    Missing values become ``None``; they are never coerced to zero.
    """

    if value is None:
        return None
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (str, bool, int)):
        if isinstance(value, bool):
            return bool(value)
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        converted = float(value)
        return None if not math.isfinite(converted) else converted
    if isinstance(value, (pd.Timestamp, datetime, date, time)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, pd.Series):
        return [json_safe(item) for item in value.tolist()]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)
