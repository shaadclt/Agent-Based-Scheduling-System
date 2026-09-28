import json
from datetime import date, time
from pathlib import Path

from app.database import SessionLocal, init_db
from app.models import Doctor, DoctorAvailability


# ============================================================
# Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DOCTORS_FILE = BASE_DIR / "data" / "doctors.json"


# ============================================================
# Seed Database
# ============================================================

def seed_database():

    init_db()

    db = SessionLocal()

    try:

        # ----------------------------------------------------
        # Check whether doctors already exist
        # ----------------------------------------------------

        existing_doctors = db.query(Doctor).count()

        if existing_doctors > 0:

            print(
                f"Database already contains "
                f"{existing_doctors} doctors."
            )

            return

        # ----------------------------------------------------
        # Load JSON
        # ----------------------------------------------------

        with open(
            DOCTORS_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            doctors = json.load(file)

        # ----------------------------------------------------
        # Insert doctors
        # ----------------------------------------------------

        doctor_objects = []

        for doctor_data in doctors:

            doctor = Doctor(
                name=doctor_data["name"],
                specialty=doctor_data["specialty"],
                experience=doctor_data["experience"],
                description=doctor_data["description"],
            )

            db.add(doctor)
            doctor_objects.append(doctor)

        db.commit()

        # ----------------------------------------------------
        # Generate sample availability
        # ----------------------------------------------------

        available_dates = [
            date(2026, 10, 1),
            date(2026, 10, 2),
            date(2026, 10, 3),
            date(2026, 10, 4),
            date(2026, 10, 5),
        ]

        time_slots = [
            (
                time(9, 0),
                time(9, 30),
            ),
            (
                time(10, 30),
                time(11, 0),
            ),
            (
                time(14, 0),
                time(14, 30),
            ),
            (
                time(15, 30),
                time(16, 0),
            ),
            (
                time(17, 0),
                time(17, 30),
            ),
        ]

        # ----------------------------------------------------
        # Add availability
        # ----------------------------------------------------

        for doctor in doctor_objects:

            for available_date in available_dates:

                for start_time, end_time in time_slots:

                    availability = DoctorAvailability(
                        doctor_id=doctor.id,
                        date=available_date,
                        start_time=start_time,
                        end_time=end_time,
                    )

                    db.add(availability)

        db.commit()

        print(
            f"Database initialized successfully.\n"
            f"Doctors: {len(doctor_objects)}"
        )

    finally:

        db.close()


if __name__ == "__main__":
    seed_database()