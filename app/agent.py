from app.config import setup_models
from app.memory import ConversationMemory
from app.tools import (
    build_doctor_index,
    create_search_doctors_tool,
    create_schedule_appointment_tool,
)
from app.workflow import SchedulingWorkflow
from app.traces import AgentTraceLogger
from app.evaluation import AgentEvaluator


def create_agent(data_path: str):

    # ------------------------------------------------------------
    # Setup LLM
    # ------------------------------------------------------------

    llm = setup_models()

    # ------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------

    memory = ConversationMemory()

    # ------------------------------------------------------------
    # Tracing
    # ------------------------------------------------------------

    tracer = AgentTraceLogger()

    # ------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------

    evaluator = AgentEvaluator()

    # ------------------------------------------------------------
    # Doctor index
    # ------------------------------------------------------------

    index = build_doctor_index(
        data_path
    )

    # ------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------

    search_tool = create_search_doctors_tool(
        index
    )

    schedule_tool = create_schedule_appointment_tool()

    tools = [
        search_tool,
        schedule_tool,
    ]

    # ------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------

    workflow = SchedulingWorkflow(
        memory=memory,
        index=index,
        tracer=tracer,
        evaluator=evaluator,
        llm=llm,
        tools=tools,
    )

    return workflow, tracer