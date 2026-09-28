from datetime import datetime
from pathlib import Path
from typing import Optional

import json

from langchain_core.tools import tool


# ============================================================
# Configuration
# ============================================================

DOCTORS_FILE = Path("data/doctors.json")
APPOINTMENTS_FILE = Path(
    "data/doctor_appointment_requests.csv"
)


# ============================================================
# Internal helpers
# ============================================================

def _load_doctors() -> list[dict]:
    """
    Load doctor information from the JSON dataset.
    """

    if not DOCTORS_FILE.exists():
        raise FileNotFoundError(
            f"Doctor database not found: {DOCTORS_FILE}"
        )

    with open(
        DOCTORS_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


# ============================================================
# Doctor Search Tool
# ============================================================

@tool
def search_doctors(
    specialty: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """
    Search the doctor database.

    Use this tool when the patient needs to find a doctor
    based on specialty or a general requirement.

    Args:
        specialty: Medical specialty such as Cardiologist,
                   Dermatologist, Neurologist, etc.
        query: Additional search text.
    """

    doctors = _load_doctors()

    specialty_normalized = (
        specialty.lower().strip()
        if specialty
        else None
    )

    query_normalized = (
        query.lower().strip()
        if query
        else None
    )

    matches = []

    for doctor in doctors:

        doctor_specialty = str(
            doctor.get("specialty", "")
        ).lower()

        doctor_name = str(
            doctor.get("name", "")
        ).lower()

        doctor_description = str(
            doctor.get("description", "")
        ).lower()

        specialty_match = (
            specialty_normalized
            and specialty_normalized
            in doctor_specialty
        )

        query_match = False

        if query_normalized:

            query_match = (
                query_normalized in doctor_name
                or query_normalized in doctor_specialty
                or query_normalized in doctor_description
            )

        if specialty_match or query_match:

            matches.append(doctor)

    # If no specific filters were provided
    if not specialty_normalized and not query_normalized:
        matches = doctors

    if not matches:

        return (
            "No doctors were found matching the requested "
            "criteria."
        )

    results = []

    for doctor in matches:

        results.append(
            {
                "name": doctor.get("name"),
                "specialty": doctor.get("specialty"),
                "experience": doctor.get("experience"),
                "description": doctor.get("description"),
            }
        )

    return json.dumps(
        results,
        indent=2,
    )


# ============================================================
# Availability Tool
# ============================================================

@tool
def check_availability(
    doctor_name: str,
    appointment_date: str,
) -> str:
    """
    Check available appointment slots for a doctor.

    Args:
        doctor_name: Name of the doctor.
        appointment_date: Requested date in YYYY-MM-DD format.

    Returns:
        Available appointment slots.
    """

    doctors = _load_doctors()

    doctor = None

    for item in doctors:

        if item.get("name", "").lower() == (
            doctor_name.lower().strip()
        ):
            doctor = item
            break

    if doctor is None:

        return (
            f"Doctor '{doctor_name}' was not found."
        )

    # --------------------------------------------------------
    # Phase 1 simulated availability
    # --------------------------------------------------------
    #
    # We intentionally use deterministic sample slots for
    # Phase 1. In Phase 2 this will be replaced with real
    # schedule data from a database.
    #

    available_slots = [
        "09:00",
        "10:30",
        "14:00",
        "15:30",
        "17:00",
    ]

    return json.dumps(
        {
            "doctor": doctor.get("name"),
            "date": appointment_date,
            "available_slots": available_slots,
        },
        indent=2,
    )


# ============================================================
# Appointment Booking Tool
# ============================================================

@tool
def book_appointment(
    patient_name: str,
    doctor_name: str,
    appointment_date: str,
    appointment_time: str,
) -> str:
    """
    Book an appointment for a patient.

    Args:
        patient_name: Patient's name.
        doctor_name: Doctor's name.
        appointment_date: Appointment date in YYYY-MM-DD format.
        appointment_time: Appointment time in HH:MM format.

    Returns:
        Booking confirmation.
    """

    # --------------------------------------------------------
    # Validate doctor
    # --------------------------------------------------------

    doctors = _load_doctors()

    doctor = None

    for item in doctors:

        if item.get("name", "").lower() == (
            doctor_name.lower().strip()
        ):
            doctor = item
            break

    if doctor is None:

        return (
            f"Booking failed. Doctor '{doctor_name}' "
            f"was not found."
        )

    # --------------------------------------------------------
    # Validate slot
    # --------------------------------------------------------

    valid_slots = [
        "09:00",
        "10:30",
        "14:00",
        "15:30",
        "17:00",
    ]

    if appointment_time not in valid_slots:

        return (
            f"Booking failed. {appointment_time} is not "
            f"a valid available slot."
        )

    # --------------------------------------------------------
    # Save appointment request
    # --------------------------------------------------------

    APPOINTMENTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    appointment = {
        "timestamp": datetime.now().isoformat(),
        "patient_name": patient_name,
        "doctor_name": doctor_name,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
    }

    file_exists = APPOINTMENTS_FILE.exists()

    import csv

    with open(
        APPOINTMENTS_FILE,
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=appointment.keys(),
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(appointment)

    # --------------------------------------------------------
    # Generate confirmation
    # --------------------------------------------------------

    return (
        "Appointment successfully booked.\n"
        f"Patient: {patient_name}\n"
        f"Doctor: {doctor_name}\n"
        f"Date: {appointment_date}\n"
        f"Time: {appointment_time}"
    )


# ============================================================
# Tool Registry
# ============================================================

def get_tools():
    """
    Return all tools used by the scheduling agent.
    """

    return [
        search_doctors,
        check_availability,
        book_appointment,
    ]