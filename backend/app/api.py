
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.database import init_db
from backend.app.graph import build_graph
from backend.app.doctor_import import (
    MAX_UPLOAD_BYTES,
    validate_doctors_json,
    import_doctors,
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
# Root
# ============================================================

@app.get(
    "/",
    response_model=HealthResponse,
)
async def root():
    return {
        "status": "ok",
        "service": "Healthcare Agent Scheduling System",
        "version": "1.0.0",
    }


# ============================================================
# Health Check
# ============================================================

@app.get(
    "/health",
    response_model=HealthResponse,
)
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
            {
                "query": request.query,
            },
            config=config,
        )

        return SchedulingResponse(
            thread_id=request.thread_id,
            response=result.get("response", ""),
            status=result.get("status", ""),
            trace=result.get("trace", []),
        )

    except Exception as exc:
        # Keep the detailed exception in the server logs.
        print(f"Scheduling request failed: {exc}")

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
        print(f"Unable to retrieve conversation state: {exc}")

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
        print(f"Unable to retrieve conversation debug state: {exc}")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve conversation debug state.",
        ) from exc


# ============================================================
# Admin: Doctor JSON Import Helpers
# ============================================================

async def _read_and_validate_doctor_file(file: UploadFile):
    """Read and validate an uploaded doctor JSON file."""

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a .json file.",
        )

    raw = await file.read(MAX_UPLOAD_BYTES + 1)

    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The upload exceeds the 2 MB limit.",
        )

    result = validate_doctors_json(raw)

    return result


# ============================================================
# Admin: Preview Doctor JSON
# ============================================================

@app.post("/api/v1/admin/doctors/preview")
async def preview_doctors_json(file: UploadFile = File(...)):
    """
    Validate the uploaded JSON and return a preview.
    This endpoint does not modify the database.
    """

    result = await _read_and_validate_doctor_file(file)

    return {
        "valid": result["valid"],
        "count": len(result["doctors"]),
        "doctors": result["doctors"],
        "errors": result["errors"],
    }


# ============================================================
# Admin: Initialize / Import Doctors
# ============================================================

@app.post("/api/v1/admin/doctors/initialize")
async def initialize_doctors_database(
    file: UploadFile = File(...),
):
    """
    Validate and import doctor records into the database.

    Existing matching doctors are updated by the import service.
    Doctors absent from the uploaded file are not automatically deleted.
    """

    result = await _read_and_validate_doctor_file(file)

    if not result["valid"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The JSON file failed validation.",
                "errors": result["errors"],
            },
        )

    try:
        summary = import_doctors(result["doctors"])

    except Exception as exc:
        print(f"Doctor import failed: {exc}")

        raise HTTPException(
            status_code=500,
            detail=(
                "Doctor import failed. Check the backend logs "
                "for details."
            ),
        ) from exc

    return {
        "success": True,
        "message": "Doctor records imported successfully.",
        **summary,
    }
