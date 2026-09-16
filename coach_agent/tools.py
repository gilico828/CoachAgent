"""Every tool the agent can call: each function next to the schema that tells the
model when to call it, plus the dispatch that runs one by name.

graph.py knows only TOOLS and run_tool, so adding a tool is a change to this file
and nowhere else.
"""

import json
import httpx

from coach_agent.config import USDA_API_KEY

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


# --- Registry ----------------------------------------------------------------


def _run_nutrition(tool_input: dict) -> str:
    if tool_input.get("barcode"):
        result = search_by_barcode(tool_input["barcode"])
    else:
        result = search_by_name(tool_input.get("query", ""))
    if not result:
        return "לא נמצא מוצר מתאים."
    return json.dumps(result, ensure_ascii=False)


TOOLS = [_NUTRITION_TOOL]

# Keyed off the schema itself, so a tool's name is written once and the schema and
# its handler cannot drift apart.
_HANDLERS = {
    _NUTRITION_TOOL["name"]: _run_nutrition,
}


def run_tool(name: str, tool_input: dict) -> str:
    """Result text for one tool_use block.

    An unknown name is reported back to the model rather than raised: a tool the
    model hallucinated should cost one wasted turn, not kill the conversation.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"הכלי '{name}' לא קיים."
    return handler(tool_input)
