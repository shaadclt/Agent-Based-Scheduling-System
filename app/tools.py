import json
from datetime import datetime

from langchain_core.tools import tool
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import (
    Appointment,
    Doctor,
    DoctorAvailability,
    Patient,
)


# ============================================================
# Helper Functions
# ============================================================

def _normalize_name(name: str) -> str:
    """
    Normalize doctor/patient names.
    """

    if not name:
        return ""

    normalized = name.lower().strip()

    normalized = normalized.replace(
        "dr.",
        " ",
    )

    normalized = normalized.replace(
        "dr ",
        " ",
    )

    normalized = " ".join(
        normalized.split()
    )

    return normalized


def _find_doctor(
    db,
    doctor_name: str,
):
    """
    Find doctor using flexible name matching.
    """

    requested_name = _normalize_name(
        doctor_name
    )

    doctors = db.query(Doctor).all()

    for doctor in doctors:

        database_name = _normalize_name(
            doctor.name
        )

        if database_name == requested_name:
            return doctor

        if requested_name in database_name:
            return doctor

        if database_name in requested_name:
            return doctor

    return None


def _parse_date(date_string: str):

    return datetime.strptime(
        date_string,
        "%Y-%m-%d",
    ).date()


def _parse_time(time_string: str):

    return datetime.strptime(
        time_string,
        "%H:%M",
    ).time()


# ============================================================
# Search Doctors
# ============================================================

@tool
def search_doctors(
    specialty: str = "",
    query: str = "",
) -> str:
    """
    Search doctors by specialty, name,
    or general query.
    """

    db = SessionLocal()

    try:

        doctors = db.query(Doctor).all()

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

        matches = []

        for doctor in doctors:

            name = doctor.name.lower()
            doctor_specialty = (
                doctor.specialty.lower()
            )
            description = (
                doctor.description.lower()
                if doctor.description
                else ""
            )

            normalized_name = _normalize_name(
                doctor.name
            )

            specialty_match = False

            if specialty_normalized:

                specialty_match = (
                    specialty_normalized
                    in doctor_specialty
                    or
                    doctor_specialty
                    in specialty_normalized
                )

            query_match = False

            if query_normalized:

                query_match = (
                    query_normalized
                    in normalized_name
                    or
                    query_normalized
                    in doctor_specialty
                    or
                    query_normalized
                    in description
                )

            token_match = False

            if query_normalized:

                tokens = [
                    token
                    for token
                    in query_normalized.split()
                    if len(token) > 2
                ]

                searchable_text = " ".join(
                    [
                        normalized_name,
                        doctor_specialty,
                        description,
                    ]
                )

                if tokens:

                    token_match = all(
                        token in searchable_text
                        for token in tokens
                    )

            # When no search criteria are supplied, return all
            # doctors. This supports requests such as:
            # "Can you list the doctors available?"
            no_filters = not specialty_normalized and not query_normalized

            if (
                no_filters
                or specialty_match
                or query_match
                or token_match
            ):

                matches.append(
                    {
                        "id": doctor.id,
                        "name": doctor.name,
                        "specialty": doctor.specialty,
                        "experience": doctor.experience,
                        "description": doctor.description,
                    }
                )

        if not matches:

            return json.dumps(
                {
                    "status": "no_results",
                    "message": (
                        "No doctors were found "
                        "matching the requested criteria."
                    ),
                    "doctors": [],
                },
                indent=2,
            )

        return json.dumps(
            {
                "status": "success",
                "count": len(matches),
                "doctors": matches,
            },
            indent=2,
        )

    finally:

        db.close()


# ============================================================
# Check Availability
# ============================================================

@tool
def check_availability(
    doctor_name: str,
    appointment_date: str,
) -> str:
    """
    Check real availability stored in SQLite.
    """

    db = SessionLocal()

    try:

        doctor = _find_doctor(
            db,
            doctor_name,
        )

        if doctor is None:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        f"Doctor '{doctor_name}' "
                        "was not found."
                    ),
                    "available_slots": [],
                },
                indent=2,
            )

        requested_date = _parse_date(
            appointment_date
        )

        availability = (
            db.query(DoctorAvailability)
            .filter(
                DoctorAvailability.doctor_id
                == doctor.id,
                DoctorAvailability.date
                == requested_date,
            )
            .all()
        )

        if not availability:

            return json.dumps(
                {
                    "status": "success",
                    "doctor": doctor.name,
                    "date": appointment_date,
                    "available_slots": [],
                    "message": (
                        "No availability found "
                        "for this date."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Get existing bookings
        # ----------------------------------------------------

        existing_appointments = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id
                == doctor.id,
                Appointment.appointment_date
                == requested_date,
                Appointment.status
                == "confirmed",
            )
            .all()
        )

        booked_times = {
            appointment.appointment_time.strftime(
                "%H:%M"
            )
            for appointment
            in existing_appointments
        }

        # ----------------------------------------------------
        # Calculate free slots
        # ----------------------------------------------------

        available_slots = []

        for slot in availability:

            slot_time = slot.start_time.strftime(
                "%H:%M"
            )

            if slot_time not in booked_times:

                available_slots.append(
                    slot_time
                )

        return json.dumps(
            {
                "status": "success",
                "doctor": doctor.name,
                "specialty": doctor.specialty,
                "date": appointment_date,
                "available_slots": available_slots,
            },
            indent=2,
        )

    except ValueError:

        return json.dumps(
            {
                "status": "error",
                "message": (
                    "Invalid date format. "
                    "Use YYYY-MM-DD."
                ),
            },
            indent=2,
        )

    finally:

        db.close()


# ============================================================
# Book Appointment
# ============================================================

@tool
def book_appointment(
    doctor_name: str,
    patient_name: str,
    appointment_date: str,
    appointment_time: str,
) -> str:
    """
    Book an appointment using the SQLite database.
    Prevents double booking.
    """

    db = SessionLocal()

    try:

        # ----------------------------------------------------
        # Find doctor
        # ----------------------------------------------------

        doctor = _find_doctor(
            db,
            doctor_name,
        )

        if doctor is None:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        f"Doctor '{doctor_name}' "
                        "was not found."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Validate patient
        # ----------------------------------------------------

        patient_name = patient_name.strip()

        if not patient_name:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Patient name is required."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Parse date/time
        # ----------------------------------------------------

        try:

            requested_date = _parse_date(
                appointment_date
            )

            requested_time = _parse_time(
                appointment_time
            )

        except ValueError:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Invalid date or time format. "
                        "Use YYYY-MM-DD and HH:MM."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Check availability
        # ----------------------------------------------------

        availability = (
            db.query(DoctorAvailability)
            .filter(
                DoctorAvailability.doctor_id
                == doctor.id,
                DoctorAvailability.date
                == requested_date,
                DoctorAvailability.start_time
                == requested_time,
            )
            .first()
        )

        if availability is None:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "The selected time is not "
                        "available for this doctor."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Check existing appointment
        # ----------------------------------------------------

        existing = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id
                == doctor.id,
                Appointment.appointment_date
                == requested_date,
                Appointment.appointment_time
                == requested_time,
                Appointment.status
                == "confirmed",
            )
            .first()
        )

        if existing:

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "This appointment slot has "
                        "already been booked."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Find or create patient
        # ----------------------------------------------------

        patient = (
            db.query(Patient)
            .filter(
                Patient.name == patient_name
            )
            .first()
        )

        if patient is None:

            patient = Patient(
                name=patient_name
            )

            db.add(patient)
            db.flush()

        # ----------------------------------------------------
        # Create appointment
        # ----------------------------------------------------

        appointment = Appointment(
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=requested_date,
            appointment_time=requested_time,
            status="confirmed",
        )

        db.add(appointment)

        try:

            db.commit()

        except IntegrityError:

            db.rollback()

            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "The appointment slot was "
                        "already booked."
                    ),
                },
                indent=2,
            )

        # ----------------------------------------------------
        # Confirmation
        # ----------------------------------------------------

        return json.dumps(
            {
                "status": "success",
                "message": (
                    "Appointment booked successfully."
                ),
                "appointment": {
                    "id": appointment.id,
                    "patient_name": patient.name,
                    "doctor_name": doctor.name,
                    "specialty": doctor.specialty,
                    "date": appointment_date,
                    "time": appointment_time,
                    "status": appointment.status,
                },
            },
            indent=2,
        )

    finally:

        db.close()


# ============================================================
# Tool Registry
# ============================================================

def get_tools():

    return [
        search_doctors,
        check_availability,
        book_appointment,
    ]