
from backend.app.database import init_db
from backend.app import models  # Ensure all models are registered with Base


def initialize_database() -> None:
    """Create database tables without importing doctor records."""
    init_db()
    print("Database tables initialized successfully.")


if __name__ == "__main__":
    initialize_database()
