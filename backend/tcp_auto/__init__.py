"""TCP-Auto: draft traffic control plans from utility design drawings."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent
RULES_DIR = Path(os.environ.get("TCP_RULES_DIR") or REPO_ROOT / "rules")

__version__ = "0.1.0"
