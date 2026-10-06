from typing import Any, TypedDict


class SchedulingState(TypedDict, total=False):
    # Current user request
    query: str

    # Conversation
    messages: list

    # Patient information
    patient_name: str

    # Scheduling information
    specialty: str
    doctor_name: str
    appointment_date: str
    appointment_time: str

    # Agent state
    intent: str
    status: str

    # Tool results
    doctor_results: Any
    availability_result: Any
    booking_result: Any

    # Agent response
    response: str

    # Observability
    trace: list