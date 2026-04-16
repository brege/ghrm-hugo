from __future__ import annotations

from pathlib import Path


__version__ = "0.1.0"


ROOT_DIR = Path(__file__).resolve().parent.parent
THEME_DIR = ROOT_DIR / "theme" / "gh-readme"
VENDOR_DIR = THEME_DIR / "static" / "vendor"
