"""Every tool the agent can call: each function next to the schema that tells the
model when to call it, plus the dispatch that runs one by name.

graph.py knows only TOOLS and run_tool, so adding a tool is a change to this file
and nowhere else.
"""

import json
from dataclasses import dataclass
from datetime import datetime

import httpx

from coach_agent import log_store, profile_store
from coach_agent.clock import TIMEZONE as _TIMEZONE
from coach_agent.config import USDA_API_KEY


@dataclass(frozen=True)
class ToolContext:
    """Who this tool call is being run for.

    Every tool used to be a pure function of its input, which was true right up
    until one of them had to write to a particular person's file. Passed to every
    handler rather than only the ones that care, so the day a second field is
    needed it is added here and nowhere else.
    """

    user_key: str

# --- Nutrition (USDA FoodData Central) ---------------------------------------

_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

_NUTRIENT_NAMES = {
    "calories_per_100g": "Energy",
    "protein_per_100g": "Protein",
    "carbs_per_100g": "Carbohydrate, by difference",
    "fat_per_100g": "Total lipid (fat)",
}

_NUTRITION_TOOL = {
    "name": "lookup_food",
    "description": (
        "מחפש ערכים תזונתיים (קלוריות, חלבון, פחמימות, שומן ל-100 גרם) של מוצר מזון "
        "דרך USDA FoodData Central — לפי שם (query) או לפי ברקוד (barcode). "
        "כשמחפשים לפי שם למזון גנרי/לא-ממותג, לנסח את query בסגנון התיאורים של "
        "USDA (למשל 'banana, raw' ולא סתם 'banana') לתוצאות מדויקות יותר."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "שם המוצר לחיפוש, למשל 'banana, raw'"},
            "barcode": {"type": "string", "description": "מספר ברקוד (UPC/EAN) של המוצר"},
        },
    },
}


def _extract_food(food: dict) -> dict:
    values = {key: None for key in _NUTRIENT_NAMES}
    for nutrient in food.get("foodNutrients", []):
        for key, target_name in _NUTRIENT_NAMES.items():
            if nutrient.get("nutrientName") == target_name:
                values[key] = nutrient.get("value")
    return {
        "name": food.get("description") or "לא ידוע",
        "brand": food.get("brandOwner") or food.get("brandName") or "לא ידוע",
        **values,
    }


def _search(query: str, page_size: int) -> list[dict]:
    response = httpx.get(
        _SEARCH_URL,
        params={"api_key": USDA_API_KEY, "query": query, "pageSize": page_size},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("foods", [])


def search_by_name(query: str) -> dict | None:
    foods = _search(query, page_size=1)
    if not foods:
        return None
    return _extract_food(foods[0])


def search_by_barcode(barcode: str) -> dict | None:
    normalized = barcode.lstrip("0")
    for food in _search(barcode, page_size=10):
        gtin = (food.get("gtinUpc") or "").lstrip("0")
        if gtin == normalized:
            return _extract_food(food)
    return None


# --- Clock -------------------------------------------------------------------

# datetime.weekday() is Monday-based, so index 0 is Monday.
_HEBREW_WEEKDAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]

_CLOCK_TOOL = {
    "name": "get_current_datetime",
    "description": (
        "מחזיר את התאריך והשעה הנוכחיים באזור הזמן של המשתמש (ישראל), כולל יום בשבוע. "
        "לקרוא לו בכל פעם שהתשובה תלויה בזמן הנוכחי — למשל 'מה אכלתי היום', "
        "'כמה ימים נשארו עד', או כל התייחסות ל'עכשיו'/'אתמול'/'מחר'. "
        "אין להסתמך על ידע פנימי לגבי התאריך — הוא לא מעודכן."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def get_current_datetime() -> dict[str, str]:
    now = datetime.now(_TIMEZONE)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": _HEBREW_WEEKDAYS[now.weekday()],
        "timezone": "Asia/Jerusalem",
    }


# --- Food log and measurements -----------------------------------------------

# A figure the model produced from its own sense of what a bagel "usually" has is
# indistinguishable, once stored, from one the USDA returned. Said in the
# description because there is no way to tell them apart at write time.
_NUMBERS_NOTE = (
    "ערכים תזונתיים: להשלים ממה ש-lookup_food החזיר. "
    "אם לא נבדק ואין ערך אמיתי — להשאיר ריק ולא לנחש מספר."
)

_LOG_MEAL_TOOL = {
    "name": "log_meal",
    "description": (
        "רושם ביומן התזונה מה המתאמן אכל. "
        "כל פריטי אותה ארוחה בקריאה אחת — כל פריט נשמר בשורה משלו עם אותה שעה. "
        + _NUMBERS_NOTE
        + " מה שנאמר ואין לו שדה משלו — איך הרגיש אחרי, עם מי אכל, למה דילג — "
        "הולך ל-notes כטקסט חופשי. אין להמציא שמות שדות."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "פריטי הארוחה, כל אחד בנפרד.",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "שם המזון, במילים של המתאמן.",
                        },
                        "grams": {"type": "number", "description": "כמות בגרמים, אם ידועה."},
                        "calories": {"type": "number"},
                        "protein": {"type": "number"},
                        "carbs": {"type": "number"},
                        "fat": {"type": "number"},
                        "notes": {
                            "type": "string",
                            "description": "מה שנאמר על הפריט ואין לו שדה משלו.",
                        },
                    },
                    "required": ["item"],
                },
            },
            "meal_type": {
                "type": "string",
                "enum": list(log_store.MEAL_TYPES),
                "description": "סוג הארוחה. להשמיט אם לא ברור מהשיחה.",
            },
            "eaten_at": {
                "type": "string",
                "description": (
                    "מתי נאכל, בפורמט ISO-8601 (למשל 2026-09-18T08:30). "
                    "ברירת המחדל היא עכשיו — לשלוח רק כשמדובר במשהו שנאכל קודם."
                ),
            },
        },
        "required": ["items"],
    },
}

_FOOD_LOG_TOOL = {
    "name": "get_food_log",
    "description": (
        "מחזיר מה המתאמן אכל ביום מסוים, כולל סיכום קלוריות ומאקרו. "
        "לקרוא לו לפני כל תשובה על מה נאכל — גם על היום הנוכחי — ולא להסתמך על "
        "מה שנאמר קודם בשיחה, כי ייתכן שנרשמו דברים בשיחה אחרת."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "תאריך בפורמט YYYY-MM-DD. ברירת מחדל: היום.",
            }
        },
    },
}

_LOG_MEASUREMENT_TOOL = {
    "name": "log_measurement",
    "description": (
        "רושם מדידה של המתאמן. רק המדדים שברשימה — אין להמציא מדד חדש. "
        "מה שאין לו מדד נרשם כ-notes על ארוחה, או נשאר בפרופיל."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "enum": list(log_store.METRIC_UNITS),
                "description": "weight = משקל, body_fat = אחוז שומן.",
            },
            "value": {"type": "number", "description": "הערך המספרי בלבד."},
            "measured_at": {
                "type": "string",
                "description": "ISO-8601. ברירת מחדל: עכשיו.",
            },
            "notes": {"type": "string", "description": "הקשר שנאמר על המדידה."},
        },
        "required": ["metric", "value"],
    },
}

_MEASUREMENTS_TOOL = {
    "name": "get_measurements",
    "description": (
        "מחזיר את המדידות של המתאמן במדד מסוים, מהישנה לחדשה, לצורך מגמה. "
        "לקרוא לו לפני כל אמירה על שינוי במשקל או באחוז שומן."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": list(log_store.METRIC_UNITS)},
            "days": {
                "type": "integer",
                "description": "כמה ימים אחורה. להשמיט כדי לקבל הכל.",
            },
        },
        "required": ["metric"],
    },
}

_UNKNOWN_METRIC_REPLY = "המדד {metric} לא קיים. המדדים האפשריים: {options}."


def _run_log_meal(tool_input: dict, context: ToolContext) -> str:
    written = log_store.log_meal(
        context.user_key,
        tool_input.get("items", []),
        meal_type=tool_input.get("meal_type"),
        eaten_at=tool_input.get("eaten_at"),
    )
    if not written:
        # Reported back rather than raised, like an unknown section name: the call
        # was malformed and the model can correct it on the next turn.
        return "לא נרשם כלום — אף פריט לא הגיע עם שם."
    return f"נרשמו {written} פריטים ביומן."


def _run_get_food_log(tool_input: dict, context: ToolContext) -> str:
    date = tool_input.get("date") or get_current_datetime()["date"]
    day = log_store.food_log_for_day(context.user_key, date)
    if not day["items"]:
        # An empty day and a day nobody logged look identical from here, and the
        # difference changes what the coach should say — so it is spelled out
        # instead of left as an empty list for the model to interpret.
        return f"אין רישומים ביומן בתאריך {date}."
    return json.dumps(day, ensure_ascii=False)


def _run_log_measurement(tool_input: dict, context: ToolContext) -> str:
    metric = tool_input.get("metric")
    try:
        log_store.log_measurement(
            context.user_key,
            metric,
            tool_input["value"],
            measured_at=tool_input.get("measured_at"),
            notes=tool_input.get("notes"),
        )
    except log_store.UnknownMetric:
        return _UNKNOWN_METRIC_REPLY.format(
            metric=metric, options=", ".join(log_store.METRIC_UNITS)
        )
    return f"נרשם: {metric} = {tool_input['value']} {log_store.METRIC_UNITS[metric]}."


def _run_get_measurements(tool_input: dict, context: ToolContext) -> str:
    metric = tool_input.get("metric")
    try:
        readings = log_store.measurements_for(
            context.user_key, metric, days=tool_input.get("days")
        )
    except log_store.UnknownMetric:
        return _UNKNOWN_METRIC_REPLY.format(
            metric=metric, options=", ".join(log_store.METRIC_UNITS)
        )
    if not readings:
        return f"אין מדידות של {metric} ליומן הזה."
    return json.dumps(readings, ensure_ascii=False)


# --- Intake: the two documents -----------------------------------------------

_SAVE_SECTION_TOOL = {
    "name": "save_trainee_section",
    "description": (
        "שומר סקשן אחד או יותר בפרופיל המתאמן. לקרוא בסוף כל בלוק באינטק, אחרי שהמתאמן "
        "אישר את הסיכום — ובכל פעם שמידע קיים מתעדכן או מתברר כלא מדויק. "
        "התוכן שנשלח מחליף את הסקשן במלואו, אז יש לכלול את כל השדות שלו, "
        "גם כאלה שלא השתנו. שדה שנשאל ואין עליו תשובה נכתב 'לא ידוע' ולא 'לבירור'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "description": "הסקשנים לעדכון בקריאה אחת.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": list(profile_store.SECTIONS)},
                        "content": {
                            "type": "string",
                            "description": (
                                "גוף הסקשן ב-Markdown, שורת בולט לכל שדה "
                                "בפורמט '- **שם השדה:** ערך'. בלי כותרת ## — היא כבר במסמך."
                            ),
                        },
                    },
                    "required": ["name", "content"],
                },
            }
        },
        "required": ["sections"],
    },
}

# The closed vocabulary of the coaching-preferences document. Enums and not free
# text: this document is pasted into the system prompt, so a free-text field here
# is a channel from whatever the user types straight into the instruction layer.
_COACH_PREFERENCE_FIELDS = {
    "coach_name": {
        "type": "string",
        "description": (
            "השם שהמתאמן בחר לקרוא לך. נשאל בפתיחת האינטק ונשמר מיד — "
            "לא ממתין ל-finish_intake. אם המתאמן לא רצה לבחור שם, להשאיר ריק."
        ),
    },
    "address_form": {
        "type": "string",
        "enum": ["זכר", "נקבה", "ניטרלית"],
        "description": "לשון הפנייה למתאמן.",
    },
    "tone": {
        "type": "string",
        "enum": ["תומך-רך", "ישיר-תכל'ס", "משלב"],
        "description": "נגזר מסגנון השיחה, לא נשאל ישירות. ברירת מחדל: משלב.",
    },
    "reply_length": {
        "type": "string",
        "enum": ["קצר מאוד", "בינוני"],
        "description": "נגזר מאורך התשובות של המתאמן. ברירת מחדל: קצר מאוד.",
    },
    "initiative": {
        "type": "string",
        "enum": ["יומי", "2-3 בשבוע", "רק כשאני פונה"],
        "description": "נשאל ישירות בבלוק 3.",
    },
    "quiet_hours": {
        "type": "string",
        "description": "טווח שעות שבו אין ליזום הודעה, בפורמט 'HH:MM-HH:MM'. נשאל ישירות.",
    },
    "numbers_stance": {
        "type": "string",
        "enum": ["לעודד ספירת קלוריות", "משקל שבועי בלבד", "להימנע ממספרים"],
        "description": "נגזר. דיווח על אכילה רגשית או בושה סביב אוכל מכריע ל'להימנע ממספרים'.",
    },
    "what_helps_when_down": {
        "type": "string",
        "enum": ["עידוד", "עובדות ופתרון", "מרחב בלי הערות"],
        "description": "נשאל ישירות בבלוק 3.",
    },
    "topics_to_avoid": {
        "type": "array",
        "items": {"type": "string"},
        "description": "נושאים שאין להעלות ביוזמת המאמן, למשל 'משקל', 'מראה'. נגזר.",
    },
    "expectations_quote": {
        "type": "string",
        "description": "מה המתאמן מצפה מהמאמן, כציטוט ישיר מדבריו ולא בסיכום שלך.",
    },
}

_FINISH_INTAKE_TOOL = {
    "name": "finish_intake",
    "description": (
        "סוגר את האינטק: כותב את מסמך העדפות הליווי ומעביר את המתאמן לליווי רגיל. "
        "לקרוא פעם אחת בלבד, בסוף בלוק 3, אחרי שכל הסקשנים של הפרופיל נשמרו "
        "ואחרי שהמתאמן אישר את ההעדפות שהוצגו לו. "
        "אין להודיע למתאמן על סיום לפני שהכלי הזה החזיר הצלחה."
    ),
    "input_schema": {
        "type": "object",
        "properties": _COACH_PREFERENCE_FIELDS,
        "required": [
            "address_form",
            "tone",
            "reply_length",
            "initiative",
            "numbers_stance",
            "what_helps_when_down",
        ],
    },
}

_UPDATE_PREFERENCES_TOOL = {
    "name": "update_coach_preferences",
    "description": (
        "מעדכן שדות בודדים בהעדפות הליווי במהלך הליווי השוטף — למשל כשהמתאמן מבקש "
        "'תפסיק להציף אותי' או 'אל תדבר איתי על משקל'. "
        "לשלוח רק את השדות שמשתנים; השאר נשארים כמו שהם."
    ),
    "input_schema": {"type": "object", "properties": _COACH_PREFERENCE_FIELDS},
}

_STOP_INTAKE_TOOL = {
    "name": "stop_intake",
    "description": (
        "עוצר את האינטק בלי להשלים אותו, כשעולה סימן להפרעת אכילה. "
        "לא מסלול של סיום עם הערה — מסלול אחר לגמרי: המסמכים לא נכתבים והליווי לא מתחיל."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "מה נצפה, בתיאור עובדתי של מה שנאמר. בלי לנקוב בשם של הפרעה.",
            }
        },
        "required": ["reason"],
    },
}


def _run_save_section(tool_input: dict, context: ToolContext) -> str:
    saved = []
    for section in tool_input.get("sections", []):
        name = section.get("name")
        if name not in profile_store.SECTIONS:
            # Reported back rather than raised, same as an unknown tool name: one
            # wasted turn the model can correct, not a dead conversation.
            return f"הסקשן '{name}' לא קיים. הסקשנים האפשריים: {', '.join(profile_store.SECTIONS)}."
        profile_store.replace_section(context.user_key, name, section.get("content", ""))
        saved.append(name)
    if not saved:
        return "לא נשלח אף סקשן — אין מה לשמור."
    return f"נשמר: {', '.join(saved)}."


def _run_finish_intake(tool_input: dict, context: ToolContext) -> str:
    untouched = profile_store.untouched_sections(context.user_key)
    if untouched:
        return (
            f"האינטק לא נסגר: הסקשנים {', '.join(untouched)} עדיין ריקים לגמרי. "
            "יש להשלים אותם ולשמור אותם לפני סגירה. אל תודיע למתאמן שסיימתם."
        )

    # Order matters: preferences first, status last. If the second write fails,
    # the user stays in intake and the tool gets called again — which rewrites
    # the same preferences harmlessly. The reverse order would leave a coached
    # user with no preferences document at all.
    profile_store.write_coach_preferences(context.user_key, tool_input)
    today = get_current_datetime()["date"]
    profile_store.replace_section(context.user_key, "יומן", f"- **{today}:** יצירת המסמך באינטק.")
    profile_store.set_status(context.user_key, profile_store.STATUS_ACTIVE)

    still_open = profile_store.open_fields(context.user_key)
    open_note = (
        f" נשארו שדות פתוחים בסקשנים: {', '.join(still_open)} — לציין בקצרה שתחזור אליהם."
        if still_open
        else ""
    )
    # The instruction to close arrives in the tool result and not in the system
    # prompt, so the model cannot produce a farewell before the save succeeded:
    # it has not been told how to write one yet.
    return (
        "שני המסמכים נשמרו והליווי מתחיל." + open_note + " כעת כתוב הודעת סיום אחת, "
        "בשלושה חלקים ובלי כותרות: (1) מה נשמר, בשתי שורות ולא המסמך המלא; "
        "(2) שהמסמך חי — אם משהו לא מדויק או משתנה, שיגיד ותעדכן; "
        "(3) צעד קונקרטי אחד לביצוע היום, קטן ונגזר ממה שנאמר בשיחה."
    )


def _run_stop_intake(tool_input: dict, context: ToolContext) -> str:
    reason = tool_input.get("reason", "").strip() or "לא צוין"
    profile_store.replace_section(
        context.user_key, "דגלים", f"- **האינטק נעצר.** {reason}"
    )
    profile_store.set_status(context.user_key, profile_store.STATUS_BLOCKED)
    return (
        "האינטק נעצר והסיבה נרשמה. כעת כתוב הודעה אחת, קצרה וחמה: תודה על השיתוף, "
        "שזה לא משהו שנכון שתלווה, ושיש אנשי מקצוע שזה בדיוק התחום שלהם — "
        "רופא/ה, פסיכולוג/ית או דיאטן/ית קליני/ת עם התמחות בהפרעות אכילה. "
        "בלי לאבחן, בלי לנקוב בשם של הפרעה, ובלי להמשיך לשאול שאלות אינטק."
    )


def _run_update_preferences(tool_input: dict, context: ToolContext) -> str:
    if not tool_input:
        return "לא נשלח אף שדה לעדכון."
    profile_store.write_coach_preferences(context.user_key, tool_input)
    return f"עודכן: {', '.join(tool_input)}. השינוי ייכנס לתוקף בהודעה הבאה."


# --- Registry ----------------------------------------------------------------


def _run_nutrition(tool_input: dict, context: ToolContext) -> str:
    if tool_input.get("barcode"):
        result = search_by_barcode(tool_input["barcode"])
    else:
        result = search_by_name(tool_input.get("query", ""))
    if not result:
        return "לא נמצא מוצר מתאים."
    return json.dumps(result, ensure_ascii=False)


def _run_clock(tool_input: dict, context: ToolContext) -> str:
    return json.dumps(get_current_datetime(), ensure_ascii=False)


# Two sets, because the two modes are two different jobs. The interviewer cannot
# look up calories and the coach cannot close an intake — not as a rule it is
# asked to follow, but as a tool it was never handed.
COACH_TOOLS = [
    _NUTRITION_TOOL,
    _CLOCK_TOOL,
    _UPDATE_PREFERENCES_TOOL,
    _LOG_MEAL_TOOL,
    _FOOD_LOG_TOOL,
    _LOG_MEASUREMENT_TOOL,
    _MEASUREMENTS_TOOL,
]
# update_coach_preferences is in both sets. During the intake it is what saves
# the coach's name the moment it is chosen, in the opening, rather than holding
# it in the conversation until finish_intake — a name picked and then lost to a
# restart is the least personal thing this bot could do.
INTAKE_TOOLS = [
    _SAVE_SECTION_TOOL,
    _UPDATE_PREFERENCES_TOOL,
    _FINISH_INTAKE_TOOL,
    _STOP_INTAKE_TOOL,
    _CLOCK_TOOL,
]

# Keyed off the schema itself, so a tool's name is written once and the schema and
# its handler cannot drift apart.
_HANDLERS = {
    _NUTRITION_TOOL["name"]: _run_nutrition,
    _CLOCK_TOOL["name"]: _run_clock,
    _SAVE_SECTION_TOOL["name"]: _run_save_section,
    _FINISH_INTAKE_TOOL["name"]: _run_finish_intake,
    _STOP_INTAKE_TOOL["name"]: _run_stop_intake,
    _UPDATE_PREFERENCES_TOOL["name"]: _run_update_preferences,
    _LOG_MEAL_TOOL["name"]: _run_log_meal,
    _FOOD_LOG_TOOL["name"]: _run_get_food_log,
    _LOG_MEASUREMENT_TOOL["name"]: _run_log_measurement,
    _MEASUREMENTS_TOOL["name"]: _run_get_measurements,
}


def run_tool(name: str, tool_input: dict, context: ToolContext) -> str:
    """Result text for one tool_use block.

    An unknown name is reported back to the model rather than raised: a tool the
    model hallucinated should cost one wasted turn, not kill the conversation.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"הכלי '{name}' לא קיים."
    return handler(tool_input, context)
