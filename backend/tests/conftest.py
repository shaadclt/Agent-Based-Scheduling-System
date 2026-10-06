import os
import sys
from pathlib import Path

# Ensure the project root is importable when pytest is launched from
# the repository root or from another working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# graph.py initializes ChatGroq at import time. Tests replace the LLM
# immediately after import, so a non-empty placeholder is sufficient.
os.environ.setdefault("GROQ_API_KEY", "test-key")
