"""FlagPole (tcp_auto): draft traffic control plans from utility design drawings."""

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
# In a PyInstaller build, bundled data (frontend/, rules/) sits under sys._MEIPASS.
REPO_ROOT = Path(getattr(sys, "_MEIPASS", PACKAGE_DIR.parent.parent))
RULES_DIR = Path(os.environ.get("TCP_RULES_DIR") or REPO_ROOT / "rules")

__version__ = "0.1.0"
