import json
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver
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
        "appointment_date": state.get(
            "appointment_date",
            "",
        ),
        "appointment_time": state.get(
            "appointment_time",
            "",
        ),
    }

    prompt = f"""
You are the intent extraction component of a healthcare
appointment scheduling system.

Current workflow state:

{json.dumps(current_state, indent=2)}

New user message:

{query}

Extract information from ONLY the new user message.

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

1. A request to find a doctor is doctor_search.

2. A request to book or schedule an appointment is
   appointment_booking.

3. If the current workflow is already an appointment workflow,
   a follow-up containing only a date, time, or patient name
   must be appointment_booking.

4. Do not invent missing information.

5. Date format:
   YYYY-MM-DD

6. Time format:
   HH:MM

7. If the user says "14:00", extract:
   appointment_time = "14:00"

8. If the user says "2026-10-01", extract:
   appointment_date = "2026-10-01"

9. If the user provides a person's name in response to a
   patient-name request, extract it as patient_name.

10. Return empty strings for fields not present in the
    current user message.
"""

    try:

        response = llm.invoke(prompt)

        content = response.content

        if isinstance(content, list):
            content = "".join(
                str(item)
                for item in content
            )

        content = str(content).strip()

        if content.startswith("```"):

            content = content.replace(
                "```json",
                "",
            )

            content = content.replace(
                "```",
                "",
            )

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

    # --------------------------------------------------------
    # Update only fields explicitly extracted
    # --------------------------------------------------------

    if parsed.get("intent"):
        state["intent"] = parsed["intent"]

    if parsed.get("specialty"):
        state["specialty"] = parsed["specialty"]

    if parsed.get("doctor_name"):
        state["doctor_name"] = parsed["doctor_name"]

    if parsed.get("patient_name"):
        state["patient_name"] = parsed["patient_name"]

    if parsed.get("appointment_date"):
        state["appointment_date"] = parsed[
            "appointment_date"
        ]

    if parsed.get("appointment_time"):
        state["appointment_time"] = parsed[
            "appointment_time"
        ]

    # --------------------------------------------------------
    # Existing appointment workflow has priority
    # --------------------------------------------------------

    existing_status = state.get(
        "status",
        "",
    )

    appointment_states = {
        "waiting_for_doctor",
        "waiting_for_date",
        "waiting_for_time",
        "waiting_for_patient_name",
        "availability_checked",
        "availability_error",
    }

    if existing_status in appointment_states:

        state["intent"] = "appointment_booking"

    elif (
        state.get("doctor_name")
        and state.get("appointment_date")
    ):

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

    status = state.get(
        "status",
        "",
    )

    intent = state.get(
        "intent",
        "general",
    )

    # --------------------------------------------------------
    # Continue existing scheduling workflow
    # --------------------------------------------------------

    if status in {
        "waiting_for_doctor",
        "waiting_for_date",
        "waiting_for_time",
        "waiting_for_patient_name",
        "availability_checked",
        "availability_error",
    }:

        return "check_availability"

    # --------------------------------------------------------
    # New request
    # --------------------------------------------------------

    if intent == "doctor_search":
        return "search_doctors"

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

    query = state.get(
        "query",
        "",
    )

    search_query = doctor_name or query

    result = search_doctors.invoke(
        {
            "specialty": specialty,
            "query": search_query,
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

            # If exactly one doctor matches,
            # retain that doctor in the workflow.
            if len(doctors) == 1:

                state["doctor_name"] = doctors[0].get(
                    "name",
                    "",
                )

            lines = [
                "I found the following doctor(s):",
                "",
            ]

            for doctor in doctors:

                lines.append(
                    f"• {doctor.get('name')} — "
                    f"{doctor.get('specialty')} "
                    f"({doctor.get('experience')} years experience)"
                )

            state["response"] = "\n".join(
                lines
            )

        else:

            state["response"] = parsed.get(
                "message",
                "No doctors were found.",
            )

    except Exception:

        state["response"] = str(result)

    state["status"] = (
        "doctor_search_completed"
    )

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

    memory = MemorySaver()

    return workflow.compile(
        checkpointer=memory,
    )