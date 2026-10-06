from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# Healthcare Database
# ============================================================

DATABASE_FILE = DATA_DIR / "healthcare.db"

DATABASE_URL = (
    f"sqlite:///{DATABASE_FILE}"
)


engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    },
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


Base = declarative_base()


# ============================================================
# Initialization
# ============================================================

def init_db():
    """
    Create healthcare application tables.
    """

    from backend.app.models import (
        Appointment,
        Doctor,
        DoctorAvailability,
        Patient,
    )

    Base.metadata.create_all(
        bind=engine,
    )