"""Test import paths for the repo's flat server + collector layout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for path in (ROOT / "server", ROOT / "collector"):
    sys.path.insert(0, str(path))
