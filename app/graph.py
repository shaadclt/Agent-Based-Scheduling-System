from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.config import setup_llm
from app.state import SchedulingState
from app.tools import (
    book_appointment,
    check_availability,
    search_doctors,
)


# ============================================================
# LLM
# ============================================================

llm = setup_llm()


# ============================================================
# Helper
# ============================================================


def add_trace(
    state: SchedulingState,
    node: str,
    details: str,
) -> list:

    trace = state.get("trace", []).copy()

    trace.append(
        {
            "node": node,
            "details": details,
        }
    )

    return trace


# ============================================================
# 1. Analyze Request
# ============================================================


def analyze_request(
    state: SchedulingState,
) -> SchedulingState:

    query = state["query"]

    prompt = f"""
You are a healthcare scheduling assistant.

Analyze the user's request and extract the following information.

User request:
{query}

Return ONLY valid JSON with these fields:

{{
    "intent": "doctor_search | appointment_booking | general",
    "specialty": "medical specialty or empty string",
    "doctor_name": "doctor name or empty string",
    "patient_name": "patient name or empty string",
    "appointment_date": "YYYY-MM-DD or empty string",
    "appointment_time": "HH:MM or empty string"
}}
"""

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You extract structured information "
                    "from healthcare scheduling requests."
                )
            ),
            HumanMessage(
                content=prompt
            ),
        ]
    )

    import json

    content = response.content

    try:

        data = json.loads(content)

    except json.JSONDecodeError:

        # Try to extract JSON if the model added extra text
        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end == -1:

            return {
                **state,
                "intent": "general",
                "status": "analysis_failed",
                "response": (
                    "I couldn't understand the request. "
                    "Could you please provide more details?"
                ),
                "trace": add_trace(
                    state,
                    "analyze_request",
                    "Failed to parse model output.",
                ),
            }

        data = json.loads(
            content[start : end + 1]
        )

    return {
        **state,
        "intent": data.get(
            "intent",
            "general",
        ),
        "specialty": data.get(
            "specialty",
            "",
        ),
        "doctor_name": data.get(
            "doctor_name",
            "",
        ),
        "patient_name": data.get(
            "patient_name",
            "",
        ),
        "appointment_date": data.get(
            "appointment_date",
            "",
        ),
        "appointment_time": data.get(
            "appointment_time",
            "",
        ),
        "status": "request_analyzed",
        "trace": add_trace(
            state,
            "analyze_request",
            (
                f"Intent: {data.get('intent', '')}, "
                f"Specialty: {data.get('specialty', '')}, "
                f"Doctor: {data.get('doctor_name', '')}"
            ),
        ),
    }


# ============================================================
# 2. Route Request
# ============================================================


def route_request(
    state: SchedulingState,
) -> Literal[
    "search_doctors",
    "check_availability",
    "general_response",
]:

    intent = state.get(
        "intent",
        "general",
    )

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    specialty = state.get(
        "specialty",
        "",
    )

    if doctor_name:
        return "check_availability"

    if specialty:
        return "search_doctors"

    if intent == "doctor_search":
        return "search_doctors"

    return "general_response"


# ============================================================
# 3. Search Doctors
# ============================================================


def search_doctors_node(
    state: SchedulingState,
) -> SchedulingState:

    specialty = state.get(
        "specialty",
        "",
    )

    query = state.get(
        "query",
        "",
    )

    result = search_doctors.invoke(
        {
            "specialty": specialty or None,
            "query": query,
        }
    )

    return {
        **state,
        "doctor_results": result,
        "status": "doctors_found",
        "response": result,
        "trace": add_trace(
            state,
            "search_doctors",
            f"Doctor search completed for: {specialty or query}",
        ),
    }


# ============================================================
# 4. Check Availability
# ============================================================


def check_availability_node(
    state: SchedulingState,
) -> SchedulingState:

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    appointment_date = state.get(
        "appointment_date",
        "",
    )

    # --------------------------------------------------------
    # Missing information
    # --------------------------------------------------------

    if not doctor_name:

        return {
            **state,
            "status": "missing_doctor",
            "response": (
                "Which doctor would you like to book "
                "an appointment with?"
            ),
            "trace": add_trace(
                state,
                "check_availability",
                "Doctor name missing.",
            ),
        }

    if not appointment_date:

        return {
            **state,
            "status": "missing_date",
            "response": (
                f"What date would you like to see "
                f"{doctor_name}?"
            ),
            "trace": add_trace(
                state,
                "check_availability",
                "Appointment date missing.",
            ),
        }

    result = check_availability.invoke(
        {
            "doctor_name": doctor_name,
            "appointment_date": appointment_date,
        }
    )

    return {
        **state,
        "availability_result": result,
        "status": "availability_checked",
        "trace": add_trace(
            state,
            "check_availability",
            (
                f"Checked availability for "
                f"{doctor_name} on {appointment_date}."
            ),
        ),
    }


# ============================================================
# 5. Route Availability
# ============================================================


def route_availability(
    state: SchedulingState,
) -> Literal[
    "book_appointment",
    "ask_for_slot",
    "finish",
]:

    if state.get("status") == "missing_doctor":
        return "finish"

    if state.get("status") == "missing_date":
        return "finish"

    appointment_time = state.get(
        "appointment_time",
        "",
    )

    if appointment_time:
        return "book_appointment"

    return "ask_for_slot"


# ============================================================
# 6. Ask For Slot
# ============================================================


def ask_for_slot(
    state: SchedulingState,
) -> SchedulingState:

    return {
        **state,
        "status": "waiting_for_slot",
        "response": (
            f"Available appointment slots for "
            f"{state.get('doctor_name')} on "
            f"{state.get('appointment_date')}:\n\n"
            f"{state.get('availability_result')}\n\n"
            "Please choose one of the available times."
        ),
        "trace": add_trace(
            state,
            "ask_for_slot",
            "Waiting for the patient to select an appointment slot.",
        ),
    }


# ============================================================
# 7. Book Appointment
# ============================================================


def book_appointment_node(
    state: SchedulingState,
) -> SchedulingState:

    patient_name = state.get(
        "patient_name",
        "",
    )

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    appointment_date = state.get(
        "appointment_date",
        "",
    )

    appointment_time = state.get(
        "appointment_time",
        "",
    )

    # --------------------------------------------------------
    # Patient name required
    # --------------------------------------------------------

    if not patient_name:

        return {
            **state,
            "status": "missing_patient_name",
            "response": (
                "What is the patient's name?"
            ),
            "trace": add_trace(
                state,
                "book_appointment",
                "Patient name missing.",
            ),
        }

    # --------------------------------------------------------
    # Book
    # --------------------------------------------------------

    result = book_appointment.invoke(
        {
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
        }
    )

    return {
        **state,
        "booking_result": result,
        "status": "appointment_booked",
        "response": result,
        "trace": add_trace(
            state,
            "book_appointment",
            (
                f"Appointment booking attempted for "
                f"{patient_name} with {doctor_name}."
            ),
        ),
    }


# ============================================================
# 8. General Response
# ============================================================


def general_response(
    state: SchedulingState,
) -> SchedulingState:

    query = state.get(
        "query",
        "",
    )

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a healthcare scheduling assistant. "
                    "Respond helpfully to the user's request. "
                    "If the request is unrelated to scheduling, "
                    "explain that you specialize in healthcare "
                    "appointment assistance."
                )
            ),
            HumanMessage(
                content=query
            ),
        ]
    )

    return {
        **state,
        "status": "completed",
        "response": response.content,
        "trace": add_trace(
            state,
            "general_response",
            "Generated a general response.",
        ),
    }


# ============================================================
# 9. Build Graph
# ============================================================


def build_graph():

    workflow = StateGraph(
        SchedulingState
    )

    # --------------------------------------------------------
    # Nodes
    # --------------------------------------------------------

    workflow.add_node(
        "analyze_request",
        analyze_request,
    )

    workflow.add_node(
        "search_doctors",
        search_doctors_node,
    )

    workflow.add_node(
        "check_availability",
        check_availability_node,
    )

    workflow.add_node(
        "ask_for_slot",
        ask_for_slot,
    )

    workflow.add_node(
        "book_appointment",
        book_appointment_node,
    )

    workflow.add_node(
        "general_response",
        general_response,
    )

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    workflow.add_edge(
        START,
        "analyze_request",
    )

    # --------------------------------------------------------
    # Request routing
    # --------------------------------------------------------

    workflow.add_conditional_edges(
        "analyze_request",
        route_request,
        {
            "search_doctors": "search_doctors",
            "check_availability": "check_availability",
            "general_response": "general_response",
        },
    )

    # --------------------------------------------------------
    # Doctor search
    # --------------------------------------------------------

    workflow.add_edge(
        "search_doctors",
        END,
    )

    # --------------------------------------------------------
    # Availability
    # --------------------------------------------------------

    workflow.add_conditional_edges(
        "check_availability",
        route_availability,
        {
            "book_appointment": "book_appointment",
            "ask_for_slot": "ask_for_slot",
            "finish": END,
        },
    )

    # --------------------------------------------------------
    # Ask for slot
    # --------------------------------------------------------

    workflow.add_edge(
        "ask_for_slot",
        END,
    )

    # --------------------------------------------------------
    # Booking
    # --------------------------------------------------------

    workflow.add_edge(
        "book_appointment",
        END,
    )

    # --------------------------------------------------------
    # General response
    # --------------------------------------------------------

    workflow.add_edge(
        "general_response",
        END,
    )

    return workflow.compile()