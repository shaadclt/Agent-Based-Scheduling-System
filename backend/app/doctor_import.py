"""Validation and transactional import for the doctor directory."""
import json
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.database import SessionLocal
from backend.app.models import Doctor

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_DOCTORS = 5000
FIELD_ALIASES = {
    "name": ("name",),
    "specialty": ("specialty", "speciality"),
    "experience": ("experience", "years of experience", "years_of_experience"),
    "description": ("description",),
}

def _normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())

def _get_field(record: dict[str, Any], field: str):
    aliases = {_normalize_key(alias) for alias in FIELD_ALIASES[field]}
    for key, value in record.items():
        if _normalize_key(str(key)) in aliases:
            return value
    return None

def validate_doctors_json(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {"valid": False, "doctors": [], "errors": ["The uploaded file is empty."]}
    if len(raw) > MAX_UPLOAD_BYTES:
        return {"valid": False, "doctors": [], "errors": ["The file exceeds the 2 MB upload limit."]}
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"valid": False, "doctors": [], "errors": ["The file must contain valid UTF-8 encoded JSON."]}
    if not isinstance(payload, list) or not payload:
        return {"valid": False, "doctors": [], "errors": ["The JSON root must be a non-empty array of doctors."]}
    if len(payload) > MAX_DOCTORS:
        return {"valid": False, "doctors": [], "errors": [f"A maximum of {MAX_DOCTORS} doctors is allowed."]}

    doctors, errors, seen_names = [], [], set()
    for index, record in enumerate(payload, start=1):
        if not isinstance(record, dict):
            errors.append(f"Record {index}: expected a JSON object.")
            continue
        name = _get_field(record, "name")
        specialty = _get_field(record, "specialty")
        experience = _get_field(record, "experience")
        description = _get_field(record, "description")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"Record {index}: a non-empty name is required.")
            continue
        if not isinstance(specialty, str) or not specialty.strip():
            errors.append(f"Record {index}: a non-empty specialty/speciality is required.")
            continue
        if isinstance(experience, bool):
            errors.append(f"Record {index}: experience must be a whole number between 0 and 100.")
            continue
        try:
            numeric_experience = float(experience)
        except (TypeError, ValueError):
            errors.append(f"Record {index}: experience must be a number between 0 and 100.")
            continue
        if not numeric_experience.is_integer() or not 0 <= numeric_experience <= 100:
            errors.append(f"Record {index}: experience must be a whole number between 0 and 100.")
            continue
        if description is not None and not isinstance(description, str):
            errors.append(f"Record {index}: description must be text.")
            continue
        clean_name = name.strip()
        name_key = clean_name.casefold()
        if name_key in seen_names:
            errors.append(f"Record {index}: duplicate doctor name '{clean_name}' in the uploaded file.")
            continue
        seen_names.add(name_key)
        doctors.append({
            "name": clean_name,
            "specialty": specialty.strip(),
            "experience": int(numeric_experience),
            "description": description.strip() if isinstance(description, str) else "",
        })
    return {"valid": not errors and bool(doctors), "doctors": doctors, "errors": errors}

def import_doctors(doctors: list[dict[str, Any]]) -> dict[str, int]:
    if not doctors:
        raise ValueError("There are no valid doctors to import.")
    db = SessionLocal()
    inserted = updated = 0
    try:
        for item in doctors:
            existing = db.query(Doctor).filter(Doctor.name.ilike(item["name"])).first()
            if existing:
                existing.name = item["name"]
                existing.specialty = item["specialty"]
                existing.experience = item["experience"]
                existing.description = item["description"]
                updated += 1
            else:
                db.add(Doctor(**item))
                inserted += 1
        db.commit()
        return {"inserted": inserted, "updated": updated, "total_processed": len(doctors)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def list_doctors() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        records = db.query(Doctor).order_by(Doctor.name.asc()).all()
        return [{
            "id": getattr(item, "id", None),
            "name": item.name,
            "specialty": item.specialty,
            "experience": item.experience,
            "description": getattr(item, "description", "") or "",
        } for item in records]
    finally:
        db.close()
