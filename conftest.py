"""pytest bootstrap: ensure the project root (this file's directory) is on
sys.path so `import app...` works no matter where pytest is launched from.
pytest auto-discovers this file and imports it before collecting tests."""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
