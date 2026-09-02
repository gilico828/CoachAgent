import httpx

from coach_agent.config import USDA_API_KEY

_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

_NUTRIENT_NAMES = {
    "calories_per_100g": "Energy",
    "protein_per_100g": "Protein",
    "carbs_per_100g": "Carbohydrate, by difference",
    "fat_per_100g": "Total lipid (fat)",
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
