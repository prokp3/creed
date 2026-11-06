"""Looking up a barcode in Open Food Facts, a free and open database of packaged food.

The server asks on the phone's behalf, so the phone needs no extra permissions and Open Food Facts never sees who's
asking. What comes back is a draft for you to check and save: label data is often incomplete or wrong.
Only documented product fields are read (API v2: /api/v2/product/{barcode}).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://world.openfoodfacts.org/api/v2/product/"
FIELDS = "product_name,product_name_en,brands,nutriments,serving_quantity,product_quantity_unit,quantity"
# Open Food Facts asks every app to name itself. No personal details go in here.
USER_AGENT = "Creed/0.1 (personal food logger; https://github.com/prokp3/creed)"
TIMEOUT_SECONDS = 8
BARCODE = re.compile(r"^\d{6,14}$")


class LookupFailed(RuntimeError):
    """Open Food Facts couldn't be reached or answered strangely. Not the same as "not found"."""


def valid(code: str) -> bool:
    return bool(BARCODE.match(code))


def fetch(code: str) -> dict[str, Any] | None:
    """The product's raw fields, or None when Open Food Facts doesn't know the barcode."""
    request = urllib.request.Request(f"{BASE_URL}{code}?fields={FIELDS}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise LookupFailed(f"Open Food Facts answered {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise LookupFailed("Couldn't reach Open Food Facts.") from None
    if not isinstance(body, dict) or body.get("status") != 1 or not isinstance(body.get("product"), dict):
        return None
    return body["product"]


def _value(nutriments: dict[str, Any], key: str) -> float | None:
    value = nutriments.get(key)
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def draft(code: str, product: dict[str, Any]) -> dict[str, Any]:
    """A food record to review, per 100 g (or per 100 ml for drinks), with notes on anything worked out."""
    nutriments = product.get("nutriments") if isinstance(product.get("nutriments"), dict) else {}
    notes = ["From Open Food Facts. Check it against the label."]
    values: dict[str, float] = {}

    kcal = _value(nutriments, "energy-kcal_100g")
    if kcal is None and (kj := _value(nutriments, "energy-kj_100g")) is not None:
        kcal = kj / 4.184
        notes.append("Calories worked out from kJ (kJ ÷ 4.184).")
    if kcal is not None:
        values["kcal"] = kcal
    for key, field in (("protein", "proteins_100g"), ("carbs", "carbohydrates_100g"), ("fat", "fat_100g")):
        if (v := _value(nutriments, field)) is not None:
            values[key] = v
    # Open Food Facts gives minerals per 100 g in grams; Creed uses milligrams.
    sodium = _value(nutriments, "sodium_100g")
    if sodium is None and (salt := _value(nutriments, "salt_100g")) is not None:
        sodium = salt / 2.5
        notes.append("Sodium worked out from salt (salt ÷ 2.5).")
    if sodium is not None:
        values["sodium"] = sodium * 1000
    for key, field in (("potassium", "potassium_100g"), ("magnesium", "magnesium_100g")):
        if (v := _value(nutriments, field)) is not None:
            values[key] = v * 1000

    unit_text = str(product.get("product_quantity_unit") or "").lower()
    base = "ml" if unit_text == "ml" or str(product.get("quantity") or "").lower().strip().endswith("ml") else "g"
    units: dict[str, float] = {}
    serving = _value(product, "serving_quantity")
    if serving and 0 < serving <= 100_000:
        units["serving"] = round(serving, 1)
    name = str(product.get("product_name") or product.get("product_name_en") or "").strip() or f"Product {code}"
    brand = str(product.get("brands") or "").split(",")[0].strip() or None
    return {
        "name": name[:80], "brand": brand[:80] if brand else None, "barcode": code, "base": base,
        "nutrients": values, "units": units, "default_unit": "serving" if units else base,
        "source": "barcode", "notes": " ".join(notes)[:500],
    }
