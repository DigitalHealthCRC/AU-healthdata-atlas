"""Pytest bootstrap for this repo.

scripts/ is intentionally NOT a package (no __init__.py): the scripts import
each other as top-level modules (e.g. ``import register_parsing``). Tests
therefore need the scripts directory on sys.path before importing anything
from it.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
