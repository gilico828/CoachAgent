"""The food log and the measurements table, and the tools that reach them.

The isolation test is the one that matters most here. Every other failure in this
file shows up as a wrong number; that one shows up as the coach telling one person
what somebody else ate, and nothing in the system would raise on the way there.
"""

import json

import pytest

from coach_agent import log_store, tools

_USER = "telegram_1"
_OTHER = "telegram_2"
_CONTEXT = tools.ToolContext(user_key=_USER)
_DAY = "2026-09-18"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(log_store, "DB_PATH", tmp_path / "coach.db")
    return tmp_path / "coach.db"


def _eggs(**overrides) -> dict:
    return {"item": "ביצים", "grams": 100, "calories": 155, "protein": 13, **overrides}


# --- Isolation ---------------------------------------------------------------


def test_one_users_meal_never_appears_in_anothers_day():
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T08:30")
    log_store.log_meal(_OTHER, [{"item": "פיצה", "calories": 800}], eaten_at=f"{_DAY}T08:30")

    mine = log_store.food_log_for_day(_USER, _DAY)
    assert [item["item"] for item in mine["items"]] == ["ביצים"]
    assert mine["totals"]["calories"] == 155


def test_one_users_measurements_never_appear_in_anothers_trend():
    log_store.log_measurement(_USER, "weight", 80.5)
    log_store.log_measurement(_OTHER, "weight", 62.0)

    assert [row["value"] for row in log_store.measurements_for(_USER, "weight")] == [80.5]


# --- Food log ----------------------------------------------------------------


def test_a_meal_of_three_items_becomes_three_rows_sharing_one_timestamp():
    log_store.log_meal(
        _USER,
        [_eggs(), {"item": "לחם", "calories": 158}, {"item": "קפה", "calories": 5}],
        meal_type="בוקר",
        eaten_at=f"{_DAY}T08:30",
    )
    items = log_store.food_log_for_day(_USER, _DAY)["items"]

    assert len(items) == 3
    assert {item["eaten_at"] for item in items} == {f"{_DAY}T08:30:00+03:00"}
    assert {item["meal_type"] for item in items} == {"בוקר"}


def test_totals_sum_the_day_and_ignore_missing_values():
    log_store.log_meal(
        _USER,
        [_eggs(), {"item": "תפוח"}],  # no figures were looked up for the apple
        eaten_at=f"{_DAY}T08:30",
    )
    totals = log_store.food_log_for_day(_USER, _DAY)["totals"]

    assert totals == {"calories": 155, "protein": 13, "carbs": 0, "fat": 0}


def test_yesterdays_meal_is_not_counted_in_todays_day():
    log_store.log_meal(_USER, [_eggs()], eaten_at="2026-09-17T20:00")
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T08:30")

    assert len(log_store.food_log_for_day(_USER, _DAY)["items"]) == 1


def test_a_late_night_meal_belongs_to_the_day_it_was_eaten():
    """23:50 is the edge the day-range query would get wrong if it were built
    from a date prefix and an off-by-one hour rather than from local bounds."""
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T23:50")

    assert len(log_store.food_log_for_day(_USER, _DAY)["items"]) == 1


def test_an_item_with_no_name_is_dropped_rather_than_stored_blank():
    assert log_store.log_meal(_USER, [{"grams": 100}, _eggs()]) == 1


def test_a_field_the_schema_does_not_know_is_dropped_not_stored():
    """The model inventing `feeling` is the failure this table is shaped to
    prevent — it must not quietly become a column-shaped value somewhere."""
    log_store.log_meal(_USER, [_eggs(feeling="כבד")], eaten_at=f"{_DAY}T08:30")
    item = log_store.food_log_for_day(_USER, _DAY)["items"][0]

    assert "feeling" not in item


def test_notes_carries_what_has_no_column_of_its_own():
    log_store.log_meal(
        _USER, [_eggs(notes="אמר שהרגיש כבד אחרי")], eaten_at=f"{_DAY}T08:30"
    )
    item = log_store.food_log_for_day(_USER, _DAY)["items"][0]

    assert item["notes"] == "אמר שהרגיש כבד אחרי"


# --- Measurements ------------------------------------------------------------


def test_a_measurement_gets_the_unit_of_its_metric_without_being_told():
    log_store.log_measurement(_USER, "body_fat", 18.2)
    assert log_store.measurements_for(_USER, "body_fat")[0]["unit"] == "%"


def test_readings_come_back_oldest_first_so_a_trend_reads_in_order():
    log_store.log_measurement(_USER, "weight", 81.0, measured_at="2026-09-10T07:00")
    log_store.log_measurement(_USER, "weight", 80.0, measured_at="2026-09-17T07:00")

    assert [row["value"] for row in log_store.measurements_for(_USER, "weight")] == [81.0, 80.0]


def test_an_invented_metric_is_refused_instead_of_stored():
    with pytest.raises(log_store.UnknownMetric):
        log_store.log_measurement(_USER, "mood", 7)


# --- Schema ------------------------------------------------------------------


def test_the_schema_is_created_once_and_reopening_does_not_rerun_it():
    """Every call opens its own connection, so the migration guard runs constantly.
    A guard that failed the second time would break on the second message, not the
    first — which is exactly when nobody is watching the logs."""
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T08:30")
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T12:30")

    assert len(log_store.food_log_for_day(_USER, _DAY)["items"]) == 2


def test_rows_survive_a_fresh_connection():
    """The point of the whole phase: MemorySaver forgets on restart, this must not."""
    log_store.log_meal(_USER, [_eggs()], eaten_at=f"{_DAY}T08:30")
    assert log_store.food_log_for_day(_USER, _DAY)["totals"]["calories"] == 155


# --- The tools -------------------------------------------------------------


def test_logging_a_meal_through_the_tool_reports_how_many_rows_it_wrote():
    reply = tools.run_tool(
        "log_meal",
        {"items": [_eggs(), {"item": "לחם"}], "meal_type": "בוקר"},
        _CONTEXT,
    )
    assert "2" in reply


def test_reading_an_empty_day_says_so_instead_of_returning_an_empty_list():
    reply = tools.run_tool("get_food_log", {"date": "2026-01-01"}, _CONTEXT)
    assert "אין רישומים" in reply


def test_the_food_log_tool_returns_items_and_totals_as_json():
    tools.run_tool("log_meal", {"items": [_eggs()]}, _CONTEXT)
    day = json.loads(tools.run_tool("get_food_log", {}, _CONTEXT))

    assert day["totals"]["calories"] == 155
    assert day["items"][0]["item"] == "ביצים"


def test_an_unknown_metric_costs_the_model_a_turn_and_not_the_conversation():
    reply = tools.run_tool("log_measurement", {"metric": "mood", "value": 7}, _CONTEXT)

    assert "לא קיים" in reply
    assert "weight" in reply  # the reply has to say what it may use instead


def test_a_measurement_logged_through_the_tool_comes_back_through_the_tool():
    tools.run_tool("log_measurement", {"metric": "weight", "value": 80.5}, _CONTEXT)
    readings = json.loads(tools.run_tool("get_measurements", {"metric": "weight"}, _CONTEXT))

    assert readings[0]["value"] == 80.5
