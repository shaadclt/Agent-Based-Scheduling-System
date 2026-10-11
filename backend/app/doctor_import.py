
"""Validation and transactional import for doctors and their availability."""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from backend.app.database import SessionLocal
from backend.app.models import Doctor, DoctorAvailability


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_DOCTORS = 5000
SLOT_DURATION_MINUTES = 30

FIELD_ALIASES = {
    "name": ("name",),
    "specialty": ("specialty", "speciality"),
    "experience": (
        "experience",
        "years of experience",
        "years_of_experience",
    ),
    "description": ("description",),
    "availability": ("availability",),
}


def _normalize_key(value: str) -> str:
    """Normalize JSON field names for alias matching."""
    return " ".join(
        value.strip().lower().replace("_", " ").split()
    )


def _get_field(record: dict[str, Any], field: str):
    """Return a field using its supported aliases."""
    aliases = {
        _normalize_key(alias)
        for alias in FIELD_ALIASES[field]
    }

    for key, value in record.items():
        if _normalize_key(str(key)) in aliases:
            return value

    return None


def _validate_availability(
    availability: Any,
    record_number: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Validate a doctor's availability.

    Expected format:
    [
        {
            "date": "2026-10-12",
            "time_slots": ["09:00", "10:00"]
        }
    ]
    """
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []

    if not isinstance(availability, list):
        return [], [
            f"Record {record_number}: availability must be a list."
        ]

    seen_slots: set[tuple[str, str]] = set()

    for date_index, day in enumerate(availability, start=1):
        if not isinstance(day, dict):
            errors.append(
                f"Record {record_number}, availability entry "
                f"{date_index}: expected a JSON object."
            )
            continue

        date_value = day.get("date")
        time_slots = day.get("time_slots")

        if not isinstance(date_value, str):
            errors.append(
                f"Record {record_number}, availability entry "
                f"{date_index}: date must use YYYY-MM-DD format."
            )
            continue

        try:
            parsed_date = datetime.strptime(
                date_value.strip(), "%Y-%m-%d"
            ).date()

            # Reject non-canonical dates such as 2026-1-2.
            if parsed_date.isoformat() != date_value.strip():
                raise ValueError("Date is not in canonical format.")

        except ValueError:
            errors.append(
                f"Record {record_number}, availability entry "
                f"{date_index}: invalid date '{date_value}'. "
                "Use YYYY-MM-DD."
            )
            continue

        if not isinstance(time_slots, list) or not time_slots:
            errors.append(
                f"Record {record_number}, availability entry "
                f"{date_index}: time_slots must be a non-empty list."
            )
            continue

        valid_times: list[str] = []

        for time_value in time_slots:
            if not isinstance(time_value, str):
                errors.append(
                    f"Record {record_number}, date {date_value}: "
                    "each time slot must be a string in HH:MM format."
                )
                continue

            try:
                parsed_time = datetime.strptime(
                    time_value.strip(), "%H:%M"
                ).time()

                if parsed_time.strftime("%H:%M") != time_value.strip():
                    raise ValueError("Time is not in canonical format.")

            except ValueError:
                errors.append(
                    f"Record {record_number}, date {date_value}: "
                    f"invalid time '{time_value}'. Use HH:MM "
                    "in 24-hour format."
                )
                continue

            normalized_time = parsed_time.strftime("%H:%M")
            slot_key = (parsed_date.isoformat(), normalized_time)

            if slot_key in seen_slots:
                errors.append(
                    f"Record {record_number}: duplicate time slot "
                    f"{normalized_time} on {parsed_date.isoformat()}."
                )
                continue

            seen_slots.add(slot_key)
            valid_times.append(normalized_time)

        if valid_times:
            normalized.append(
                {
                    "date": parsed_date.isoformat(),
                    "time_slots": valid_times,
                }
            )

    return normalized, errors


def validate_doctors_json(raw: bytes) -> dict[str, Any]:
    """Parse and validate the uploaded doctors JSON file."""

    if not raw:
        return {
            "valid": False,
            "doctors": [],
            "errors": ["The uploaded file is empty."],
        }

    if len(raw) > MAX_UPLOAD_BYTES:
        return {
            "valid": False,
            "doctors": [],
            "errors": ["The file exceeds the 2 MB upload limit."],
        }

    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "valid": False,
            "doctors": [],
            "errors": [
                "The file must contain valid UTF-8 encoded JSON."
            ],
        }

    if not isinstance(payload, list) or not payload:
        return {
            "valid": False,
            "doctors": [],
            "errors": [
                "The JSON root must be a non-empty array of doctors."
            ],
        }

    if len(payload) > MAX_DOCTORS:
        return {
            "valid": False,
            "doctors": [],
            "errors": [
                f"A maximum of {MAX_DOCTORS} doctors is allowed."
            ],
        }

    doctors: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_names: set[str] = set()

    for index, record in enumerate(payload, start=1):
        if not isinstance(record, dict):
            errors.append(f"Record {index}: expected a JSON object.")
            continue

        name = _get_field(record, "name")
        specialty = _get_field(record, "specialty")
        experience = _get_field(record, "experience")
        description = _get_field(record, "description")
        availability = _get_field(record, "availability")

        if not isinstance(name, str) or not name.strip():
            errors.append(
                f"Record {index}: a non-empty name is required."
            )
            continue

        if not isinstance(specialty, str) or not specialty.strip():
            errors.append(
                f"Record {index}: a non-empty specialty/speciality "
                "is required."
            )
            continue

        if isinstance(experience, bool):
            errors.append(
                f"Record {index}: experience must be a whole number "
                "between 0 and 100."
            )
            continue

        try:
            numeric_experience = float(experience)
        except (TypeError, ValueError):
            errors.append(
                f"Record {index}: experience must be a number "
                "between 0 and 100."
            )
            continue

        if (
            not numeric_experience.is_integer()
            or not 0 <= numeric_experience <= 100
        ):
            errors.append(
                f"Record {index}: experience must be a whole number "
                "between 0 and 100."
            )
            continue

        if description is not None and not isinstance(description, str):
            errors.append(
                f"Record {index}: description must be text."
            )
            continue

        clean_name = name.strip()
        name_key = clean_name.casefold()

        if name_key in seen_names:
            errors.append(
                f"Record {index}: duplicate doctor name "
                f"'{clean_name}' in the uploaded file."
            )
            continue

        seen_names.add(name_key)

        doctor_record: dict[str, Any] = {
            "name": clean_name,
            "specialty": specialty.strip(),
            "experience": int(numeric_experience),
            "description": (
                description.strip()
                if isinstance(description, str)
                else ""
            ),
        }

        # If the field is present, it must be valid.
        # If omitted, the existing database schedule is preserved.
        if "availability" in {
            _normalize_key(str(key))
            for key in record.keys()
        }:
            clean_availability, availability_errors = (
                _validate_availability(availability, index)
            )
            errors.extend(availability_errors)
            doctor_record["availability"] = clean_availability

        doctors.append(doctor_record)

    return {
        "valid": not errors and bool(doctors),
        "doctors": doctors,
        "errors": errors,
    }


def import_doctors(
    doctors: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Insert or update doctors and import their availability.

    Availability is replaced only for records that explicitly
    contain the availability field. Other doctors and appointments
    are not deleted.
    """
    if not doctors:
        raise ValueError("There are no valid doctors to import.")

    db = SessionLocal()

    inserted = 0
    updated = 0
    availability_added = 0

    try:
        for item in doctors:
            doctor_data = {
                "name": item["name"],
                "specialty": item["specialty"],
                "experience": item["experience"],
                "description": item.get("description", ""),
            }

            # Exact, case-insensitive name matching avoids matching
            # Dr. Emily Carter to Dr. Emily Johnson.
            existing = (
                db.query(Doctor)
                .filter(
                    func.lower(Doctor.name)
                    == item["name"].casefold()
                )
                .first()
            )

            if existing:
                doctor = existing
                doctor.name = doctor_data["name"]
                doctor.specialty = doctor_data["specialty"]
                doctor.experience = doctor_data["experience"]
                doctor.description = doctor_data["description"]
                updated += 1
            else:
                doctor = Doctor(**doctor_data)
                db.add(doctor)
                db.flush()
                inserted += 1

            # Flush to ensure doctor.id exists before adding slots.
            db.flush()

            if "availability" not in item:
                continue

            # Replace this doctor's schedule only. This does not
            # remove appointments or availability for other doctors.
            db.query(DoctorAvailability).filter(
                DoctorAvailability.doctor_id == doctor.id
            ).delete(synchronize_session=False)

            for day in item["availability"]:
                appointment_date = datetime.strptime(
                    day["date"], "%Y-%m-%d"
                ).date()

                for time_string in day["time_slots"]:
                    start_datetime = datetime.strptime(
                        time_string, "%H:%M"
                    )
                    end_datetime = start_datetime + timedelta(
                        minutes=SLOT_DURATION_MINUTES
                    )

                    slot = DoctorAvailability(
                        doctor_id=doctor.id,
                        date=appointment_date,
                        start_time=start_datetime.time(),
                        end_time=end_datetime.time(),
                    )
                    db.add(slot)
                    availability_added += 1

        db.commit()

        return {
            "inserted": inserted,
            "updated": updated,
            "total_processed": len(doctors),
            "availability_slots_imported": availability_added,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def list_doctors() -> list[dict[str, Any]]:
    """Return the current doctor directory."""
    db = SessionLocal()

    try:
        records = (
            db.query(Doctor)
            .order_by(Doctor.name.asc())
            .all()
        )

        return [
            {
                "id": item.id,
                "name": item.name,
                "specialty": item.specialty,
                "experience": item.experience,
                "description": item.description or "",
            }
            for item in records
        ]

    finally:
        db.close()
