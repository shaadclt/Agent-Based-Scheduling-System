from fastapi import FastAPI
from pydantic import BaseModel

from app.graph import build_graph


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="Healthcare Agent Scheduling API",
    version="1.0.0",
)


# ============================================================
# Graph
# ============================================================

graph = build_graph()


# ============================================================
# Request Model
# ============================================================

class SchedulingRequest(BaseModel):
    query: str
    thread_id: str = "default"


# ============================================================
# Health Check
# ============================================================

@app.get("/")
def root():

    return {
        "status": "ok",
        "service": "Healthcare Agent Scheduling System",
    }


# ============================================================
# Scheduling Endpoint
# ============================================================

@app.post("/schedule")
async def schedule(
    request: SchedulingRequest,
):

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

    return {
        "response": result.get(
            "response",
            "",
        ),
        "status": result.get(
            "status",
            "",
        ),
        "trace": result.get(
            "trace",
            [],
        ),
    }