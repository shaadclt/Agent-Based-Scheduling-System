from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


# ============================================================
# Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

CHECKPOINT_FILE = (
    DATA_DIR / "langgraph_checkpoints.db"
)


# ============================================================
# Checkpointer
# ============================================================

checkpointer = SqliteSaver.from_conn_string(
    str(CHECKPOINT_FILE)
)