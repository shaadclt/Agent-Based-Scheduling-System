from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.agent import create_agent


app = FastAPI(
    title="Agent-Based Scheduling System",
    description=(
        "Event-driven healthcare scheduling agent "
        "using LlamaIndex and ReAct."
    ),
    version="1.0.0",
)


class AgentRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Natural-language scheduling request.",
    )


class AgentResponse(BaseModel):
    output: str
    traces: list
    evaluation: dict


@app.post(
    "/run",
    response_model=AgentResponse,
)
async def run_agent(
    request: AgentRequest,
):

    agent, tracer = create_agent(
        "data/doctors.json"
    )

    result = await agent.run(
        request.query
    )

    return {
        "output": result["response"],
        "traces": tracer.get_traces(),
        "evaluation": result["evaluation"],
    }