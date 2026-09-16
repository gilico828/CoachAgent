"""The clock tool, and the dispatch that picks a tool by name.

The timezone cases are the point: the bot runs on an EC2 instance set to UTC, so
a wrong answer here looks exactly like a right one — no exception, no log line.
"""

import json
from datetime import datetime, timezone

import pytest

from coach_agent import tools


def _freeze(monkeypatch, moment: datetime) -> None:
    class _Frozen:
        @staticmethod
        def now(tz):
            return moment.astimezone(tz)

    monkeypatch.setattr(tools, "datetime", _Frozen)


def test_returns_israel_local_time_and_not_the_servers_utc(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 16, 10, 5, tzinfo=timezone.utc))
    assert tools.get_current_datetime() == {
        "date": "2026-09-16",
        "time": "13:05",
        "weekday": "רביעי",
        "timezone": "Asia/Jerusalem",
    }


@pytest.mark.parametrize(("utc_day", "israel_hour"), [("2026-01-15", 14), ("2026-07-15", 15)])
def test_daylight_saving_is_applied_instead_of_a_fixed_offset(utc_day, israel_hour):
    """Israel is +2 in winter and +3 in summer, so a hardcoded offset would be wrong
    half the year. This also fails loudly if the tz database is missing at runtime."""
    noon_utc = datetime.fromisoformat(f"{utc_day}T12:00:00+00:00")
    assert noon_utc.astimezone(tools._TIMEZONE).hour == israel_hour


@pytest.mark.parametrize(
    ("date", "weekday"),
    [
        ("2026-09-14", "שני"),
        ("2026-09-15", "שלישי"),
        ("2026-09-16", "רביעי"),
        ("2026-09-17", "חמישי"),
        ("2026-09-18", "שישי"),
        ("2026-09-19", "שבת"),
        ("2026-09-20", "ראשון"),
    ],
)
def test_every_weekday_maps_to_the_right_hebrew_name(monkeypatch, date, weekday):
    """weekday() is Monday-based, which makes the list one rotation away from wrong."""
    _freeze(monkeypatch, datetime.fromisoformat(f"{date}T09:00:00+03:00"))
    assert tools.get_current_datetime()["weekday"] == weekday


def test_each_tool_name_reaches_its_own_handler(monkeypatch):
    monkeypatch.setattr(tools, "search_by_name", lambda query: {"name": query})
    assert json.loads(tools.run_tool("lookup_food", {"query": "banana"}))["name"] == "banana"
    assert "date" in json.loads(tools.run_tool("get_current_datetime", {}))


def test_a_barcode_wins_over_a_query_when_the_model_sends_both(monkeypatch):
    monkeypatch.setattr(tools, "search_by_barcode", lambda barcode: {"name": "by barcode"})
    monkeypatch.setattr(tools, "search_by_name", lambda query: {"name": "by name"})
    result = json.loads(tools.run_tool("lookup_food", {"query": "x", "barcode": "123"}))
    assert result["name"] == "by barcode"


def test_an_unknown_tool_is_reported_back_instead_of_raising():
    """A hallucinated tool name should cost one wasted turn, not kill the conversation."""
    assert "no_such_tool" in tools.run_tool("no_such_tool", {})


def test_every_tool_offered_to_the_model_has_a_handler():
    """A schema in TOOLS with no entry in _HANDLERS is a dead end the model can reach."""
    assert {tool["name"] for tool in tools.TOOLS} == set(tools._HANDLERS)
