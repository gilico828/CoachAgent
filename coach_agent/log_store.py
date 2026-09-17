"""The tabular half of what the bot remembers: what was eaten, and what was measured.

One SQLite file, shared by everyone, with `user_key` on every row — not a
database per person. The isolation a separate file would have given for free is
bought here instead, by this module being the only place in the project that
writes SQL: every public function takes `user_key` first, and there is no way to
ask a question without saying whose answer it is.

The two tables are shaped differently on purpose. A meal is a *record* with a
closed set of nutrition fields — calories, protein, carbs, fat — identical for
everyone, so those are real columns. A measurement is an *observation*: a number,
a unit and a time, under a name. Those arrive open-endedly (weight and body fat
today, sleep or resting heart rate later), so the name is a value in a row rather
than a column in the schema: adding a metric is an INSERT, while adding a
nutrient would be a migration.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from coach_agent.clock import TIMEZONE, now_local

DB_PATH = Path(__file__).parent / "data" / "coach.db"

# What the agent may call a meal. Not enforced by the database — a meal type it
# has never heard of is worth storing rather than refusing — but offered to the
# model as an enum, so the same four words come back every time instead of
# "ארוחת בוקר" one day and "בוקר" the next.
MEAL_TYPES = ("בוקר", "צהריים", "ערב", "ביניים")

# The metric vocabulary, and the closed part of this module's contract. A name
# outside it is refused: left open, the same measurement arrives as `weight`,
# `body_weight` and `mishkal` across three conversations, each one stored
# successfully, and the trend query then returns a third of the truth without
# anything looking broken.
METRIC_UNITS = {
    "weight": 'ק"ג',
    "body_fat": "%",
}

# Columns one logged item may fill. Anything else the model sends is dropped
# rather than stored, the same way write_coach_preferences filters its input: the
# schema describes what a well-behaved call looks like, and this decides what a
# misbehaving one can leave behind.
_ITEM_FIELDS = ("item", "grams", "calories", "protein", "carbs", "fat", "notes")

# Applied in order; the file's own PRAGMA user_version says how many have run.
# Adding a column later means appending one entry here and nothing else — which
# is what makes `notes` below a waiting room rather than a dead end.
_MIGRATIONS = [
    """
    CREATE TABLE food_log (
        id         INTEGER PRIMARY KEY,
        user_key   TEXT NOT NULL,
        eaten_at   TEXT NOT NULL,
        meal_type  TEXT,
        item       TEXT NOT NULL,
        grams      REAL,
        calories   REAL,
        protein    REAL,
        carbs      REAL,
        fat        REAL,
        notes      TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_food_log_user_day ON food_log(user_key, eaten_at);

    CREATE TABLE measurements (
        id          INTEGER PRIMARY KEY,
        user_key    TEXT NOT NULL,
        measured_at TEXT NOT NULL,
        metric      TEXT NOT NULL,
        value       REAL NOT NULL,
        unit        TEXT NOT NULL,
        notes       TEXT,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX idx_measurements_user_metric
        ON measurements(user_key, metric, measured_at);
    """,
]


class UnknownMetric(Exception):
    """A metric name outside METRIC_UNITS — see the comment there for why it is refused."""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """A connection with the schema already current, closed when the block ends.

    Opened per call rather than held on the module. SQLite opens a local file in
    microseconds, and a long-lived connection would have to answer for the event
    loop it is touched from — python-telegram-bot is async, and `check_same_thread`
    is exactly the kind of flag that behaves in testing and bites on the server.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        # A reader no longer blocks a writer. It matters less for one bot than
        # for what it avoids: the rollback journal leaves a second file beside
        # the database that a careless backup copies without.
        conn.execute("PRAGMA journal_mode = WAL")
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(_MIGRATIONS)):
        conn.executescript(_MIGRATIONS[index])
        # Interpolated because PRAGMA takes no bound parameters. `index` is an int
        # from range() over a module constant, so there is nothing reachable here
        # from a caller.
        conn.execute(f"PRAGMA user_version = {index + 1}")


def _normalize_timestamp(value: str | None) -> str:
    """An ISO-8601 local timestamp, whatever shape the caller sent.

    Local and not UTC, because every question asked of this data is a question
    about a local day — "what did I eat today" — which a local string answers with
    a range comparison that stays right in both halves of the year. Storing UTC
    would push a shifting offset into every query instead.
    """
    if value is None:
        return now_local().isoformat(timespec="seconds")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TIMEZONE)
    return moment.isoformat(timespec="seconds")


def _day_bounds(date: str) -> tuple[str, str]:
    """The range covering one local day, as strings that compare correctly."""
    return f"{date}T00:00:00", f"{date}T23:59:59.999999"


# --- Food log ----------------------------------------------------------------


def log_meal(
    user_key: str,
    items: list[dict],
    meal_type: str | None = None,
    eaten_at: str | None = None,
) -> int:
    """Write one row per item, all sharing this meal's type and timestamp.

    A row per item and not per meal: the nutrition figures are per item, the
    lookup tool returns them per item, and "how much protein did I eat" is then a
    SUM rather than a parse. The meal itself survives as the timestamp its rows
    share.
    """
    timestamp = _normalize_timestamp(eaten_at)
    created = now_local().isoformat(timespec="seconds")
    rows = []
    for raw in items:
        name = str(raw.get("item") or "").strip()
        if not name:
            continue
        values = {field: raw.get(field) for field in _ITEM_FIELDS}
        values["item"] = name
        rows.append((user_key, timestamp, meal_type, created, *(values[f] for f in _ITEM_FIELDS)))

    if not rows:
        return 0

    columns = ", ".join(_ITEM_FIELDS)
    placeholders = ", ".join("?" for _ in _ITEM_FIELDS)
    with _connect() as conn:
        conn.executemany(
            f"INSERT INTO food_log (user_key, eaten_at, meal_type, created_at, {columns}) "
            f"VALUES (?, ?, ?, ?, {placeholders})",
            rows,
        )
    return len(rows)


def food_log_for_day(user_key: str, date: str) -> dict:
    """Everything this user ate on one local day, with the totals already summed.

    Summed here and not left to the model: it has the rows in front of it and will
    add them up itself, slightly wrong, with complete confidence.
    """
    start, end = _day_bounds(date)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT eaten_at, meal_type, item, grams, calories, protein, carbs, fat, notes "
            "FROM food_log WHERE user_key = ? AND eaten_at BETWEEN ? AND ? "
            "ORDER BY eaten_at, id",
            (user_key, start, end),
        ).fetchall()

    items = [dict(row) for row in rows]
    totals = {
        field: round(sum(item[field] or 0 for item in items), 1)
        for field in ("calories", "protein", "carbs", "fat")
    }
    return {"date": date, "items": items, "totals": totals}


# --- Measurements ------------------------------------------------------------


def log_measurement(
    user_key: str,
    metric: str,
    value: float,
    unit: str | None = None,
    measured_at: str | None = None,
    notes: str | None = None,
) -> None:
    if metric not in METRIC_UNITS:
        raise UnknownMetric(metric)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO measurements "
            "(user_key, measured_at, metric, value, unit, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_key,
                _normalize_timestamp(measured_at),
                metric,
                float(value),
                unit or METRIC_UNITS[metric],
                notes,
                now_local().isoformat(timespec="seconds"),
            ),
        )


def measurements_for(user_key: str, metric: str, days: int | None = None) -> list[dict]:
    """This user's readings of one metric, oldest first so a trend reads in order."""
    if metric not in METRIC_UNITS:
        raise UnknownMetric(metric)

    query = (
        "SELECT measured_at, metric, value, unit, notes FROM measurements "
        "WHERE user_key = ? AND metric = ?"
    )
    params: list = [user_key, metric]
    if days is not None:
        since = (now_local() - timedelta(days=days)).isoformat(timespec="seconds")
        query += " AND measured_at >= ?"
        params.append(since)
    query += " ORDER BY measured_at"

    with _connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
