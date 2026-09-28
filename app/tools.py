import csv
from datetime import datetime
from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.tools import FunctionTool, QueryEngineTool
from llama_index.readers.json import JSONReader


def build_doctor_index(json_path: str) -> VectorStoreIndex:
    """Build a vector index from the doctor directory."""

    documents = JSONReader().load_data(json_path)

    return VectorStoreIndex.from_documents(documents)


def schedule_appointment_tool(
    patient_name: str,
    doctor_name: str,
    preferred_time: str,
    csv_path: str = "data/doctor_appointment_requests.csv",
) -> str:
    """
    Record an appointment request.

    Note:
    This phase records the request only. It does not yet validate
    doctor availability or create a confirmed appointment.
    """

    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                datetime.utcnow().isoformat(),
                patient_name,
                doctor_name,
                preferred_time,
            ]
        )

    return (
        f"Appointment request recorded for {patient_name} "
        f"with {doctor_name} ({preferred_time})."
    )


def build_scheduling_tools(index: VectorStoreIndex):
    """Create the LlamaIndex tools used by the scheduling agent."""

    doctor_query_engine = index.as_query_engine()

    doctor_tool = QueryEngineTool.from_defaults(
        query_engine=doctor_query_engine,
        name="search_doctors",
        description=(
            "Search the doctor directory for doctors by specialty, "
            "name, experience, or related information."
        ),
    )

    appointment_tool = FunctionTool.from_defaults(
        fn=schedule_appointment_tool,
        name="schedule_appointment",
        description=(
            "Record an appointment request. "
            "Requires patient_name, doctor_name, and preferred_time."
        ),
    )

    return [
        doctor_tool,
        appointment_tool,
    ]