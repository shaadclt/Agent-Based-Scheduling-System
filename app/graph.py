import json
import re
from datetime import date, datetime

from app.checkpointer import checkpointer
from langgraph.graph import END, START, StateGraph

from app.config import setup_llm
from app.state import SchedulingState
from app.tools import (
    book_appointment,
    check_availability,
    get_available_dates,
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


def _extract_date_from_text(text: str) -> str:
    """Extract a common conversational date phrase from free text."""
    if not text:
        return ""

    patterns = (
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+\d{4})?\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?(?:\s+\d{4})?\b",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)

    return ""


def _normalize_natural_date(value: str) -> str:
    """Convert common natural-language dates to YYYY-MM-DD.

    The LLM is still responsible for entity extraction, but dates
    are normalized deterministically so phrases such as
    "October 10th", "Oct 10", and "10 October" do not
    get lost when the model returns the original wording.
    """
    if not value:
        return ""

    value = str(value).strip()

    # Already normalized.
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"[,]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())

    formats = (
        "%B %d %Y",
        "%B %d",
        "%b %d %Y",
        "%b %d",
        "%d %B %Y",
        "%d %B",
        "%d %b %Y",
        "%d %b",
    )

    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return value

    if "%Y" not in fmt:
        parsed = parsed.replace(year=date.today().year)

        # For a date without a year that has already passed, prefer
        # the next occurrence. This is useful for conversational
        # booking requests such as "January 5th".
        if parsed.date() < date.today():
            parsed = parsed.replace(year=parsed.year + 1)

    return parsed.date().isoformat()


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
    "intent": "doctor_search | availability_dates | appointment_booking | general",
    "specialty": "",
    "doctor_name": "",
    "patient_name": "",
    "appointment_date": "",
    "appointment_time": ""
}}

Rules:

1. A request to find, list, browse, or search for doctors is
   doctor_search.

2. A request to list the dates when a specific doctor is
   available is availability_dates.

Examples:
- "What dates is Dr Emily available?"
- "Can you list the dates when Dr Emily is available?"
- "When can I see Dr Emily?"

3. A request to book or schedule an appointment is
   appointment_booking.

3. If the current workflow is an active appointment workflow,
   a follow-up containing only a date, time, or patient name
   must be appointment_booking.

4. An explicit doctor-search request takes priority over an
   older appointment workflow. For example, if the old state
   is waiting_for_time and the user says "Can you list the
   doctors available?", classify it as doctor_search.

5. Do not invent missing information.

6. Date format: YYYY-MM-DD. Convert natural-language dates
   such as "October 10th", "Oct 10", "10 October",
   and "October 10, 2026" into YYYY-MM-DD. If a year is not
   provided, use the current year.

7. Time format: HH:MM. Convert natural-language times when
   unambiguous, such as "2 PM" -> "14:00".

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

    # Normalize dates deterministically after extraction. This makes
    # the workflow robust to LLM outputs such as "October 10th".
    raw_date = parsed.get("appointment_date", "")

    if raw_date:
        parsed["appointment_date"] = _normalize_natural_date(
            raw_date
        )
    else:
        # Some model responses may leave appointment_date empty even
        # when the current message clearly contains a natural date.
        # Recover it directly from the user's message.
        extracted_date = _extract_date_from_text(query)
        if extracted_date:
            parsed["appointment_date"] = _normalize_natural_date(
                extracted_date
            )

    parsed_intent = parsed.get("intent", "")
    existing_status = state.get("status", "")
    active_appointment = existing_status in ACTIVE_APPOINTMENT_STATES

    # --------------------------------------------------------
    # Deterministic intent safeguards
    # --------------------------------------------------------
    # The LLM can occasionally classify a follow-up such as
    # "Can you list the available dates?" as appointment_booking
    # because the previous state is waiting_for_date. Detect the
    # explicit availability-date wording before applying the
    # active-booking continuation rule.
    # Detect date-availability questions deterministically before
    # allowing the previous appointment state to influence routing.
    # This covers variations such as:
    #   - which date is she available?
    #   - which dates is Dr Emily available?
    #   - what dates are available?
    #   - when is Dr Emily available?
    #   - can you list the available dates?
    availability_date_patterns = (
        r"\bavailable\b.*\bdates?\b",
        r"\bdates?\b.*\bavailable\b",
        r"\bwhich\s+dates?\b",
        r"\bwhat\s+dates?\b",
        r"\bwhich\s+date\b.*\bavailable\b",
        r"\bwhat\s+date\b.*\bavailable\b",
        r"\bwhen\b.*\bavailable\b",
        r"\bavailable\b.*\bwhen\b",
    )

    looks_like_availability_dates = any(
        re.search(
            pattern,
            query,
            flags=re.IGNORECASE,
        )
        for pattern in availability_date_patterns
    )

    if looks_like_availability_dates:
        parsed_intent = "availability_dates"
        parsed["intent"] = parsed_intent

    # An explicit booking request must override a previous
    # availability-date lookup. For example, after showing
    # Emily's available dates, the user may say:
    # "I want to book on October 3".
    # That is a booking continuation, not another availability
    # lookup.
    explicit_booking_patterns = (
        r"\bbook\b",
        r"\bbooking\b",
        r"\bschedule\b",
        r"\breserve\b",
        r"\bappointment\b",
    )

    looks_like_booking_request = any(
        re.search(
            pattern,
            query,
            flags=re.IGNORECASE,
        )
        for pattern in explicit_booking_patterns
    )

    # A date plus an explicit booking phrase is always a booking
    # request, even when the previous state was
    # availability_dates_completed.
    if looks_like_booking_request:
        parsed_intent = "appointment_booking"
        parsed["intent"] = parsed_intent

    # If the conversation is already performing a doctor
    # availability-date lookup, a follow-up doctor name such as
    # "Dr Emily" should continue that lookup rather than starting
    # an appointment booking workflow.
    elif state.get("intent") == "availability_dates":
        parsed_intent = "availability_dates"
        parsed["intent"] = parsed_intent

    # An active booking workflow should continue for follow-up
    # messages, but explicit doctor-search and availability-date
    # requests always take priority over the old booking state.
    elif active_appointment:
        parsed_intent = "appointment_booking"
        parsed["intent"] = parsed_intent

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
    # Doctor availability-date request. This is a lookup
    # request, not a booking step, so old booking entities
    # must not control the response.
    # --------------------------------------------------------
    elif parsed_intent == "availability_dates":
        state["intent"] = "availability_dates"
        state["specialty"] = ""
        state["doctor_name"] = parsed.get("doctor_name", "") or state.get("doctor_name", "")
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
        # A booking request can immediately follow an
        # availability-date lookup. In that case, preserve the
        # doctor selected during the lookup even though the
        # previous status is not an active booking status.
        previous_intent = state.get("intent", "")
        previous_doctor = state.get("doctor_name", "")

        if not active_appointment and previous_intent != "availability_dates":
            state["doctor_name"] = ""
            state["specialty"] = ""
            state["patient_name"] = ""
            state["appointment_date"] = ""
            state["appointment_time"] = ""
            state["available_slots"] = []

        state["intent"] = "appointment_booking"

        if previous_intent == "availability_dates" and previous_doctor:
            state["doctor_name"] = previous_doctor

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

    # Explicit lookup requests always win over a stale booking
    # status.
    if intent == "doctor_search":
        return "search_doctors"

    if intent == "availability_dates":
        return "availability_dates"

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

            # If a specialty search returns exactly one doctor,
            # remember that doctor as the current selection. This
            # allows a follow-up such as "Which date is available?"
            # to check that doctor's dates without asking for the
            # doctor again.
            if len(doctors) == 1:
                state["doctor_name"] = doctors[0].get(
                    "name",
                    state.get("doctor_name", ""),
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
# Doctor Available Dates
# ============================================================

def availability_dates_node(
    state: SchedulingState,
) -> SchedulingState:

    doctor_name = state.get(
        "doctor_name",
        "",
    )

    if not doctor_name:

        state["status"] = "waiting_for_doctor"
        state["response"] = (
            "Which doctor would you like to "
            "check availability for?"
        )

        add_trace(
            state,
            "availability_dates",
            "Waiting for doctor",
        )

        return state

    result = get_available_dates.invoke(
        {
            "doctor_name": doctor_name,
        }
    )

    try:
        parsed = json.loads(result)
    except Exception:
        state["status"] = "availability_error"
        state["response"] = str(result)
        return state

    if parsed.get("status") != "success":
        state["status"] = "availability_error"
        state["response"] = parsed.get(
            "message",
            "Unable to check doctor availability.",
        )
        add_trace(
            state,
            "availability_dates",
            "Doctor lookup failed",
        )
        return state

    available_dates = parsed.get(
        "available_dates",
        [],
    )

    state["available_slots"] = []

    if not available_dates:
        state["status"] = "availability_dates_completed"
        state["response"] = (
            f"No available dates were found for "
            f"{parsed.get('doctor', doctor_name)}."
        )
    else:
        state["status"] = "availability_dates_completed"
        state["response"] = (
            f"{parsed.get('doctor', doctor_name)} is available on:\n\n"
            + "\n".join(
                f"• {available_date}"
                for available_date in available_dates
            )
        )

    add_trace(
        state,
        "availability_dates",
        f"Found {len(available_dates)} available date(s)",
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

        # If the user specified a specialty, resolve the doctor
        # before asking another question. This allows a natural
        # request such as "I need to book a dermatologist" to
        # proceed directly when exactly one matching doctor exists.
        specialty = state.get(
            "specialty",
            "",
        ).strip()

        if specialty:

            doctor_result = search_doctors.invoke(
                {
                    "specialty": specialty,
                    "query": "",
                }
            )

            try:
                doctor_data = json.loads(
                    doctor_result
                )
            except Exception:
                doctor_data = {}

            if doctor_data.get("status") == "success":

                doctors = doctor_data.get(
                    "doctors",
                    [],
                )

                # A specialty request should never silently select a
                # doctor, even when there is only one matching doctor.
                # The user should see the doctor name and explicitly
                # choose whom to book. This keeps the workflow clear
                # and avoids making an implicit provider selection.
                if doctors:

                    if len(doctors) == 1:
                        heading = (
                            f"I found a {specialty} doctor:"
                        )
                    else:
                        heading = (
                            f"I found these {specialty} doctors:"
                        )

                    lines = [
                        heading,
                        "",
                    ]

                    for doctor in doctors:
                        lines.append(
                            f"• {doctor.get('name')} — "
                            f"{doctor.get('specialty')} "
                            f"({doctor.get('experience')} years experience)"
                        )

                    lines.extend(
                        [
                            "",
                            "Which doctor would you like to book?",
                        ]
                    )

                    state["status"] = (
                        "waiting_for_doctor"
                    )

                    state["response"] = "\n".join(lines)

                    add_trace(
                        state,
                        "check_availability",
                        (
                            f"Listed {len(doctors)} doctor(s) "
                            f"for specialty '{specialty}'"
                        ),
                    )

                    return state

        # No specialty match, or no doctor could be resolved.
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
        "availability_dates",
        availability_dates_node,
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

            "availability_dates":
                "availability_dates",

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

    workflow.add_edge(
        "availability_dates",
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