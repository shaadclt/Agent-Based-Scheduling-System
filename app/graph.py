import json
from datetime import datetime

from app.checkpointer import checkpointer
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


# Active appointment states are the states in which a follow-up
# message such as a date, time, or patient name should continue
# the existing booking workflow.
ACTIVE_APPOINTMENT_STATES = {
    "waiting_for_doctor",
    "waiting_for_date",
    "waiting_for_time",
    "waiting_for_patient_name",
    "availability_checked",
    "availability_error",
}


# ============================================================
# Trace
# ============================================================

def add_trace(
    state: SchedulingState,
    node: str,
    details: str = "",
):
    trace = state.get("trace", [])

    trace.append(
        {
            "node": node,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details,
        }
    )

    state["trace"] = trace

    return state


# ============================================================
# Analyze Request
# ============================================================

def analyze_request(
    state: SchedulingState,
) -> SchedulingState:

    query = state.get("query", "").strip()

    current_state = {
        "status": state.get("status", ""),
        "intent": state.get("intent", ""),
        "doctor_name": state.get("doctor_name", ""),
        "specialty": state.get("specialty", ""),
        "patient_name": state.get("patient_name", ""),
        "appointment_date": state.get("appointment_date", ""),
        "appointment_time": state.get("appointment_time", ""),
    }

    prompt = f"""
You are the intent extraction component of a healthcare
appointment scheduling system.

Current workflow state:

{json.dumps(current_state, indent=2)}

New user message:

{query}

Classify the CURRENT user message first.

Return ONLY valid JSON:

{{
    "intent": "doctor_search | appointment_booking | general",
    "specialty": "",
    "doctor_name": "",
    "patient_name": "",
    "appointment_date": "",
    "appointment_time": ""
}}

Rules:

1. A request to find, list, browse, or search for doctors is
   doctor_search.

2. A request to book or schedule an appointment is
   appointment_booking.

3. If the current workflow is an active appointment workflow,
   a follow-up containing only a date, time, or patient name
   must be appointment_booking.

4. An explicit doctor-search request takes priority over an
   older appointment workflow. For example, if the old state
   is waiting_for_time and the user says "Can you list the
   doctors available?", classify it as doctor_search.

5. Do not invent missing information.

6. Date format: YYYY-MM-DD

7. Time format: HH:MM

8. Return empty strings for fields not present in the current
   user message.
"""

    try:
        response = llm.invoke(prompt)

        content = response.content

        if isinstance(content, list):
            content = "".join(str(item) for item in content)

        content = str(content).strip()

        if content.startswith("```"):
            content = content.replace("```json", "", 1)
            content = content.replace("```", "")
            content = content.strip()

        parsed = json.loads(content)

    except Exception:
        parsed = {
            "intent": "",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        }

    parsed_intent = parsed.get("intent", "")
    existing_status = state.get("status", "")
    active_appointment = existing_status in ACTIVE_APPOINTMENT_STATES

    # --------------------------------------------------------
    # Explicit doctor search starts a search context.
    # Clear old booking-specific entities so an old appointment
    # cannot leak into the new request.
    # --------------------------------------------------------
    if parsed_intent == "doctor_search":
        state["intent"] = "doctor_search"
        state["specialty"] = parsed.get("specialty", "") or ""
        state["doctor_name"] = parsed.get("doctor_name", "") or ""
        state["patient_name"] = ""
        state["appointment_date"] = ""
        state["appointment_time"] = ""
        state["available_slots"] = []

    # --------------------------------------------------------
    # Appointment request. Preserve previous entities only when
    # the conversation is already in an active booking workflow.
    # A new booking request starts cleanly.
    # --------------------------------------------------------
    elif parsed_intent == "appointment_booking":
        if not active_appointment:
            state["doctor_name"] = ""
            state["specialty"] = ""
            state["patient_name"] = ""
            state["appointment_date"] = ""
            state["appointment_time"] = ""
            state["available_slots"] = []

        state["intent"] = "appointment_booking"

        if parsed.get("specialty"):
            state["specialty"] = parsed["specialty"]

        if parsed.get("doctor_name"):
            state["doctor_name"] = parsed["doctor_name"]

        if parsed.get("patient_name"):
            state["patient_name"] = parsed["patient_name"]

        if parsed.get("appointment_date"):
            state["appointment_date"] = parsed["appointment_date"]

        if parsed.get("appointment_time"):
            state["appointment_time"] = parsed["appointment_time"]

    # --------------------------------------------------------
    # General request. Do not allow an old appointment context
    # to control an unrelated request.
    # --------------------------------------------------------
    elif parsed_intent == "general":
        state["intent"] = "general"

    # --------------------------------------------------------
    # If the LLM failed to classify the message but the workflow
    # is active, retain the appointment context.
    # --------------------------------------------------------
    elif active_appointment:
        state["intent"] = "appointment_booking"

    add_trace(
        state,
        "analyze_request",
        json.dumps(parsed),
    )

    return state


# ============================================================
# Router
# ============================================================

def route_request(
    state: SchedulingState,
):

    intent = state.get(
        "intent",
        "general",
    )

    status = state.get(
        "status",
        "",
    )

    # Explicit doctor search always wins over a stale booking
    # status. This is the key fix for the previous screenshot.
    if intent == "doctor_search":
        return "search_doctors"

    # Continue an active appointment conversation.
    if status in ACTIVE_APPOINTMENT_STATES:
        return "check_availability"

    if intent == "appointment_booking":
        return "check_availability"

    return "general_response"


# ============================================================
# Doctor Search
# ============================================================

def search_doctors_node(
    state: SchedulingState,
) -> SchedulingState:

    specialty = state.get(
        "specialty",
        "",
    )

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    # The tool returns all doctors when both values are empty.
    # Do not pass the natural-language request such as
    # "Can you list the doctors available?" as a name query.
    result = search_doctors.invoke(
        {
            "specialty": specialty,
            "query": doctor_name,
        }
    )

    state["doctor_results"] = result

    try:
        parsed = json.loads(result)

        if parsed.get("status") == "success":
            doctors = parsed.get(
                "doctors",
                [],
            )

            if specialty:
                heading = (
                    f"Doctors available for {specialty}:"
                )
            else:
                heading = (
                    "Here are the doctors currently available:"
                )

            lines = [heading, ""]

            for doctor in doctors:
                lines.append(
                    f"• {doctor.get('name')} — "
                    f"{doctor.get('specialty')} "
                    f"({doctor.get('experience')} years experience)"
                )

            state["response"] = "\n".join(lines)

        else:
            state["response"] = parsed.get(
                "message",
                "No doctors were found.",
            )

    except Exception:
        state["response"] = str(result)

    state["status"] = "doctor_search_completed"

    add_trace(
        state,
        "search_doctors",
        "Doctor search completed",
    )

    return state


# ============================================================
# Availability / Scheduling
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

    appointment_time = state.get(
        "appointment_time",
        "",
    )

    # --------------------------------------------------------
    # Doctor missing
    # --------------------------------------------------------

    if not doctor_name:

        state["status"] = (
            "waiting_for_doctor"
        )

        state["response"] = (
            "Which doctor would you like "
            "to book an appointment with?"
        )

        add_trace(
            state,
            "check_availability",
            "Waiting for doctor",
        )

        return state

    # --------------------------------------------------------
    # Date missing
    # --------------------------------------------------------

    if not appointment_date:

        state["status"] = (
            "waiting_for_date"
        )

        clean_name = (
            doctor_name
            .replace("Dr. ", "")
            .replace("Dr ", "")
        )

        state["response"] = (
            f"What date would you like to see "
            f"{clean_name}?"
        )

        add_trace(
            state,
            "check_availability",
            "Waiting for appointment date",
        )

        return state

    # --------------------------------------------------------
    # Check SQLite availability
    # --------------------------------------------------------

    result = check_availability.invoke(
        {
            "doctor_name": doctor_name,
            "appointment_date": appointment_date,
        }
    )

    state["availability_result"] = result

    try:

        parsed = json.loads(result)

    except Exception:

        state["status"] = (
            "availability_error"
        )

        state["response"] = str(result)

        return state

    if parsed.get("status") != "success":

        state["status"] = (
            "availability_error"
        )

        state["response"] = parsed.get(
            "message",
            "Unable to check availability.",
        )

        return state

    available_slots = parsed.get(
        "available_slots",
        [],
    )

    state["available_slots"] = (
        available_slots
    )

    # --------------------------------------------------------
    # No slots
    # --------------------------------------------------------

    if not available_slots:

        state["status"] = (
            "availability_checked"
        )

        state["response"] = (
            f"No appointment slots are available "
            f"for {doctor_name} on "
            f"{appointment_date}."
        )

        return state

    # --------------------------------------------------------
    # User already selected a time
    # --------------------------------------------------------

    if appointment_time:

        if appointment_time in available_slots:

            # Continue to patient name
            if not state.get(
                "patient_name",
                "",
            ):

                state["status"] = (
                    "waiting_for_patient_name"
                )

                state["response"] = (
                    "May I have the patient's name?"
                )

                add_trace(
                    state,
                    "check_availability",
                    "Time available; waiting for patient",
                )

                return state

            # Patient already known -> book
            return book_appointment_node(
                state
            )

        state["status"] = (
            "waiting_for_time"
        )

        state["response"] = (
            f"{appointment_time} is not available.\n\n"
            f"Available times for "
            f"{doctor_name} on "
            f"{appointment_date} are:\n\n"
            +
            "\n".join(
                f"• {slot}"
                for slot in available_slots
            )
        )

        add_trace(
            state,
            "check_availability",
            "Requested time unavailable",
        )

        return state

    # --------------------------------------------------------
    # Ask for time
    # --------------------------------------------------------

    state["status"] = (
        "waiting_for_time"
    )

    state["response"] = (
        f"Available times for "
        f"{doctor_name} on "
        f"{appointment_date} are:\n\n"
        +
        "\n".join(
            f"• {slot}"
            for slot in available_slots
        )
        +
        "\n\nWhich time would you prefer?"
    )

    add_trace(
        state,
        "check_availability",
        "Availability retrieved",
    )

    return state


# ============================================================
# Book Appointment
# ============================================================

def book_appointment_node(
    state: SchedulingState,
) -> SchedulingState:

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    patient_name = state.get(
        "patient_name",
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
    # Required information
    # --------------------------------------------------------

    if not doctor_name:

        state["status"] = (
            "waiting_for_doctor"
        )

        state["response"] = (
            "Which doctor would you like "
            "to book an appointment with?"
        )

        return state

    if not appointment_date:

        state["status"] = (
            "waiting_for_date"
        )

        state["response"] = (
            "What date would you like "
            "the appointment?"
        )

        return state

    if not appointment_time:

        state["status"] = (
            "waiting_for_time"
        )

        state["response"] = (
            "Which appointment time would "
            "you prefer?"
        )

        return state

    if not patient_name:

        state["status"] = (
            "waiting_for_patient_name"
        )

        state["response"] = (
            "May I have the patient's name?"
        )

        return state

    # --------------------------------------------------------
    # Book through SQLite tool
    # --------------------------------------------------------

    result = book_appointment.invoke(
        {
            "doctor_name": doctor_name,
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
        }
    )

    state["booking_result"] = result

    try:

        parsed = json.loads(result)

    except Exception:

        state["status"] = (
            "booking_error"
        )

        state["response"] = str(result)

        return state

    if parsed.get("status") == "success":

        appointment = parsed.get(
            "appointment",
            {},
        )

        state["status"] = (
            "booking_completed"
        )

        state["response"] = (
            "Appointment booked successfully!\n\n"
            f"Patient: "
            f"{appointment.get('patient_name')}\n"
            f"Doctor: "
            f"{appointment.get('doctor_name')}\n"
            f"Specialty: "
            f"{appointment.get('specialty')}\n"
            f"Date: "
            f"{appointment.get('date')}\n"
            f"Time: "
            f"{appointment.get('time')}\n"
            f"Status: "
            f"{appointment.get('status')}"
        )

    else:

        state["status"] = (
            "booking_error"
        )

        state["response"] = parsed.get(
            "message",
            "Unable to book the appointment.",
        )

    add_trace(
        state,
        "book_appointment",
        "Appointment booking completed",
    )

    return state


# ============================================================
# General Response
# ============================================================

def general_response(
    state: SchedulingState,
) -> SchedulingState:

    query = state.get(
        "query",
        "",
    )

    prompt = f"""
You are a healthcare appointment scheduling assistant.

User message:
{query}

You can help with:

- finding doctors
- medical specialties
- checking appointment availability
- booking appointments

Do not diagnose medical conditions or provide treatment advice.

If the request is unrelated to scheduling,
politely explain what you can help with.
"""

    response = llm.invoke(
        prompt
    )

    content = response.content

    if isinstance(content, list):

        content = "".join(
            str(item)
            for item in content
        )

    state["response"] = (
        str(content).strip()
    )

    state["status"] = (
        "general_response"
    )

    add_trace(
        state,
        "general_response",
        "General response generated",
    )

    return state


# ============================================================
# Graph
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
        "book_appointment",
        book_appointment_node,
    )

    workflow.add_node(
        "general_response",
        general_response,
    )

    # --------------------------------------------------------
    # Start
    # --------------------------------------------------------

    workflow.add_edge(
        START,
        "analyze_request",
    )

    # --------------------------------------------------------
    # Initial routing
    # --------------------------------------------------------

    workflow.add_conditional_edges(
        "analyze_request",
        route_request,
        {
            "search_doctors":
                "search_doctors",

            "check_availability":
                "check_availability",

            "general_response":
                "general_response",
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
    # Availability routing
    # --------------------------------------------------------

    def availability_router(
        state: SchedulingState,
    ):

        status = state.get(
            "status",
            "",
        )

        if status == "booking_completed":
            return "end"

        if status == "waiting_for_patient_name":
            return "end"

        if status == "waiting_for_time":
            return "end"

        if status == "waiting_for_date":
            return "end"

        if status == "waiting_for_doctor":
            return "end"

        if status == "availability_error":
            return "end"

        return "end"

    workflow.add_conditional_edges(
        "check_availability",
        availability_router,
        {
            "end": END,
        },
    )

    # --------------------------------------------------------
    # Booking
    # --------------------------------------------------------

    workflow.add_edge(
        "book_appointment",
        END,
    )

    # --------------------------------------------------------
    # General
    # --------------------------------------------------------

    workflow.add_edge(
        "general_response",
        END,
    )

    # --------------------------------------------------------
    # Checkpointing
    # --------------------------------------------------------

    return workflow.compile(
    checkpointer=checkpointer,
)