import os
import sys
from pathlib import Path


# ============================================================
# Project Root
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


# ============================================================
# Test Environment
# ============================================================

# graph.py initializes ChatGroq when imported.
# Tests replace the LLM with a fake implementation,
# so a placeholder API key is sufficient.
os.environ.setdefault(
    "GROQ_API_KEY",
    "test-key",
)