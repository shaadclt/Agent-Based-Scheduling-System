from typing import Any, TypedDict


class SchedulingState(TypedDict, total=False):
    # Original user request
    query: str

    # Conversation
    messages: list

    # Patient information
    patient_name: str

    # Request understanding
    intent: str
    specialty: str

    # Doctor information
    doctor_name: str

    # Appointment information
    appointment_date: str
    appointment_time: str

    # Availability
    available_slots: list

    # Workflow control
    status: str

    # Tool results
    doctor_results: Any
    availability_result: Any
    booking_result: Any

    # Final response
    response: str

    # Debugging / observability
    trace: list