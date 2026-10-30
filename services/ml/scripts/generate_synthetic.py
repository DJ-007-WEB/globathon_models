"""Generate reproducible synthetic solar-plant scenarios.

This is a thin CLI wrapper around :mod:`src.synthetic`. Run from the project
root, for example::

    python scripts/generate_synthetic.py --seed 7 --n-scenarios 9 --out artifacts/synthetic_demo
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.synthetic import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
