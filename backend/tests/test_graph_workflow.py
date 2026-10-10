import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import backend.app.graph as graph


class FakeLLM:
    """Return a deterministic JSON extraction for a test query."""

    def __init__(self, responses):
        self.responses = responses

    def invoke(self, prompt):
        # The current user message is included at the end of the prompt.
        marker = "New user message:\n"
        query = prompt.split(marker, 1)[1].split("\n\nClassify", 1)[0].strip()
        response = self.responses.get(query)

        if response is None:
            raise AssertionError(f"No fake LLM response configured for: {query!r}")

        return SimpleNamespace(content=json.dumps(response))


def fake_all_doctors():
    return json.dumps(
        {
            "status": "success",
            "doctors": [
                {
                    "name": "Dr. Emily Johnson",
                    "specialty": "Dermatologist",
                    "experience": 8,
                },
                {
                    "name": "Dr. John Smith",
                    "specialty": "Cardiologist",
                    "experience": 12,
                },
            ],
        }
    )


@pytest.fixture
def patch_llm_and_doctors(monkeypatch):
    monkeypatch.setattr(
        graph.search_doctors,
        "invoke",
        Mock(return_value=fake_all_doctors()),
    )


def run_analysis(monkeypatch, state, query, llm_response):
    monkeypatch.setattr(
        graph,
        "llm",
        FakeLLM({query: llm_response}),
    )

    state["query"] = query
    return graph.analyze_request(state)


def test_specialty_booking_is_not_treated_as_doctor_name(
    monkeypatch,
    patch_llm_and_doctors,
):
    state = {}

    state = run_analysis(
        monkeypatch,
        state,
        "I need to book a dermatologist",
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "dermatologist",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert state["intent"] == "appointment_booking"
    assert state["specialty"] == "Dermatologist"
    assert state["doctor_name"] == ""


def test_specialty_booking_routes_to_check_availability(
    monkeypatch,
    patch_llm_and_doctors,
):
    state = {}

    state = run_analysis(
        monkeypatch,
        state,
        "I need to book a cardiologist",
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "cardiologist",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert graph.route_request(state) == "check_availability"


@pytest.mark.parametrize(
    "query",
    [
        "On which dates is Emily available?",
        "What are the available dates?",
        "Which dates is Dr Emily available?",
        "When is Dr Emily available?",
        "Can you list the dates when Emily is available?",
    ],
)
def test_availability_date_questions_override_booking_state(
    monkeypatch,
    query,
):
    state = {
        "status": "waiting_for_date",
        "intent": "appointment_booking",
        "doctor_name": "Dr. Emily Johnson",
        "appointment_date": "",
    }

    state = run_analysis(
        monkeypatch,
        state,
        query,
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert state["intent"] == "availability_dates"
    assert graph.route_request(state) == "availability_dates"


def test_natural_language_date_is_normalized(
    monkeypatch,
):
    state = {
        "status": "waiting_for_date",
        "intent": "appointment_booking",
        "doctor_name": "Dr. Emily Johnson",
        "appointment_date": "",
    }

    state = run_analysis(
        monkeypatch,
        state,
        "October 10th",
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert state["intent"] == "appointment_booking"
    assert state["appointment_date"].endswith("-10-10")


def test_booking_after_availability_lookup_preserves_doctor(
    monkeypatch,
):
    state = {
        "status": "availability_dates_completed",
        "intent": "availability_dates",
        "doctor_name": "Dr. Emily Johnson",
        "specialty": "",
        "appointment_date": "",
        "appointment_time": "",
        "patient_name": "",
    }

    state = run_analysis(
        monkeypatch,
        state,
        "I want to book on October 3rd",
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert state["intent"] == "appointment_booking"
    assert state["doctor_name"] == "Dr. Emily Johnson"
    assert state["appointment_date"].endswith("-10-03")
    assert graph.route_request(state) == "check_availability"


def test_explicit_doctor_search_overrides_old_booking_state(
    monkeypatch,
):
    state = {
        "status": "waiting_for_time",
        "intent": "appointment_booking",
        "doctor_name": "Dr. Michael Brown",
        "appointment_date": "2026-10-02",
        "appointment_time": "",
    }

    state = run_analysis(
        monkeypatch,
        state,
        "Can you list the doctors available?",
        {
            "intent": "appointment_booking",
            "specialty": "",
            "doctor_name": "",
            "patient_name": "",
            "appointment_date": "",
            "appointment_time": "",
        },
    )

    assert state["intent"] == "doctor_search"
    assert state["doctor_name"] == ""
    assert state["appointment_date"] == ""
    assert graph.route_request(state) == "search_doctors"


def test_date_extraction_helpers():
    assert graph._normalize_natural_date("October 10th").endswith(
        "-10-10"
    )
    assert graph._normalize_natural_date("Oct 3").endswith(
        "-10-03"
    )
    assert graph._normalize_natural_date("3rd October 2026") == (
        "2026-10-03"
    )
    assert graph._extract_date_from_text(
        "I want an appointment on October 3rd"
    ) == "October 3rd"
