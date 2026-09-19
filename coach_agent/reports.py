"""The two pages the coach can hand the trainee, rendered from the log.

Two fixed templates in `templates/`, and nothing here decides what they look
like — only what goes in the holes. The model never writes a line of this HTML:
it picks a metric or a date, and the same page comes out every time.

Charts are SVG written by hand rather than matplotlib. Two reasons, both
practical: matplotlib does no bidi, so every Hebrew label would come out
reversed without `python-bidi` and a font shipped in the image, and a line of
fourteen points does not justify the dependency that would fix it. SVG inside
the page gets RTL, real text and resolution from the browser for free.

This module imports nothing from `tools` or `graph`, which is what lets both of
them import it.
"""

import html
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Template

from coach_agent.clock import TIMEZONE, now_local

_TEMPLATES = Path(__file__).parent / "templates"

# Read per render, like the prompt files: editing a template on the server takes
# effect on the next report instead of on the next rebuild.
_MEASUREMENTS_TEMPLATE = _TEMPLATES / "measurements.html"
_FOOD_DAY_TEMPLATE = _TEMPLATES / "food_day.html"

# Month and weekday names for the page's own headings. tools.py keeps its own
# weekday list for `get_current_datetime`, and the two are not shared on
# purpose: that one is a value handed to the model, this one is UI text, and
# they are free to diverge the day one of them should.
_MONTHS = (
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
)
_WEEKDAYS = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")

_MINUS = "−"  # a real minus sign; the hyphen reads as punctuation in RTL


@dataclass(frozen=True)
class Document:
    """One file on its way back to the user, as the channel layer will send it.

    The outbound mirror of `graph.ImageAttachment`: bytes, a type, and a name,
    with nothing in it that knows what Telegram is.
    """

    filename: str
    data: bytes
    media_type: str


# --- small formatting helpers ------------------------------------------------


def _number(value: float | int) -> str:
    """The figure as a person reads it: 155 and 82.3, never 155.0."""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _signed(value: float) -> str:
    """A delta with a real minus sign, wrapped so RTL does not move it.

    Without the `dir="ltr"`, a leading sign in an RTL line is reordered to the
    other end of the number and "−0.3" is read as "0.3−".
    """
    sign = _MINUS if value < 0 else "+"
    return f'<span dir="ltr">{sign}{_number(abs(value))}</span>'


def _esc(value) -> str:
    """Everything that came from a person or from the model goes through here.

    Item names and notes are free text from a conversation. Without this, a meal
    logged as `<script>` is script in a file the trainee opens in their browser.
    """
    return html.escape("" if value is None else str(value))


def _parse(stamp: str) -> datetime:
    """A stored timestamp as a datetime, tolerant of a missing offset.

    log_store writes local ISO-8601 with an offset, but a row written before a
    normalisation bug was fixed, or by hand, may carry none — and a naive value
    mixed with aware ones raises on the first comparison.
    """
    moment = datetime.fromisoformat(stamp)
    return moment.replace(tzinfo=TIMEZONE) if moment.tzinfo is None else moment


def _day_month(moment: datetime) -> str:
    return f"{moment.day:02d}.{moment.month:02d}"


def _long_date(moment: datetime) -> str:
    return f"{moment.day} ב{_MONTHS[moment.month - 1]}"


# --- chart -------------------------------------------------------------------

# One geometry for both charts, so the two stack as small multiples rather than
# as two unrelated pictures. The value axis sits on the right (Hebrew reads from
# there) while time still runs left to right, which is the convention every
# Hebrew publication uses for a time series.
_VIEW_W = 640.0
_X0, _X1 = 24.0, 560.0
_TICK_X = 636.0
_TOP = 20.0

_NICE_STEPS = (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0)


def _domain(values: list[float]) -> tuple[float, float, float]:
    """A rounded (low, high, step) that contains every value with room to spare.

    Padded before rounding so a reading never sits exactly on the frame, and
    guarded for the two degenerate cases that a real log produces on week one:
    a single reading, and a run of identical ones. Both give a zero span, and a
    zero span is a division by zero two lines later.
    """
    low, high = min(values), max(values)
    span = high - low
    if span == 0:
        span = max(abs(high) * 0.04, 1.0)
        low, high = low - span / 2, high + span / 2
        span = high - low
    low -= span * 0.04
    high += span * 0.04

    span = high - low
    step = next((s for s in _NICE_STEPS if span / s <= 4), _NICE_STEPS[-1])
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def _ticks(low: float, high: float, step: float) -> list[float]:
    count = int(round((high - low) / step))
    return [low + step * i for i in range(count + 1)]


def _time_labels(t0: datetime, t1: datetime, x_of) -> list[tuple[float, str]]:
    """Month names where the range spans months, plain dates where it does not.

    A month name on a two-week range would print "ספטמבר" once and say nothing;
    a date at each end of a three-month range would waste the axis. So the
    labels follow the span instead of a fixed rule.
    """
    starts = []
    year, month = t0.year, t0.month
    while (year, month) <= (t1.year, t1.month):
        start = datetime(year, month, 1, tzinfo=t0.tzinfo)
        if start >= t0:
            starts.append((x_of(start), _MONTHS[month - 1]))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    if len(starts) >= 2:
        # The opening month begins before the first reading, so its label is
        # pinned to the axis start rather than dropped. A first reading late in
        # its month then puts that label almost on top of the next one, so
        # anything closer than a label's width is dropped instead of overlapped.
        kept: list[tuple[float, str]] = []
        for x, text in [(_X0, _MONTHS[t0.month - 1])] + starts:
            if not kept or x - kept[-1][0] >= 46:
                kept.append((x, text))
        return kept
    if t0 == t1:
        return [(_X0, _day_month(t0))]
    return [(_X0, _day_month(t0)), (_X1, _day_month(t1))]


def _chart(
    points: list[tuple[datetime, float]],
    *,
    color: str,
    t0: datetime,
    t1: datetime,
    bottom: float,
    unit: str,
    label: str,
    goal: float | None = None,
) -> str:
    """One series against one scale. Never two — see the note in the template."""
    values = [value for _, value in points] + ([goal] if goal is not None else [])
    low, high, step = _domain(values)

    def x_of(moment: datetime) -> float:
        if t1 == t0:
            return (_X0 + _X1) / 2
        ratio = (moment.timestamp() - t0.timestamp()) / (t1.timestamp() - t0.timestamp())
        return _X0 + ratio * (_X1 - _X0)

    def y_of(value: float) -> float:
        return bottom - (value - low) / (high - low) * (bottom - _TOP)

    parts: list[str] = []
    ticks = _ticks(low, high, step)
    for tick in ticks:
        y = y_of(tick)
        line = "axis-line" if tick == ticks[0] else "grid-line"
        parts.append(f'<line class="{line}" x1="{_X0}" y1="{y:.1f}" x2="{_X1}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="tick" x="{_TICK_X}" y="{y + 4:.1f}" text-anchor="end">{_number(tick)}</text>'
        )

    if goal is not None:
        y = y_of(goal)
        parts.append(f'<line class="goal" x1="{_X0}" y1="{y:.1f}" x2="{_X1}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="goal-label" x="{_X0}" y="{y - 5:.1f}">יעד · {_number(goal)}</text>'
        )

    placed = [(x_of(moment), y_of(value), value) for moment, value in points]
    if len(placed) > 1:
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in placed)
        parts.append(f'<polyline class="series" stroke="{color}" points="{line}"/>')
    for index, (x, y, _) in enumerate(placed):
        radius = 4.5 if index == len(placed) - 1 else 3.5
        parts.append(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>')

    # Only the first and last point get a number. A value on every point is the
    # table below the chart, printed on top of the chart.
    first_x, first_y, first_v = placed[0]
    last_x, last_y, last_v = placed[-1]
    if len(placed) > 1:
        parts.append(
            f'<text class="startpoint" x="{first_x:.1f}" y="{first_y - 9:.1f}">'
            f"{_number(first_v)}{unit}</text>"
        )
    # Below the point normally, above it when the point sits in the lower half:
    # a label under a low endpoint lands in the band the month names occupy.
    below = last_y < (bottom + _TOP) / 2
    label_y = last_y + 18 if below else last_y - 9
    anchor = "end" if len(placed) > 1 else "middle"
    parts.append(
        f'<text class="endpoint" x="{last_x:.1f}" y="{label_y:.1f}" '
        f'text-anchor="{anchor}" fill="{color}">{_number(last_v)}{unit}</text>'
    )

    months_y = bottom + 22
    for x, text in _time_labels(t0, t1, x_of):
        anchor = "end" if x >= _X1 else "start"
        parts.append(f'<text class="month" x="{x:.1f}" y="{months_y:.1f}" text-anchor="{anchor}">{text}</text>')

    view_h = bottom + 48
    body = "\n      ".join(parts)
    return (
        f'<svg viewBox="0 0 {_VIEW_W:.0f} {view_h:.0f}" role="img" aria-label="{_esc(label)}">\n'
        f"      {body}\n    </svg>"
    )


# --- page 1: measurements ----------------------------------------------------

_METRIC_TITLES = {"weight": "משקל", "body_fat": "אחוז שומן"}
_METRIC_UNITS = {"weight": '', "body_fat": "%"}
_METRIC_COLORS = {"weight": "var(--weight)", "body_fat": "var(--fat)"}

# Charts of different heights, because the second series is the smaller story
# and an equal box would claim otherwise.
_WEIGHT_BOTTOM = 176.0
_FAT_BOTTOM = 130.0


def _stat(label: str, value: str, unit: str = "", toward_goal: bool = False) -> str:
    klass = ' class="down"' if toward_goal else ""
    suffix = f'<span class="u">{_esc(unit)}</span>' if unit else ""
    return (
        f'<div class="stat"><dt>{_esc(label)}</dt>'
        f"<dd{klass}>{value}{suffix}</dd></div>"
    )


def _measurement_stats(readings: list[dict], unit: str, goal: float | None) -> str:
    current = readings[-1]["value"]
    cards = [_stat("ערך נוכחי" if unit != 'ק"ג' else "משקל נוכחי", _number(current), unit)]

    if len(readings) > 1:
        since_start = current - readings[0]["value"]
        since_prev = current - readings[-2]["value"]
        # Green only when the change moves toward a goal the trainee actually
        # stated. Without one, down is not automatically good — somebody adding
        # muscle is not failing — so the number is left to speak for itself.
        toward = goal is not None and abs(current - goal) < abs(readings[0]["value"] - goal)
        cards.append(_stat("מאז ההתחלה", _signed(since_start), unit, toward))
        cards.append(_stat("מהמדידה הקודמת", _signed(since_prev), unit))

    if goal is not None:
        cards.append(_stat("נותר עד היעד", _number(abs(goal - current)), unit))

    # The column count travels with the row: one reading has no delta to show
    # and not everyone named a goal, so this is anywhere from one card to four.
    return f'<dl class="stats cols-{len(cards)}">{"".join(cards)}</dl>'


def _figure(metric: str, readings: list[dict], t0: datetime, t1: datetime, goal: float | None) -> str:
    title = _METRIC_TITLES[metric]
    unit = _METRIC_UNITS[metric]
    points = [(_parse(row["measured_at"]), row["value"]) for row in readings]

    note = f'יעד {_number(goal)} {readings[0]["unit"]}' if goal is not None else ""
    if not note and len(readings) > 1:
        note = f'{_signed(readings[-1]["value"] - readings[0]["value"])} מאז ההתחלה'

    chart = _chart(
        points,
        color=_METRIC_COLORS[metric],
        t0=t0,
        t1=t1,
        bottom=_WEIGHT_BOTTOM if metric == "weight" else _FAT_BOTTOM,
        unit=unit,
        label=f"גרף {title}: {len(points)} מדידות, מ-{_number(points[0][1])} ל-{_number(points[-1][1])}",
        goal=goal,
    )
    return (
        f"<figure>\n"
        f'    <figcaption><span class="swatch" style="background: {_METRIC_COLORS[metric]}"></span>'
        f'<span class="fig-title">{title}</span>'
        f'<span class="fig-note">{note}</span></figcaption>\n'
        f"    {chart}\n  </figure>"
    )


def _readings_table(metric: str, readings: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{_day_month(_parse(row['measured_at']))}</td>"
        f'<td class="v">{_number(row["value"])}</td></tr>'
        for row in readings
    )
    unit = _esc(readings[0]["unit"])
    return (
        f"<table><caption>{_METRIC_TITLES[metric]} ({unit})</caption>"
        f'<thead><tr><th scope="col">נמדד</th><th scope="col" class="v">ערך</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def render_measurements(
    weight: list[dict],
    body_fat: list[dict],
    goal_weight: float | None = None,
) -> str:
    """The trend page. At least one of the two lists must be non-empty.

    An empty pair is not rendered as an empty page: the tool checks first and
    says so in a sentence, because a page with nothing on it is worse than no
    page at all.
    """
    series = [(metric, rows) for metric, rows in (("weight", weight), ("body_fat", body_fat)) if rows]
    if not series:
        raise ValueError("render_measurements needs at least one reading")

    moments = [_parse(row["measured_at"]) for _, rows in series for row in rows]
    t0, t1 = min(moments), max(moments)

    # The trend the page leads with, and the one the stat row describes.
    lead_metric, lead_rows = series[0]
    goal = goal_weight if lead_metric == "weight" else None

    counts = ", ".join(f'{len(rows)} מדידות {_METRIC_TITLES[metric]}' for metric, rows in series)
    span = _long_date(t0) if t0.date() == t1.date() else f"{_long_date(t0)} – {_long_date(t1)}"

    figures = "\n\n  ".join(
        _figure(metric, rows, t0, t1, goal_weight if metric == "weight" else None)
        for metric, rows in series
    )
    tables = "".join(_readings_table(metric, rows) for metric, rows in series)

    footnote = (
        f"הדף נוצר ב-{_long_date(now_local())} {now_local().year}, {now_local():%H:%M}. "
        "מוצג בו רק מה שנרשם ביומן — מדידה שלא דווחה לא מופיעה כאן ולא משפיעה על המגמה."
    )
    if goal_weight is not None:
        footnote += f'<br>משקל היעד ({_number(goal_weight)} ק"ג) נלקח מסקשן "נתונים" בפרופיל.'

    return Template(_MEASUREMENTS_TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        title=" ו".join(_METRIC_TITLES[metric] for metric, _ in series),
        range_line=f"{span} {t1.year} · {counts}",
        stats=_measurement_stats(lead_rows, lead_rows[0]["unit"], goal),
        figures=figures,
        readings=f'<details><summary>כל המדידות</summary><div class="tables">{tables}</div></details>',
        footnote=footnote,
    )


# --- page 2: one day of the food log -----------------------------------------

_MACROS = (
    ("protein", "חלבון", 4, "var(--protein)"),
    ("carbs", "פחמימות", 4, "var(--carbs)"),
    ("fat", "שומן", 9, "var(--fat)"),
)
_NO_VALUE = "לא נבדק"


def _meal_groups(items: list[dict]) -> list[tuple[str | None, str, list[dict]]]:
    """The day's rows back into meals.

    log_meal writes a row per item and lets them share a timestamp and a type,
    so the meal survives only as that shared pair — this reassembles it. The
    rows arrive ordered by time, so consecutive matches are one meal.
    """
    groups: list[tuple[str | None, str, list[dict]]] = []
    for item in items:
        key = (item.get("meal_type"), item["eaten_at"])
        if groups and (groups[-1][0], groups[-1][1]) == key:
            groups[-1][2].append(item)
        else:
            groups.append((key[0], key[1], [item]))
    return groups


def _item_row(item: dict) -> str:
    grams = f'<span class="g">{_number(item["grams"])} גרם</span>' if item.get("grams") else ""
    calories = item.get("calories")
    if calories is None:
        value = f'<span class="kcal none">{_NO_VALUE}</span>'
    else:
        value = f'<span class="kcal">{_number(calories)}</span>'
    note = f'<span class="note">{_esc(item["notes"])}</span>' if item.get("notes") else ""
    return (
        f'<div class="item"><span class="name">{_esc(item["item"])}</span>{grams}'
        f'<span class="leader"></span>{value}{note}</div>'
    )


def _meal_block(meal_type: str | None, eaten_at: str, items: list[dict]) -> str:
    subtotal = sum(item["calories"] or 0 for item in items)
    time = f'<span class="meal-time">{_parse(eaten_at):%H:%M}</span>'
    total = (
        f'<span class="meal-sum">{_number(subtotal)} <small>קק"ל</small></span>'
        if subtotal
        else ""
    )
    rows = "\n      ".join(_item_row(item) for item in items)
    return (
        f'<section class="meal">\n'
        f'      <div class="meal-head"><span class="meal-name">{_esc(meal_type or "ארוחה")}</span>'
        f"{time}{total}</div>\n      {rows}\n    </section>"
    )


def _summary_block(totals: dict) -> str:
    calories = totals.get("calories") or 0
    # The bar is drawn from the macros' own energy, not from the calorie column:
    # the two disagree whenever an item carries calories but no breakdown, and a
    # bar whose segments do not add up to its own width is the worse lie.
    energy = {key: (totals.get(key) or 0) * per_gram for key, _, per_gram, _ in _MACROS}
    total_energy = sum(energy.values())

    head = (
        f'<div class="total-head"><span class="total-num">{calories:,.0f}</span>'
        f'<span class="total-unit">קק"ל</span>'
        f'<span class="total-say">ערכים משוערים</span></div>'
    )
    if not total_energy:
        return f'<section class="total">{head}</section>'

    bar = "".join(
        f'<span style="flex: {energy[key] / total_energy * 100:.1f}; background: {color}"></span>'
        for key, _, _, color in _MACROS
    )
    chips = "".join(
        f'<div class="macro"><span class="swatch" style="background: {color}"></span>'
        f'<span class="mlabel">{name}</span>'
        f'<span class="mval">{_number(totals.get(key) or 0)} ג\'</span>'
        f'<span class="mpct">{energy[key] / total_energy * 100:.0f}%</span></div>'
        for key, name, _, color in _MACROS
    )
    reading = ", ".join(
        f"{name} {energy[key] / total_energy * 100:.0f} אחוז" for key, name, _, _ in _MACROS
    )
    return (
        f'<section class="total">\n    {head}\n'
        f'    <div class="bar" role="img" aria-label="התפלגות הקלוריות: {reading}">{bar}</div>\n'
        f'    <div class="macros">{chips}</div>\n  </section>'
    )


def render_food_day(day: dict) -> str:
    """One day's page. `day` is exactly what log_store.food_log_for_day returns."""
    items = day["items"]
    if not items:
        raise ValueError("render_food_day needs at least one item")

    date = datetime.fromisoformat(day["date"]).replace(tzinfo=TIMEZONE)
    groups = _meal_groups(items)
    unpriced = [item["item"] for item in items if item.get("calories") is None]

    footnote = f"הדף נוצר ב-{_long_date(now_local())} {now_local().year}, {now_local():%H:%M}."
    if unpriced:
        names = ", ".join(f"<b>{_esc(name)}</b>" for name in unpriced)
        footnote += (
            f"<br>{names} — נרשמו בלי ערכים תזונתיים ולכן אינם נכללים בסיכום; "
            "עדיף ריק על מספר מנוחש."
        )
    footnote += "<br>הקלוריות והמאקרו הם הערכה לפי מה שנרשם ביומן, ולא מדידה."

    return Template(_FOOD_DAY_TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        title=f"{_WEEKDAYS[date.weekday()]}, {_long_date(date)}",
        sub_line=f"{len(groups)} ארוחות · {len(items)} פריטים",
        summary=_summary_block(day["totals"]),
        meals="\n\n    ".join(_meal_block(*group) for group in groups),
        footnote=footnote,
    )
