import json

import pytest

from app.tools import (
    check_availability,
    get_available_dates,
    search_doctors,
)


def invoke_tool(tool, **kwargs):
    return json.loads(tool.invoke(kwargs))


def test_search_doctors_by_specialty():
    result = invoke_tool(
        search_doctors,
        specialty="Dermatologist",
        query="",
    )

    assert result["status"] == "success"
    assert result["doctors"]

    assert all(
        doctor["specialty"].lower() == "dermatologist"
        for doctor in result["doctors"]
    )


def test_search_doctors_by_name():
    result = invoke_tool(
        search_doctors,
        specialty="",
        query="Emily",
    )

    assert result["status"] == "success"
    assert any(
        "Emily" in doctor["name"]
        for doctor in result["doctors"]
    )


def test_available_dates_returns_structured_dates():
    result = invoke_tool(
        get_available_dates,
        doctor_name="Dr. Emily Johnson",
    )

    assert result["status"] == "success"
    assert isinstance(
        result["available_dates"],
        list,
    )


def test_availability_returns_slots_for_seeded_date():
    result = invoke_tool(
        check_availability,
        doctor_name="Dr. Emily Johnson",
        appointment_date="2026-10-03",
    )

    assert result["status"] == "success"
    assert isinstance(
        result["available_slots"],
        list,
    )
