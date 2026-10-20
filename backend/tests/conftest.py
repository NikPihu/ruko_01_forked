"""Put the three Python folders on the path, same as `export PYTHONPATH=backend:ml:data`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for folder in ("backend", "ml", "data"):
    p = str(ROOT / folder)
    if p not in sys.path:
        sys.path.insert(0, p)
