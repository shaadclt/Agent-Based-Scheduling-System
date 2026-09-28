import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


# ============================================================
# File Paths
# ============================================================

DOCTORS_FILE = Path("data/doctors.json")
APPOINTMENTS_FILE = Path("data/doctor_appointment_requests.csv")


# ============================================================
# Helper Functions
# ============================================================

def _load_doctors() -> list:
    """
    Load doctor records from the JSON database.
    """

    if not DOCTORS_FILE.exists():
        raise FileNotFoundError(
            f"Doctor database not found: {DOCTORS_FILE}"
        )

    with open(DOCTORS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def _normalize_name(name: str) -> str:
    """
    Normalize doctor names for flexible matching.

    Examples:
        "Dr. Michael Brown" -> "michael brown"
        "Michael Brown"     -> "michael brown"
        "DR MICHAEL BROWN"  -> "michael brown"
    """

    if not name:
        return ""

    normalized = name.lower().strip()

    # Remove common doctor prefixes
    normalized = normalized.replace("dr.", " ")
    normalized = normalized.replace("dr ", " ")

    # Normalize whitespace
    normalized = " ".join(normalized.split())

    return normalized


def _find_doctor(doctor_name: str) -> Optional[dict]:
    """
    Find a doctor using flexible name matching.
    """

    doctors = _load_doctors()

    requested_name = _normalize_name(doctor_name)

    if not requested_name:
        return None

    for doctor in doctors:

        database_name = _normalize_name(
            doctor.get("name", "")
        )

        if not database_name:
            continue

        # Exact match
        if database_name == requested_name:
            return doctor

        # Partial match
        if requested_name in database_name:
            return doctor

        if database_name in requested_name:
            return doctor

    return None


# ============================================================
# Doctor Search Tool
# ============================================================

@tool
def search_doctors(
    specialty: Optional[str] = None,
    query: Optional[str] = None,
) -> str:
    """
    Search the doctor database by medical specialty,
    doctor name, or general search query.

    Args:
        specialty: Medical specialty such as Neurologist,
                   Cardiologist, Dermatologist, etc.
        query: Doctor name or general search text.

    Returns:
        JSON string containing matching doctors.
    """

    doctors = _load_doctors()

    specialty_normalized = (
        specialty.lower().strip()
        if specialty
        else ""
    )

    query_normalized = (
        query.lower().strip()
        if query
        else ""
    )

    # Normalize punctuation
    specialty_normalized = (
        specialty_normalized
        .replace(",", "")
        .replace(".", "")
    )

    query_normalized = (
        query_normalized
        .replace(",", "")
        .replace(".", "")
    )

    matches = []

    for doctor in doctors:

        name = str(
            doctor.get("name", "")
        ).lower()

        doctor_specialty = str(
            doctor.get("specialty", "")
        ).lower()

        description = str(
            doctor.get("description", "")
        ).lower()

        # Remove "dr." for matching
        normalized_name = _normalize_name(name)

        # ----------------------------------------------------
        # Specialty matching
        # ----------------------------------------------------

        specialty_match = False

        if specialty_normalized:

            specialty_match = (
                specialty_normalized in doctor_specialty
                or doctor_specialty in specialty_normalized
            )

        # ----------------------------------------------------
        # Query matching
        # ----------------------------------------------------

        query_match = False

        if query_normalized:

            query_match = (
                query_normalized in normalized_name
                or query_normalized in doctor_specialty
                or query_normalized in description
            )

        # ----------------------------------------------------
        # Token-based matching
        # ----------------------------------------------------

        token_match = False

        if query_normalized:

            query_tokens = query_normalized.split()

            searchable_text = " ".join(
                [
                    normalized_name,
                    doctor_specialty,
                    description,
                ]
            )

            # Match when all meaningful query tokens exist
            # somewhere in the doctor's searchable information.
            if query_tokens:
                token_match = all(
                    token in searchable_text
                    for token in query_tokens
                    if len(token) > 2
                )

        if specialty_match or query_match or token_match:
            matches.append(
                {
                    "name": doctor.get("name"),
                    "specialty": doctor.get("specialty"),
                    "experience": doctor.get("experience"),
                    "description": doctor.get("description"),
                }
            )

    # --------------------------------------------------------
    # No results
    # --------------------------------------------------------

    if not matches:
        return json.dumps(
            {
                "status": "no_results",
                "message": (
                    "No doctors were found matching "
                    "the requested criteria."
                ),
                "doctors": [],
            },
            indent=2,
        )

    # --------------------------------------------------------
    # Results
    # --------------------------------------------------------

    return json.dumps(
        {
            "status": "success",
            "count": len(matches),
            "doctors": matches,
        },
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
    Check available appointment slots for a doctor
    on a specific date.

    Args:
        doctor_name: Name of the doctor.
        appointment_date: Appointment date in YYYY-MM-DD format.

    Returns:
        JSON string containing available appointment slots.
    """

    doctor = _find_doctor(doctor_name)

    # --------------------------------------------------------
    # Doctor not found
    # --------------------------------------------------------

    if doctor is None:

        return json.dumps(
            {
                "status": "error",
                "message": (
                    f"Doctor '{doctor_name}' was not found."
                ),
                "available_slots": [],
            },
            indent=2,
        )

    # --------------------------------------------------------
    # Current Phase 1 availability
    # --------------------------------------------------------
    # These are deterministic sample slots.
    # Phase 2 can replace this with database-backed
    # doctor schedules and existing appointment checks.

    available_slots = [
        "09:00",
        "10:30",
        "14:00",
        "15:30",
        "17:00",
    ]

    return json.dumps(
        {
            "status": "success",
            "doctor": doctor.get("name"),
            "specialty": doctor.get("specialty"),
            "date": appointment_date,
            "available_slots": available_slots,
        },
        indent=2,
    )


# ============================================================
# Booking Tool
# ============================================================

@tool
def book_appointment(
    doctor_name: str,
    patient_name: str,
    appointment_date: str,
    appointment_time: str,
) -> str:
    """
    Book an appointment with a doctor.

    Args:
        doctor_name: Name of the doctor.
        patient_name: Patient's name.
        appointment_date: Appointment date in YYYY-MM-DD format.
        appointment_time: Appointment time in HH:MM format.

    Returns:
        JSON string containing booking confirmation.
    """

    # --------------------------------------------------------
    # Validate doctor
    # --------------------------------------------------------

    doctor = _find_doctor(doctor_name)

    if doctor is None:

        return json.dumps(
            {
                "status": "error",
                "message": (
                    f"Doctor '{doctor_name}' was not found."
                ),
            },
            indent=2,
        )

    # --------------------------------------------------------
    # Validate required fields
    # --------------------------------------------------------

    if not patient_name.strip():

        return json.dumps(
            {
                "status": "error",
                "message": "Patient name is required.",
            },
            indent=2,
        )

    if not appointment_date.strip():

        return json.dumps(
            {
                "status": "error",
                "message": "Appointment date is required.",
            },
            indent=2,
        )

    if not appointment_time.strip():

        return json.dumps(
            {
                "status": "error",
                "message": "Appointment time is required.",
            },
            indent=2,
        )

    # --------------------------------------------------------
    # Validate appointment slot
    # --------------------------------------------------------

    valid_slots = [
        "09:00",
        "10:30",
        "14:00",
        "15:30",
        "17:00",
    ]

    if appointment_time not in valid_slots:

        return json.dumps(
            {
                "status": "error",
                "message": (
                    f"'{appointment_time}' is not a valid "
                    "appointment slot."
                ),
                "available_slots": valid_slots,
            },
            indent=2,
        )

    # --------------------------------------------------------
    # Create data directory if necessary
    # --------------------------------------------------------

    APPOINTMENTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Create CSV file with header if it doesn't exist
    # --------------------------------------------------------

    file_exists = APPOINTMENTS_FILE.exists()

    with open(
        APPOINTMENTS_FILE,
        "a",
        encoding="utf-8",
        newline="",
    ) as file:

        if not file_exists:

            file.write(
                "patient_name,"
                "doctor_name,"
                "specialty,"
                "appointment_date,"
                "appointment_time\n"
            )

        file.write(
            f'"{patient_name}",'
            f'"{doctor.get("name")}",'
            f'"{doctor.get("specialty")}",'
            f'"{appointment_date}",'
            f'"{appointment_time}"\n'
        )

    # --------------------------------------------------------
    # Return confirmation
    # --------------------------------------------------------

    return json.dumps(
        {
            "status": "success",
            "message": "Appointment booked successfully.",
            "appointment": {
                "patient_name": patient_name,
                "doctor_name": doctor.get("name"),
                "specialty": doctor.get("specialty"),
                "date": appointment_date,
                "time": appointment_time,
            },
        },
        indent=2,
    )


# ============================================================
# Tool Registry
# ============================================================

def get_tools():
    """
    Return all tools available to the scheduling agent.
    """

    return [
        search_doctors,
        check_availability,
        book_appointment,
    ]