from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.database import init_db
from app.graph import build_graph


# ============================================================
# Graph
# ============================================================

graph = build_graph()


# ============================================================
# Application Lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize application resources on startup.
    """

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


# ============================================================
# Request Schemas
# ============================================================

class SchedulingRequest(BaseModel):
    """
    User message sent to the scheduling agent.
    """

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
    """
    Response returned by the scheduling agent.
    """

    thread_id: str

    response: str

    status: str

    trace: list[dict[str, Any]] = []


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

    available_slots: list[str] = []


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
# Schedule
# ============================================================

@app.post(
    "/api/v1/schedule",
    response_model=SchedulingResponse,
)
async def schedule(
    request: SchedulingRequest,
):

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
            response=result.get(
                "response",
                "",
            ),
            status=result.get(
                "status",
                "",
            ),
            trace=result.get(
                "trace",
                [],
            ),
        )

    except Exception as exc:

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
async def get_conversation_state(
    thread_id: str,
):

    try:

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        state_snapshot = graph.get_state(
            config
        )

        values = state_snapshot.values

        return ConversationStateResponse(
            thread_id=thread_id,
            status=values.get(
                "status",
                "",
            ),
            intent=values.get(
                "intent",
                "",
            ),
            patient_name=values.get(
                "patient_name",
                "",
            ),
            doctor_name=values.get(
                "doctor_name",
                "",
            ),
            specialty=values.get(
                "specialty",
                "",
            ),
            appointment_date=values.get(
                "appointment_date",
                "",
            ),
            appointment_time=values.get(
                "appointment_time",
                "",
            ),
            available_slots=values.get(
                "available_slots",
                [],
            ),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve conversation state."
            ),
        ) from exc


@app.get("/api/v1/conversations/{thread_id}/debug")
async def debug_conversation(thread_id: str):

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