from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


# ============================================================
# Paths
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
# Persistent SQLite Checkpointer
# ============================================================

_checkpointer_context = (
    SqliteSaver.from_conn_string(
        str(CHECKPOINT_FILE)
    )
)

checkpointer = (
    _checkpointer_context.__enter__()
)