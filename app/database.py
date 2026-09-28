from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ============================================================
# Database Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_DIR = BASE_DIR / "data"
DATABASE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DATABASE_FILE = DATABASE_DIR / "healthcare.db"

DATABASE_URL = f"sqlite:///{DATABASE_FILE}"


# ============================================================
# Engine
# ============================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    },
)


# ============================================================
# Session
# ============================================================

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


# ============================================================
# Base
# ============================================================

Base = declarative_base()


# ============================================================
# Database Initialization
# ============================================================

def init_db():
    """
    Create all database tables.
    """

    from app.models import (
        Doctor,
        Patient,
        DoctorAvailability,
        Appointment,
    )

    Base.metadata.create_all(
        bind=engine,
    )