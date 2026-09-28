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
# Model
# ============================================================

llm = setup_llm()


# ============================================================
# Trace Helper
# ============================================================

def add_trace(
    state: SchedulingState,
    node: str,
    details: str = "",
):
    """
    Add a simple execution trace entry.
    """

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
# Request Analysis
# ============================================================

def analyze_request(
    state: SchedulingState,
) -> SchedulingState:

    query = state.get("query", "").strip()

    # --------------------------------------------------------
    # Preserve existing state
    # --------------------------------------------------------

    existing_doctor = state.get("doctor_name", "")
    existing_date = state.get("appointment_date", "")
    existing_time = state.get("appointment_time", "")
    existing_patient = state.get("patient_name", "")

    # --------------------------------------------------------
    # Build context for LLM
    # --------------------------------------------------------

    context = {
        "existing_doctor": existing_doctor,
        "existing_date": existing_date,
        "existing_time": existing_time,
        "existing_patient": existing_patient,
    }

    prompt = f"""
You are the intent extraction component of a healthcare
appointment scheduling system.

Current conversation state:

{json.dumps(context, indent=2)}

New user message:

{query}

Extract the information from the user's message.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "intent": "doctor_search | appointment_booking | general",
    "specialty": "",
    "doctor_name": "",
    "patient_name": "",
    "appointment_date": "",
    "appointment_time": ""
}}

Rules:

1. If the user is searching for a doctor, use doctor_search.
2. If the user wants to book or schedule an appointment,
   use appointment_booking.
3. If the user provides only a date, time, doctor name,
   or patient name as a follow-up to an existing appointment
   conversation, use appointment_booking.
4. Dates must use YYYY-MM-DD when the date is unambiguous.
5. Times must use HH:MM in 24-hour format.
6. Do not invent missing information.
7. Preserve existing information conceptually, but only
   extract information explicitly available from the current
   message.
"""

    try:

        response = llm.invoke(prompt)

        content = response.content

        # ----------------------------------------------------
        # Extract JSON
        # ----------------------------------------------------

        if isinstance(content, list):
            content = "".join(
                str(item)
                for item in content
            )

        content = str(content).strip()

        # Remove markdown fences if model adds them
        if content.startswith("```"):
            content = content.replace("```json", "")
            content = content.replace("```", "")
            content = content.strip()

        parsed = json.loads(content)

    except Exception:

        parsed = {
            "intent": "general",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        }

    # --------------------------------------------------------
    # Update state only when information exists
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
        state["appointment_date"] = parsed["appointment_date"]

    if parsed.get("appointment_time"):
        state["appointment_time"] = parsed["appointment_time"]

    # --------------------------------------------------------
    # Detect follow-up messages
    # --------------------------------------------------------

    if (
        existing_doctor
        or existing_date
        or existing_time
        or existing_patient
    ):
        state["intent"] = "appointment_booking"

    add_trace(
        state,
        "analyze_request",
        json.dumps(parsed),
    )

    return state


# ============================================================
# Routing
# ============================================================

def route_request(state: SchedulingState):

    intent = state.get("intent", "general")

    # Existing appointment workflow takes priority
    if (
        state.get("doctor_name")
        or state.get("appointment_date")
        or state.get("appointment_time")
    ):
        if intent == "appointment_booking":
            return "check_availability"

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

    specialty = state.get("specialty", "")
    doctor_name = state.get("doctor_name", "")
    query = state.get("query", "")

    # Prefer extracted doctor/specialty information
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

            doctors = parsed.get("doctors", [])

            if len(doctors) == 1:

                doctor = doctors[0]

                state["doctor_name"] = doctor.get(
                    "name",
                    "",
                )

    except Exception:
        pass

    # --------------------------------------------------------
    # Build response
    # --------------------------------------------------------

    try:

        parsed = json.loads(result)

        if parsed.get("status") == "success":

            doctors = parsed.get("doctors", [])

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
# Availability
# ============================================================

def check_availability_node(
    state: SchedulingState,
) -> SchedulingState:

    doctor_name = state.get("doctor_name", "")
    appointment_date = state.get(
        "appointment_date",
        "",
    )

    # --------------------------------------------------------
    # Need doctor
    # --------------------------------------------------------

    if not doctor_name:

        state["status"] = "waiting_for_doctor"

        state["response"] = (
            "Which doctor would you like to book "
            "an appointment with?"
        )

        add_trace(
            state,
            "check_availability",
            "Missing doctor",
        )

        return state

    # --------------------------------------------------------
    # Need date
    # --------------------------------------------------------

    if not appointment_date:

        state["status"] = "waiting_for_date"

        state["response"] = (
            f"What date would you like to see "
            f"{doctor_name.replace('Dr. ', '')}?"
        )

        add_trace(
            state,
            "check_availability",
            "Missing appointment date",
        )

        return state

    # --------------------------------------------------------
    # Check availability
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

        state["response"] = str(result)
        state["status"] = "availability_checked"

        return state

    if parsed.get("status") != "success":

        state["response"] = parsed.get(
            "message",
            "Unable to check availability.",
        )

        state["status"] = "availability_error"

        return state

    available_slots = parsed.get(
        "available_slots",
        [],
    )

    state["available_slots"] = available_slots

    # --------------------------------------------------------
    # If user already supplied a time
    # --------------------------------------------------------

    appointment_time = state.get(
        "appointment_time",
        "",
    )

    if appointment_time:

        if appointment_time in available_slots:

            return book_appointment_node(state)

        state["status"] = "waiting_for_time"

        state["response"] = (
            f"{appointment_time} is not available.\n\n"
            f"Available times for {doctor_name} on "
            f"{appointment_date} are:\n"
            + "\n".join(
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
    # Ask user to select time
    # --------------------------------------------------------

    state["status"] = "waiting_for_time"

    state["response"] = (
        f"Available times for {doctor_name} on "
        f"{appointment_date} are:\n\n"
        + "\n".join(
            f"• {slot}"
            for slot in available_slots
        )
        + "\n\nWhich time would you prefer?"
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

    doctor_name = state.get("doctor_name", "")
    patient_name = state.get("patient_name", "")
    appointment_date = state.get(
        "appointment_date",
        "",
    )
    appointment_time = state.get(
        "appointment_time",
        "",
    )

    # --------------------------------------------------------
    # Patient name
    # --------------------------------------------------------

    if not patient_name:

        state["status"] = "waiting_for_patient_name"

        state["response"] = (
            "May I have the patient's name?"
        )

        add_trace(
            state,
            "book_appointment",
            "Missing patient name",
        )

        return state

    # --------------------------------------------------------
    # Doctor
    # --------------------------------------------------------

    if not doctor_name:

        state["status"] = "waiting_for_doctor"

        state["response"] = (
            "Which doctor would you like to book "
            "an appointment with?"
        )

        return state

    # --------------------------------------------------------
    # Date
    # --------------------------------------------------------

    if not appointment_date:

        state["status"] = "waiting_for_date"

        state["response"] = (
            "What date would you like the appointment?"
        )

        return state

    # --------------------------------------------------------
    # Time
    # --------------------------------------------------------

    if not appointment_time:

        state["status"] = "waiting_for_time"

        available_slots = state.get(
            "available_slots",
            [],
        )

        state["response"] = (
            "Please choose an available time:\n\n"
            + "\n".join(
                f"• {slot}"
                for slot in available_slots
            )
        )

        return state

    # --------------------------------------------------------
    # Book
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

        state["response"] = str(result)
        state["status"] = "booking_completed"

        return state

    if parsed.get("status") == "success":

        appointment = parsed.get(
            "appointment",
            {},
        )

        state["status"] = "booking_completed"

        state["response"] = (
            "Appointment booked successfully!\n\n"
            f"Patient: {appointment.get('patient_name')}\n"
            f"Doctor: {appointment.get('doctor_name')}\n"
            f"Specialty: {appointment.get('specialty')}\n"
            f"Date: {appointment.get('date')}\n"
            f"Time: {appointment.get('time')}"
        )

    else:

        state["status"] = "booking_error"

        state["response"] = parsed.get(
            "message",
            "Unable to book the appointment.",
        )

    add_trace(
        state,
        "book_appointment",
        "Booking operation completed",
    )

    return state


# ============================================================
# General Response
# ============================================================

def general_response(
    state: SchedulingState,
) -> SchedulingState:

    query = state.get("query", "")

    prompt = f"""
You are a healthcare appointment scheduling assistant.

User message:
{query}

Respond helpfully and concisely.

You can help users:
- find doctors
- identify medical specialties
- check appointment availability
- book appointments

Do not provide medical diagnosis or treatment advice.

If the request is unrelated to scheduling or finding doctors,
politely explain what you can help with.
"""

    response = llm.invoke(prompt)

    content = response.content

    if isinstance(content, list):
        content = "".join(
            str(item)
            for item in content
        )

    state["response"] = str(content).strip()
    state["status"] = "general_response"

    add_trace(
        state,
        "general_response",
        "General response generated",
    )

    return state


# ============================================================
# Graph Builder
# ============================================================

def build_graph():

    workflow = StateGraph(SchedulingState)

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
    # Search -> End
    # --------------------------------------------------------

    workflow.add_edge(
        "search_doctors",
        END,
    )

    # --------------------------------------------------------
    # Availability -> conditional routing
    # --------------------------------------------------------

    def availability_router(
        state: SchedulingState,
    ):

        status = state.get(
            "status",
            "",
        )

        if status == "waiting_for_date":
            return "end"

        if status == "waiting_for_doctor":
            return "end"

        if status == "waiting_for_time":
            return "end"

        if status == "availability_error":
            return "end"

        if status == "booking_completed":
            return "end"

        if state.get("appointment_time"):
            return "book"

        return "end"

    workflow.add_conditional_edges(
        "check_availability",
        availability_router,
        {
            "book": "book_appointment",
            "end": END,
        },
    )

    # --------------------------------------------------------
    # Booking -> End
    # --------------------------------------------------------

    workflow.add_edge(
        "book_appointment",
        END,
    )

    # --------------------------------------------------------
    # General -> End
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