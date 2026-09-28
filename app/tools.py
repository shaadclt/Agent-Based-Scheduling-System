from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from llama_index.core import VectorStoreIndex
from llama_index.core.tools import FunctionTool
from llama_index.readers.json import JSONReader


# ============================================================
# Doctor Index
# ============================================================

def build_doctor_index(data_path: str) -> VectorStoreIndex:
    """
    Load doctor information from JSON and build a vector index.
    """

    documents = JSONReader().load_data(
        Path(data_path)
    )

    index = VectorStoreIndex.from_documents(
        documents
    )

    return index


# ============================================================
# Doctor Search
# ============================================================

def search_doctors(
    query: str,
    index: VectorStoreIndex,
) -> str:
    """
    Search the doctor database using the vector index.
    """

    query_engine = index.as_query_engine(
        similarity_top_k=5
    )

    response = query_engine.query(query)

    return str(response)


# ============================================================
# Appointment Scheduling
# ============================================================

def schedule_appointment(
    patient_name: str,
    doctor_name: str,
    appointment_time: str,
) -> str:
    """
    Record an appointment request.

    NOTE:
    This currently records the request rather than performing
    real availability checking. Phase 2 will replace this with
    proper availability and booking logic.
    """

    output_file = Path(
        "data/doctor_appointment_requests.csv"
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    appointment = {
        "timestamp": datetime.now().isoformat(),
        "patient_name": patient_name,
        "doctor_name": doctor_name,
        "appointment_time": appointment_time,
    }

    df = pd.DataFrame([appointment])

    if output_file.exists():

        df.to_csv(
            output_file,
            mode="a",
            header=False,
            index=False,
        )

    else:

        df.to_csv(
            output_file,
            index=False,
        )

    return (
        f"Appointment request recorded for "
        f"{patient_name} with {doctor_name} "
        f"at {appointment_time}."
    )


# ============================================================
# LlamaIndex Tools
# ============================================================

def create_search_doctors_tool(
    index: VectorStoreIndex,
) -> FunctionTool:
    """
    Create a LlamaIndex tool for doctor search.
    """

    def search(query: str) -> str:
        return search_doctors(
            query=query,
            index=index,
        )

    return FunctionTool.from_defaults(
        fn=search,
        name="search_doctors",
        description=(
            "Search the doctor database for doctors matching "
            "a specialty, condition, or other requirement. "
            "Use this tool when the patient needs help finding "
            "a suitable doctor."
        ),
    )


def create_schedule_appointment_tool() -> FunctionTool:
    """
    Create a LlamaIndex tool for appointment scheduling.
    """

    return FunctionTool.from_defaults(
        fn=schedule_appointment,
        name="schedule_appointment",
        description=(
            "Record an appointment request. "
            "Requires patient_name, doctor_name, and "
            "appointment_time."
        ),
    )