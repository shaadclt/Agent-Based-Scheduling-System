"""FastAPI application for healthcare appointment scheduling."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.database import init_db
from backend.app.graph import build_graph
from backend.app.doctor_import import (
    MAX_UPLOAD_BYTES,
    import_doctors,
    list_doctors,
    validate_doctors_json,
)


# ============================================================
# Graph
# ============================================================

graph = build_graph()


# ============================================================
# Application Lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application resources on startup."""
    init_db()
    yield


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="Healthcare Agent Scheduling System",
    description=(
        "Agentic healthcare scheduling system built with "
        "LangChain, LangGraph, FastAPI and SQLite."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Request Schemas
# ============================================================

class SchedulingRequest(BaseModel):
    """User message sent to the scheduling agent."""

    query: str = Field(
        ...,
        min_length=1,
        description="User's scheduling request.",
        examples=[
            "I want an appointment with Dr. Michael Brown"
        ],
    )

    thread_id: str = Field(
        default="default",
        min_length=1,
        description="Conversation identifier.",
        examples=["patient-001"],
    )


# ============================================================
# Response Schemas
# ============================================================

class SchedulingResponse(BaseModel):
    """Response returned by the scheduling agent."""

    thread_id: str
    response: str
    status: str
    trace: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ConversationStateResponse(BaseModel):
    thread_id: str
    status: str = ""
    intent: str = ""
    patient_name: str = ""
    doctor_name: str = ""
    specialty: str = ""
    appointment_date: str = ""
    appointment_time: str = ""
    available_slots: list[str] = Field(default_factory=list)


# ============================================================
# Root and Health Check
# ============================================================

@app.get("/", response_model=HealthResponse)
async def root():
    return {
        "status": "ok",
        "service": "Healthcare Agent Scheduling System",
        "version": "1.0.0",
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    return {
        "status": "healthy",
        "service": "Healthcare Agent Scheduling System",
        "version": "1.0.0",
    }


# ============================================================
# Schedule Appointment
# ============================================================

@app.post(
    "/api/v1/schedule",
    response_model=SchedulingResponse,
)
async def schedule(request: SchedulingRequest):
    try:
        config = {
            "configurable": {
                "thread_id": request.thread_id,
            }
        }

        result = graph.invoke(
            {"query": request.query},
            config=config,
        )

        return SchedulingResponse(
            thread_id=request.thread_id,
            response=result.get("response", ""),
            status=result.get("status", ""),
            trace=result.get("trace", []),
        )

    except Exception as exc:
        # Keep internal exception details out of the API response.
        raise HTTPException(
            status_code=500,
            detail=(
                "An error occurred while processing "
                "the scheduling request."
            ),
        ) from exc


# ============================================================
# Conversation State
# ============================================================

@app.get(
    "/api/v1/conversations/{thread_id}",
    response_model=ConversationStateResponse,
)
async def get_conversation_state(thread_id: str):
    try:
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        state_snapshot = graph.get_state(config)
        values = state_snapshot.values

        return ConversationStateResponse(
            thread_id=thread_id,
            status=values.get("status", ""),
            intent=values.get("intent", ""),
            patient_name=values.get("patient_name", ""),
            doctor_name=values.get("doctor_name", ""),
            specialty=values.get("specialty", ""),
            appointment_date=values.get("appointment_date", ""),
            appointment_time=values.get("appointment_time", ""),
            available_slots=values.get("available_slots", []),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve conversation state.",
        ) from exc


@app.get("/api/v1/conversations/{thread_id}/debug")
async def debug_conversation(thread_id: str):
    try:
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        snapshot = graph.get_state(config)

        return {
            "thread_id": thread_id,
            "state": snapshot.values,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve conversation debug state.",
        ) from exc


# ============================================================
# Admin: Doctor JSON Validation
# ============================================================

async def _read_and_validate_doctor_file(
    file: UploadFile,
) -> dict[str, Any]:
    """Read and validate an uploaded doctor JSON file."""

    if (
        not file.filename
        or not file.filename.lower().endswith(".json")
    ):
        raise HTTPException(
            status_code=400,
            detail="Please upload a .json file.",
        )

    try:
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()

    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The upload exceeds the 2 MB limit.",
        )

    result = validate_doctors_json(raw)

    if not result["valid"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "The doctor JSON file contains validation errors."
                ),
                "errors": result["errors"],
            },
        )

    return result


# ============================================================
# Admin: Preview Doctor Import
# ============================================================

@app.post("/api/v1/admin/doctors/preview")
async def preview_doctors(file: UploadFile = File(...)):
    result = await _read_and_validate_doctor_file(file)
    doctors = result["doctors"]

    specialties = sorted(
        {doctor["specialty"] for doctor in doctors}
    )

    return {
        "valid": True,
        "total_doctors": len(doctors),
        "total_specialties": len(specialties),
        "specialties": specialties,
        "doctors": doctors[:100],
        "preview_truncated": len(doctors) > 100,
        "errors": [],
    }


# ============================================================
# Admin: Initialize Doctor Directory
# ============================================================

@app.post("/api/v1/admin/doctors/initialize")
async def initialize_doctors(file: UploadFile = File(...)):
    result = await _read_and_validate_doctor_file(file)

    try:
        import_result = import_doctors(result["doctors"])
        current_doctors = list_doctors()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Doctor import failed. "
                "The database transaction was rolled back."
            ),
        ) from exc

    specialties = {
        doctor["specialty"]
        for doctor in current_doctors
        if doctor.get("specialty")
    }

    return {
        "message": "Doctor directory initialized successfully.",
        **import_result,
        "total_doctors": len(current_doctors),
        "total_specialties": len(specialties),
    }


# ============================================================
# Admin: List Doctors
# ============================================================

@app.get("/api/v1/admin/doctors")
async def get_doctors():
    doctors = list_doctors()

    return {
        "doctors": doctors,
        "total_doctors": len(doctors),
    }


# ============================================================
# Admin: Doctor Summary
# ============================================================

@app.get("/api/v1/admin/doctors/summary")
async def get_doctor_summary():
    doctors = list_doctors()

    specialties = {
        doctor["specialty"]
        for doctor in doctors
        if doctor.get("specialty")
    }

    return {
        "total_doctors": len(doctors),
        "total_specialties": len(specialties),
    }