"""The two pages the coach sends, and the tools that build them.

Two tests here matter more than the rest. The escaping one: an item name is free
text from a conversation, and the page it lands in is opened in the trainee's own
browser. And the self-contained one: the file is sent through Telegram with
nothing behind it, so a single external reference turns the report into a page
that is blank on a phone with no signal — a failure that never shows up locally.

The rest are the shapes a real log takes in its first week: no readings at all,
exactly one, several identical ones, and an item logged without ever having been
looked up.
"""

import pytest

from coach_agent import log_store, profile_store, reports, tools

_USER = "telegram_1"
_DAY = "2026-09-19"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(log_store, "DB_PATH", tmp_path / "coach.db")
    monkeypatch.setattr(profile_store, "USERS_DIR", tmp_path)
    return tmp_path


def _context() -> tools.ToolContext:
    return tools.ToolContext(user_key=_USER)


def _reading(day: int, value: float, metric: str = "weight") -> dict:
    return {
        "measured_at": f"2026-09-{day:02d}T08:00:00+03:00",
        "metric": metric,
        "value": value,
        "unit": 'ק"ג' if metric == "weight" else "%",
        "notes": None,
    }


def _day(*items: dict) -> dict:
    totals = {
        field: round(sum(item.get(field) or 0 for item in items), 1)
        for field in ("calories", "protein", "carbs", "fat")
    }
    return {"date": _DAY, "items": list(items), "totals": totals}


def _item(name: str, **overrides) -> dict:
    return {
        "eaten_at": f"{_DAY}T08:15:00+03:00",
        "meal_type": "בוקר",
        "item": name,
        "grams": 100,
        "calories": 155,
        "protein": 13,
        "carbs": 1,
        "fat": 11,
        "notes": None,
        **overrides,
    }


def _profile(body: str) -> None:
    (profile_store.USERS_DIR / f"{_USER}.md").write_text(
        f"<!-- status: active -->\n\n## נתונים\n\n{body}\n", encoding="utf-8"
    )


# --- The two properties that make the file sendable at all -------------------


def test_an_item_name_cannot_smuggle_markup_into_the_page():
    """The name came from a conversation and the page opens in a browser."""
    page = reports.render_food_day(_day(_item("<script>alert(1)</script>")))

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_note_is_escaped_too():
    page = reports.render_food_day(_day(_item("ביצים", notes="<img onerror=x>")))

    assert "<img onerror=x>" not in page
    assert "&lt;img onerror=x&gt;" in page


@pytest.mark.parametrize(
    "page",
    [
        reports.render_measurements([_reading(1, 90.0), _reading(8, 89.0)], [], 83.0),
        reports.render_food_day(
            {
                "date": _DAY,
                "items": [
                    {
                        "eaten_at": f"{_DAY}T08:15:00+03:00",
                        "meal_type": "בוקר",
                        "item": "ביצים",
                        "grams": 100,
                        "calories": 155,
                        "protein": 13,
                        "carbs": 1,
                        "fat": 11,
                        "notes": None,
                    }
                ],
                "totals": {"calories": 155, "protein": 13, "carbs": 1, "fat": 11},
            }
        ),
    ],
)
def test_the_page_reaches_for_nothing_on_the_network(page):
    """No font, no stylesheet, no script, no image. The file is sent as itself,
    and a phone with no signal has to render all of it."""
    assert "http" not in page


# --- Shapes a real log takes -------------------------------------------------


def test_a_single_reading_is_a_point_and_not_a_crash():
    page = reports.render_measurements([_reading(1, 90.0)], [], None)

    assert "<polyline" not in page  # one point is not a line
    assert "90" in page


def test_identical_readings_do_not_divide_by_zero():
    """Three days of the same number is a flat line, not an empty scale."""
    same = [_reading(day, 90.0) for day in (1, 8, 15)]

    page = reports.render_measurements(same, [], None)

    assert "<polyline" in page


def test_the_stat_row_asks_for_as_many_columns_as_it_has_cards():
    """Otherwise the leftover grid tracks show up as empty grey cells."""
    one = reports.render_measurements([_reading(1, 90.0)], [], None)
    full = reports.render_measurements([_reading(1, 90.0), _reading(8, 89.0)], [], 83.0)

    assert 'class="stats cols-1"' in one
    assert 'class="stats cols-4"' in full


def test_an_item_never_looked_up_is_not_reported_as_zero():
    """log_meal stores a blank when nothing was checked, and the page has to keep
    "unknown" and "none" apart — the totals are wrong either way, but only one of
    them says so."""
    page = reports.render_food_day(
        _day(_item("ביצים"), _item("יוגורט", calories=None, protein=None, carbs=None, fat=None))
    )

    assert "לא נבדק" in page
    assert "יוגורט" in page  # named in the footnote as excluded


def test_a_page_with_nothing_on_it_is_refused_rather_than_rendered():
    with pytest.raises(ValueError):
        reports.render_measurements([], [], 83.0)
    with pytest.raises(ValueError):
        reports.render_food_day(_day())


def test_body_fat_alone_still_makes_a_page():
    """The goal is a weight, so a body-fat-only page must not try to draw it."""
    page = reports.render_measurements([], [_reading(1, 33.0, "body_fat")], 83.0)

    assert "אחוז שומן" in page
    assert "יעד · 83" not in page


# --- The goal weight, parsed out of prose ------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ('- **משקל יעד:** 83 ק"ג', 83.0),
        ('- משקל יעד : 78.5 ק"ג', 78.5),
        ("- **משקל יעד:** לבירור", None),
        ("- **משקל יעד:** לא ידוע", None),
        ('- **משקל נוכחי:** 91 ק"ג', None),
        # A year on the goal line is not a goal. Without the plausibility guard
        # this draws a target line and says the trainee is 1,940 kg away.
        ("- **משקל יעד:** להגיע עד מרץ 2027", None),
    ],
)
def test_goal_weight_survives_how_the_profile_is_actually_written(line, expected):
    _profile(line)

    assert profile_store.goal_weight(_USER) == expected


def test_a_missing_profile_costs_the_report_a_dashed_line_and_nothing_else():
    assert profile_store.goal_weight("nobody_at_all") is None


# --- The tools ---------------------------------------------------------------


def test_an_empty_log_produces_a_sentence_and_no_file():
    """An empty page is worse than no page: it says the log is broken rather than
    that nothing was ever reported."""
    context = _context()

    result = tools.run_tool("send_measurements_report", {}, context)

    assert context.outbox == []
    assert "לא נשלח דף" in result


def test_an_empty_day_produces_a_sentence_and_no_file():
    context = _context()

    result = tools.run_tool("send_food_day_report", {"date": _DAY}, context)

    assert context.outbox == []
    assert _DAY in result


def test_the_measurements_tool_leaves_one_html_document_in_the_outbox():
    _profile('- **משקל יעד:** 83 ק"ג')
    log_store.log_measurement(_USER, "weight", 90.0, measured_at="2026-09-01T08:00:00+03:00")
    log_store.log_measurement(_USER, "weight", 88.4, measured_at="2026-09-13T08:00:00+03:00")
    context = _context()

    tools.run_tool("send_measurements_report", {}, context)

    (document,) = context.outbox
    assert document.media_type == "text/html"
    assert document.filename.endswith(".html")
    assert "יעד · 83" in document.data.decode("utf-8")


def test_the_food_tool_leaves_one_html_document_in_the_outbox():
    log_store.log_meal(
        _USER,
        [{"item": "ביצים", "grams": 100, "calories": 155}],
        meal_type="בוקר",
        eaten_at=f"{_DAY}T08:15:00+03:00",
    )
    context = _context()

    tools.run_tool("send_food_day_report", {"date": _DAY}, context)

    (document,) = context.outbox
    assert document.filename == f"food-{_DAY}.html"
    assert "ביצים" in document.data.decode("utf-8")


def test_a_date_the_model_invented_cannot_shape_the_filename():
    """Nothing downstream is harmed by an odd date, but a file called
    `2026-09-19/..` landing in somebody's downloads folder is not worth finding
    out about."""
    log_store.log_meal(_USER, [{"item": "ביצים"}], eaten_at=f"{_DAY}T08:15:00+03:00")
    context = _context()

    tools.run_tool("send_food_day_report", {"date": f"../../{_DAY}"}, context)

    for document in context.outbox:
        assert "/" not in document.filename


def test_the_report_tools_do_not_stop_for_approval():
    """The approval gate exists for writes. These two only read."""
    assert not tools.needs_confirmation("send_measurements_report")
    assert not tools.needs_confirmation("send_food_day_report")


def test_the_interviewer_is_not_handed_a_report_to_send():
    """During the intake there is nothing logged yet to draw."""
    intake = {tool["name"] for tool in tools.INTAKE_TOOLS}

    assert not {"send_measurements_report", "send_food_day_report"} & intake
