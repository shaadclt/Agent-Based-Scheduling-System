
import json
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.database import SessionLocal
from backend.app.models import Doctor


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_DOCTORS = 5000


# Accept the original JSON keys and normalized equivalents.
FIELD_ALIASES = {
    "name": ("name",),
    "specialty": ("specialty", "speciality"),
    "experience": (
        "experience",
        "years of experience",
        "years_of_experience",
    ),
    "description": ("description",),
}


def _normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _get_field(record: dict[str, Any], field: str):
    aliases = {
        _normalize_key(alias)
        for alias in FIELD_ALIASES[field]
    }

    for key, value in record.items():
        if _normalize_key(str(key)) in aliases:
            return value

    return None


def validate_doctors_json(raw: bytes) -> dict[str, Any]:
    """Parse and validate a JSON file without modifying the database."""

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

    doctors = []
    errors = []
    seen_names = set()

    for index, record in enumerate(payload):
        row_number = index + 1

        if not isinstance(record, dict):
            errors.append(
                f"Record {row_number}: expected a JSON object."
            )
            continue

        name = _get_field(record, "name")
        specialty = _get_field(record, "specialty")
        experience = _get_field(record, "experience")
        description = _get_field(record, "description")

        if not isinstance(name, str) or not name.strip():
            errors.append(
                f"Record {row_number}: a non-empty name is required."
            )
            continue

        if not isinstance(specialty, str) or not specialty.strip():
            errors.append(
                f"Record {row_number}: a non-empty specialty is required."
            )
            continue

        # Avoid accepting booleans as integers in Python.
        if isinstance(experience, bool):
            errors.append(
                f"Record {row_number}: experience must be a whole number."
            )
            continue

        try:
            numeric_experience = float(experience)
        except (TypeError, ValueError):
            errors.append(
                f"Record {row_number}: experience must be a number."
            )
            continue

        if (
            not numeric_experience.is_integer()
            or not 0 <= numeric_experience <= 100
        ):
            errors.append(
                f"Record {row_number}: experience must be a whole "
                "number between 0 and 100."
            )
            continue

        if description is not None and not isinstance(description, str):
            errors.append(
                f"Record {row_number}: description must be text."
            )
            continue

        clean_name = name.strip()
        clean_specialty = specialty.strip()
        name_key = clean_name.casefold()

        if name_key in seen_names:
            errors.append(
                f"Record {row_number}: duplicate doctor name "
                f"'{clean_name}' in the uploaded file."
            )
            continue

        seen_names.add(name_key)

        doctors.append(
            {
                "name": clean_name,
                "specialty": clean_specialty,
                "experience": int(numeric_experience),
                "description": (
                    description.strip()
                    if isinstance(description, str)
                    else ""
                ),
            }
        )

    return {
        "valid": not errors and bool(doctors),
        "doctors": doctors,
        "errors": errors,
    }


def import_doctors(doctors: list[dict[str, Any]]) -> dict[str, int]:
    """
    Insert new doctors and update existing doctors matched by
    case-insensitive name. Commit all changes in one transaction.
    """

    if not doctors:
        raise ValueError("There are no valid doctors to import.")

    db = SessionLocal()
    inserted = 0
    updated = 0

    try:
        for item in doctors:
            existing = (
                db.query(Doctor)
                .filter(
                    Doctor.name.ilike(item["name"])
                )
                .first()
            )

            if existing:
                existing.name = item["name"]
                existing.specialty = item["specialty"]
                existing.experience = item["experience"]
                existing.description = item["description"]
                updated += 1
            else:
                db.add(
                    Doctor(
                        name=item["name"],
                        specialty=item["specialty"],
                        experience=item["experience"],
                        description=item["description"],
                    )
                )
                inserted += 1

        db.commit()

        return {
            "inserted": inserted,
            "updated": updated,
            "total_processed": len(doctors),
        }

    except (SQLAlchemyError, Exception):
        db.rollback()
        raise

    finally:
        db.close()
