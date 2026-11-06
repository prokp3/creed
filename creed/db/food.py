"""Food logger reads and writes, each for one user.

Privacy: every function takes the user it acts for. Its queries name that user, and they also run as the database
role creed_member with the user's id set for the transaction (see 0005_food.sql), so row-level security limits
them to that user's rows even if a query forgot to. Garmin data isn't food data: it's read as the server's own role,
and only for the owner.

Sync: ids come from the phone, so a repeated request can't make a second row; the newest change to a record wins;
and a deletion beats any edit, however new. Each write says what happened (applied, stale, deleted or missing), so
the phone can drop a change from its queue either way.

Callers commit after these functions return, never in the middle of one: committing ends the transaction that the
user's id and role were set for.
"""
from __future__ import annotations

import functools
import uuid
import weakref
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg import errors, sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from creed.food import nutrition, targets
from creed.food.nutrition import BASES, BUILT_IN, QUICK_ADD, InvalidFood

APPLIED = "applied"  # Saved.
STALE = "stale"  # A newer change was already saved, so this one was ignored.
DELETED = "deleted"  # The record was deleted, which beats any edit.
MISSING = "missing"  # Nothing to delete.

KINDS = ("preset", "quick", "import")
SOURCES = ("seed", "manual", "barcode", "import")
MAX_PRESET_ITEMS = 50
MAX_ENTRIES_PER_REQUEST = 200
MEMBER_ROLE = "creed_member"

FOOD_SELECT = (
    "select f.id, f.name, f.brand, f.barcode, f.base, f.nutrients, f.default_unit, f.favourite, f.source, f.notes, "
    "f.changed_at, f.deleted_at, coalesce((select jsonb_object_agg(u.name, u.amount) from food_unit u "
    "where u.user_id = f.user_id and u.food_id = f.id), '{}'::jsonb) as units from food f"
)
ENTRY_COLUMNS = ("id", "group_id", "kind", "preset_id", "meal_label", "food_id", "logged_at", "utc_offset_minutes",
                 "local_date", "quantity", "unit", "base_amount", "food_name", "food_brand", "base",
                 "nutrients_per_100", "unit_amounts", "changed_at")


# ---------------------------------------------------------------- checking what the phone sends

def _id(value: Any, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise InvalidFood(f"{label} must be an id made by the app.") from None


def _optional_id(value: Any, label: str) -> str | None:
    return None if value is None else _id(value, label)


def moment(value: Any, label: str = "Time") -> datetime:
    """A time with its UTC offset, so the day it falls on is the day it was where you were."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            raise InvalidFood(f"{label} must be a date and time.") from None
    if parsed.utcoffset() is None:
        raise InvalidFood(f"{label} must include its time zone.")
    return parsed


def _text(value: Any, label: str, longest: int, optional: bool = False) -> str | None:
    if value is None or (optional and isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise InvalidFood(f"{label} is needed.")
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= longest:
        raise InvalidFood(f"{label} must be 1 to {longest} characters.")
    return value.strip()


def _flag(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidFood(f"{label} must be on or off.")
    return value


# ---------------------------------------------------------------- acting for one user

# Which user each connection is acting for right now, and how many calls deep.
_ACTING: weakref.WeakKeyDictionary[psycopg.Connection, list[Any]] = weakref.WeakKeyDictionary()


@contextmanager
def as_user(conn: psycopg.Connection, user_id: str) -> Iterator[str]:
    """Run food queries as creed_member for this user until the block ends. Nesting for the same user is fine."""
    uid = _id(user_id, "User")
    acting = _ACTING.get(conn)
    if acting is not None:
        if acting[0] != uid:
            raise RuntimeError("This connection is already acting for another user.")
        acting[1] += 1
        try:
            yield uid
        finally:
            acting[1] -= 1
        return
    conn.execute("select set_config('creed.user_id', %s, true), set_config('role', %s, true)", (uid, MEMBER_ROLE))
    _ACTING[conn] = [uid, 1]
    try:
        yield uid
    finally:
        del _ACTING[conn]
        # After an error the transaction is rolled back, which undoes both settings anyway.
        if conn.info.transaction_status == TransactionStatus.INTRANS:
            conn.execute("select set_config('role', 'none', true), set_config('creed.user_id', '', true)")


def _for_user[F: Callable[..., Any]](fn: F) -> F:
    """Every public food function takes (conn, user_id, ...) and runs as that user."""
    @functools.wraps(fn)
    def wrapper(conn: psycopg.Connection, user_id: str, *args: Any, **kwargs: Any) -> Any:
        with as_user(conn, user_id) as uid:
            return fn(conn, uid, *args, **kwargs)
    return wrapper  # type: ignore[return-value]


def _not_acting(conn: psycopg.Connection) -> None:
    """Garmin tables have no policies for creed_member, so reading them as it would silently find nothing."""
    if conn in _ACTING:
        raise RuntimeError("Read Garmin data before or after acting for a user, not during.")


@contextmanager
def _savepoint(conn: psycopg.Connection) -> Iterator[None]:
    """Undo just this write if it fails, leaving the rest of the request's transaction usable."""
    conn.execute("savepoint food_write")
    try:
        yield
    except Exception:
        conn.execute("rollback to savepoint food_write")
        raise
    conn.execute("release savepoint food_write")


# ---------------------------------------------------------------- the shared upsert

def _upsert(conn: psycopg.Connection, table: str, rows: list[dict[str, Any]], key: tuple[str, ...],
            update: Iterable[str], soft_delete: bool = True) -> set[tuple[Any, ...]]:
    """Insert, or update only where the stored change is older and the record isn't deleted. Returns keys saved."""
    if not rows:
        return set()
    columns = tuple(rows[0])
    guard = sql.SQL("{t}.changed_at <= excluded.changed_at").format(t=sql.Identifier(table))
    if soft_delete:
        guard = sql.SQL("{} and {}.deleted_at is null").format(guard, sql.Identifier(table))
    statement = sql.SQL(
        "insert into {t} ({cols}) values {values} on conflict ({key}) do update set {sets}, updated_at = now() "
        "where {guard} returning {key}"
    ).format(
        t=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        values=sql.SQL(", ").join(
            sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() * len(columns))) for _ in rows
        ),
        key=sql.SQL(", ").join(map(sql.Identifier, key)),
        sets=sql.SQL(", ").join(sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in update),
        guard=guard,
    )
    params = [row[c] for row in rows for c in columns]
    return {tuple(str(r[k]) if isinstance(r[k], uuid.UUID) else r[k] for k in key)
            for r in conn.execute(statement, params).fetchall()}


def _why_not(conn: psycopg.Connection, table: str, user_id: str, record_id: str) -> str:
    row = conn.execute(sql.SQL("select deleted_at from {} where user_id = %s and id = %s").format(
        sql.Identifier(table)), (user_id, record_id)).fetchone()
    return DELETED if row and row["deleted_at"] is not None else STALE


def _soft_delete(conn: psycopg.Connection, table: str, user_id: str, ids: list[str], at: datetime,
                 extra: str = "") -> set[str]:
    rows = conn.execute(
        sql.SQL("update {t} set deleted_at = coalesce(deleted_at, %s), updated_at = now() "
                "where user_id = %s and id = any(%s) {x} returning id").format(t=sql.Identifier(table), x=sql.SQL(extra)),
        (at, user_id, ids),
    ).fetchall()
    return {str(r["id"]) for r in rows}


# ---------------------------------------------------------------- nutrients

@_for_user
def nutrient_units(conn: psycopg.Connection, user_id: str) -> dict[str, str]:
    """This user's live nutrients and their units."""
    rows = conn.execute("select id, unit from food_nutrient where user_id = %s and deleted_at is null",
                        (user_id,)).fetchall()
    return {r["id"]: r["unit"] for r in rows}


@_for_user
def list_nutrients(conn: psycopg.Connection, user_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        "select id, name, unit, built_in, sort_order, changed_at from food_nutrient "
        "where user_id = %s and deleted_at is null order by sort_order, lower(name)",
        (user_id,),
    ).fetchall()


@_for_user
def save_nutrient(conn: psycopg.Connection, user_id: str, record: Mapping[str, Any], changed_at: datetime) -> str:
    """Add a custom nutrient or rename any. A unit is fixed once made, since changing it would change stored values."""
    nutrient_id = record.get("id")
    if nutrient_id not in BUILT_IN:
        nutrient_id = _id(nutrient_id, "Nutrient")
    name = _text(record.get("name"), "Name", 40)
    unit = _text(record.get("unit"), "Unit", 12)
    clash = conn.execute(
        "select 1 from food_nutrient where user_id = %s and deleted_at is null and lower(name) = lower(%s) "
        "and id <> %s",
        (user_id, name, nutrient_id),
    ).fetchone()
    if clash:
        raise InvalidFood(f"You already have a nutrient called {name}.")
    order = conn.execute("select coalesce(max(sort_order), -1) + 1 as next from food_nutrient where user_id = %s",
                         (user_id,)).fetchone()["next"]
    saved = _upsert(conn, "food_nutrient",
                    [{"user_id": user_id, "id": nutrient_id, "name": name, "unit": unit, "built_in": False,
                      "sort_order": order, "changed_at": moment(changed_at)}],
                    ("user_id", "id"), update=("name", "changed_at"))
    return APPLIED if saved else _why_not(conn, "food_nutrient", user_id, nutrient_id)


@_for_user
def delete_nutrient(conn: psycopg.Connection, user_id: str, nutrient_id: str, at: datetime) -> str:
    """Custom ones only. Values already stored for it stay in the database but are no longer shown or counted."""
    if nutrient_id in BUILT_IN:
        raise InvalidFood("Built-in nutrients can be renamed but not deleted.")
    done = _soft_delete(conn, "food_nutrient", user_id, [_id(nutrient_id, "Nutrient")], moment(at),
                        "and not built_in")
    return APPLIED if done else MISSING


# ---------------------------------------------------------------- foods

@_for_user
def clean_food(conn: psycopg.Connection, user_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """A food ready to save. Values typed in per unit (`values_per`) are turned into values per 100 of the base."""
    base = record.get("base")
    if base not in BASES:
        raise InvalidFood("A food is measured in g or ml.")
    units = nutrition.clean_units(record.get("units") or {}, base)
    known = nutrient_units(conn, user_id)
    # Names and numbers first. Limits apply to values per 100, so a big serving isn't refused before converting.
    typed = nutrition.clean_nutrients(record.get("nutrients") or {}, {k: "any" for k in known})
    per = record.get("values_per", base)
    if per != base:
        typed = nutrition.per_100_from_unit(typed, nutrition.unit_amount(per, base, units))
    nutrients = nutrition.clean_nutrients(typed, known)
    default_unit = record.get("default_unit") or base
    nutrition.unit_amount(default_unit, base, units)
    barcode = record.get("barcode") or None
    if barcode is not None and (not isinstance(barcode, str) or not barcode.isdigit() or not 6 <= len(barcode) <= 14):
        raise InvalidFood("A barcode is 6 to 14 digits.")
    source = record.get("source", "manual")
    if source not in SOURCES:
        raise InvalidFood("Unknown food source.")
    return {
        "id": _id(record.get("id"), "Food"),
        "name": _text(record.get("name"), "Name", 80),
        "brand": _text(record.get("brand"), "Brand", 80, optional=True),
        "barcode": barcode,
        "base": base,
        "nutrients": nutrients,
        "default_unit": default_unit,
        "favourite": _flag(record.get("favourite", False), "Favourite"),
        "source": source,
        "notes": _text(record.get("notes"), "Notes", 500, optional=True),
        "units": units,
    }


@_for_user
def save_food(conn: psycopg.Connection, user_id: str, record: Mapping[str, Any], changed_at: datetime) -> str:
    food = clean_food(conn, user_id, record)
    units = food.pop("units")
    row = {"user_id": user_id, **food, "nutrients": Jsonb(food["nutrients"]), "changed_at": moment(changed_at)}
    try:
        with _savepoint(conn):
            saved = _upsert(conn, "food", [row], ("user_id", "id"),
                            update=("name", "brand", "barcode", "base", "nutrients", "default_unit", "favourite",
                                    "notes", "changed_at"))
    except errors.UniqueViolation:
        raise InvalidFood("Another food already has this barcode.") from None
    if not saved:
        return _why_not(conn, "food", user_id, food["id"])
    conn.execute("delete from food_unit where user_id = %s and food_id = %s", (user_id, food["id"]))
    if units:
        conn.execute(
            sql.SQL("insert into food_unit (user_id, food_id, name, amount) values {}").format(
                sql.SQL(", ").join(sql.SQL("(%s, %s, %s, %s)") for _ in units)
            ),
            [v for name, amount in units.items() for v in (user_id, food["id"], name, amount)],
        )
    return APPLIED


@_for_user
def delete_food(conn: psycopg.Connection, user_id: str, food_id: str, at: datetime) -> str:
    """Past entries keep their own copy, and presets that use it say so."""
    return APPLIED if _soft_delete(conn, "food", user_id, [_id(food_id, "Food")], moment(at)) else MISSING


def _food_row(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "id": str(row["id"])}


@_for_user
def get_food(conn: psycopg.Connection, user_id: str, food_id: str) -> dict[str, Any] | None:
    """Deleted foods too, so an old entry or preset can still be explained."""
    row = conn.execute(FOOD_SELECT + " where f.user_id = %s and f.id = %s",
                       (user_id, _id(food_id, "Food"))).fetchone()
    return _food_row(row) if row else None


@_for_user
def list_foods(conn: psycopg.Connection, user_id: str, search: str | None = None,
               limit: int = 200) -> list[dict[str, Any]]:
    """Live foods, favourites first, then by name. Search matches anywhere in the name or brand."""
    pattern = f"%{search.strip()}%" if search and search.strip() else None
    rows = conn.execute(
        FOOD_SELECT + " where f.user_id = %(u)s and f.deleted_at is null and (%(p)s::text is null "
        "or f.name ilike %(p)s or f.brand ilike %(p)s) order by f.favourite desc, lower(f.name) limit %(l)s",
        {"u": user_id, "p": pattern, "l": limit},
    ).fetchall()
    return [_food_row(r) for r in rows]


@_for_user
def recent_food_ids(conn: psycopg.Connection, user_id: str, limit: int = 10) -> list[str]:
    """Live foods by when you last logged them."""
    rows = conn.execute(
        "select e.food_id from food_log_entry e join food f on f.user_id = e.user_id and f.id = e.food_id "
        "where e.user_id = %s and e.deleted_at is null and f.deleted_at is null "
        "group by e.food_id order by max(e.logged_at) desc limit %s",
        (user_id, limit),
    ).fetchall()
    return [str(r["food_id"]) for r in rows]


@_for_user
def find_by_barcode(conn: psycopg.Connection, user_id: str, barcode: str) -> dict[str, Any] | None:
    row = conn.execute(FOOD_SELECT + " where f.user_id = %s and f.barcode = %s and f.deleted_at is null",
                       (user_id, barcode)).fetchone()
    return _food_row(row) if row else None


# ---------------------------------------------------------------- presets

@_for_user
def save_preset(conn: psycopg.Connection, user_id: str, record: Mapping[str, Any], changed_at: datetime) -> str:
    preset_id = _id(record.get("id"), "Preset")
    name = _text(record.get("name"), "Name", 40)
    items = record.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PRESET_ITEMS:
        raise InvalidFood(f"A preset needs 1 to {MAX_PRESET_ITEMS} foods.")
    if not all(isinstance(item, Mapping) for item in items):
        raise InvalidFood("Each preset item needs a food and a quantity.")
    wanted = [_id(item.get("food_id"), "Food") for item in items]
    foods = {r["id"]: r for r in map(_food_row, conn.execute(
        FOOD_SELECT + " where f.user_id = %s and f.id = any(%s::uuid[]) and f.deleted_at is null",
        (user_id, wanted)).fetchall())}
    cleaned = []
    for food_id, item in zip(wanted, items):
        food = foods.get(food_id)
        if food is None:
            raise InvalidFood("A food in this preset isn't in your library.")
        unit = item.get("unit") or food["default_unit"]
        quantity = nutrition.check_quantity(item.get("quantity"))
        nutrition.unit_amount(unit, food["base"], food["units"])
        cleaned.append((food_id, quantity, unit))
    existing = conn.execute("select sort_order from food_preset where user_id = %s and id = %s",
                            (user_id, preset_id)).fetchone()
    order = record.get("sort_order")
    if not isinstance(order, int) or isinstance(order, bool):
        order = existing["sort_order"] if existing else conn.execute(
            "select coalesce(max(sort_order), -1) + 1 as next from food_preset where user_id = %s",
            (user_id,)).fetchone()["next"]
    saved = _upsert(conn, "food_preset",
                    [{"user_id": user_id, "id": preset_id, "name": name, "sort_order": order,
                      "changed_at": moment(changed_at)}],
                    ("user_id", "id"), update=("name", "sort_order", "changed_at"))
    if not saved:
        return _why_not(conn, "food_preset", user_id, preset_id)
    conn.execute("delete from food_preset_item where user_id = %s and preset_id = %s", (user_id, preset_id))
    conn.execute(
        sql.SQL("insert into food_preset_item (user_id, preset_id, position, food_id, quantity, unit) "
                "values {}").format(sql.SQL(", ").join(sql.SQL("(%s, %s, %s, %s, %s, %s)") for _ in cleaned)),
        [v for position, (food_id, quantity, unit) in enumerate(cleaned)
         for v in (user_id, preset_id, position, food_id, quantity, unit)],
    )
    return APPLIED


@_for_user
def delete_preset(conn: psycopg.Connection, user_id: str, preset_id: str, at: datetime) -> str:
    """Entries it logged keep their meal name."""
    return APPLIED if _soft_delete(conn, "food_preset", user_id, [_id(preset_id, "Preset")], moment(at)) else MISSING


@_for_user
def reorder_presets(conn: psycopg.Connection, user_id: str, ids: list[str], changed_at: datetime) -> int:
    """Put presets in this order. Each one moves only if this is its newest change."""
    checked = [_id(i, "Preset") for i in ids]
    rows = conn.execute(
        "update food_preset p set sort_order = o.position, changed_at = %(at)s, updated_at = now() "
        "from unnest(%(ids)s::uuid[]) with ordinality as o(id, position) "
        "where p.user_id = %(u)s and p.id = o.id and p.deleted_at is null and p.changed_at <= %(at)s returning p.id",
        {"u": user_id, "ids": checked, "at": moment(changed_at)},
    ).fetchall()
    return len(rows)


@_for_user
def list_presets(conn: psycopg.Connection, user_id: str) -> list[dict[str, Any]]:
    """Live presets in order, each with its foods. An item whose food was deleted says so."""
    presets = conn.execute(
        "select id, name, sort_order, changed_at from food_preset where user_id = %s and deleted_at is null "
        "order by sort_order, lower(name)",
        (user_id,),
    ).fetchall()
    items = conn.execute(
        "select i.preset_id, i.position, i.food_id, i.quantity, i.unit, f.name as food_name, "
        "f.deleted_at is not null as food_deleted from food_preset_item i "
        "join food f on f.user_id = i.user_id and f.id = i.food_id "
        "where i.user_id = %s order by i.preset_id, i.position",
        (user_id,),
    ).fetchall()
    by_preset: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_preset.setdefault(str(item["preset_id"]), []).append(
            {"food_id": str(item["food_id"]), "quantity": item["quantity"], "unit": item["unit"],
             "food_name": item["food_name"], "food_deleted": item["food_deleted"]}
        )
    return [{**p, "id": str(p["id"]), "items": by_preset.get(str(p["id"]), [])} for p in presets]


# ---------------------------------------------------------------- log entries

def clean_entry(record: Mapping[str, Any]) -> dict[str, Any]:
    """One entry with its own copy of the food. The phone makes the copy, so logging works offline."""
    kind = record.get("kind")
    if kind not in KINDS:
        raise InvalidFood("Unknown kind of entry.")
    logged_at = moment(record.get("logged_at"), "Time")
    base = record.get("base")
    if base not in BASES:
        raise InvalidFood("A food is measured in g or ml.")
    per_100 = record.get("nutrients_per_100")
    if not isinstance(per_100, Mapping) or not all(isinstance(k, str) for k in per_100):
        raise InvalidFood("An entry needs the food's values.")
    # The known-nutrient check is loose here: an entry made offline may name a nutrient deleted since.
    per_100 = nutrition.clean_nutrients(per_100, {k: "any" for k in per_100})
    units = nutrition.clean_units(record.get("unit_amounts") or {}, base)
    unit = record.get("unit") or base
    quantity = nutrition.check_quantity(record.get("quantity"))
    label = record.get("meal_label") or (QUICK_ADD if kind == "quick" else None)
    return {
        "id": _id(record.get("id"), "Entry"),
        "group_id": _id(record.get("group_id") or record.get("id"), "Group"),
        "kind": kind,
        "preset_id": _optional_id(record.get("preset_id"), "Preset"),
        "meal_label": _text(label, "Meal", 40),
        "food_id": _optional_id(record.get("food_id"), "Food"),
        "logged_at": logged_at,
        "utc_offset_minutes": int(logged_at.utcoffset().total_seconds() // 60),
        "local_date": logged_at.date(),
        "quantity": quantity,
        "unit": unit,
        "base_amount": nutrition.base_amount(quantity, unit, base, units),
        "food_name": _text(record.get("food_name"), "Food name", 80),
        "food_brand": _text(record.get("food_brand"), "Brand", 80, optional=True),
        "base": base,
        "nutrients_per_100": per_100,
        "unit_amounts": units,
    }


def entry_from_food(food: Mapping[str, Any], *, entry_id: str, group_id: str, kind: str, logged_at: datetime,
                    quantity: float, unit: str | None = None, meal_label: str | None = None,
                    preset_id: str | None = None) -> dict[str, Any]:
    """An entry record for a food from the library, as the phone builds one."""
    snap = nutrition.snapshot(food)
    return {
        "id": entry_id, "group_id": group_id, "kind": kind, "preset_id": preset_id, "meal_label": meal_label,
        "food_id": food["id"], "logged_at": logged_at, "quantity": quantity, "unit": unit or food["default_unit"],
        "food_name": snap.food_name, "food_brand": snap.food_brand, "base": snap.base,
        "nutrients_per_100": snap.nutrients_per_100, "unit_amounts": snap.unit_amounts,
    }


@_for_user
def save_entries(conn: psycopg.Connection, user_id: str, records: list[Mapping[str, Any]],
                 changed_at: datetime) -> dict[str, str]:
    """New entries or edits to existing ones, all checked before any is saved. Returns each id's outcome."""
    if not 1 <= len(records) <= MAX_ENTRIES_PER_REQUEST:
        raise InvalidFood(f"Send 1 to {MAX_ENTRIES_PER_REQUEST} entries at a time.")
    at = moment(changed_at)
    rows = [{**clean_entry(r), "changed_at": at} for r in records]
    if len({r["id"] for r in rows}) != len(rows):
        raise InvalidFood("The same entry was sent twice.")
    for row in rows:
        row["nutrients_per_100"] = Jsonb(row["nutrients_per_100"])
        row["unit_amounts"] = Jsonb(row["unit_amounts"])
    try:
        with _savepoint(conn):
            saved = _upsert(conn, "food_log_entry",
                            [{"user_id": user_id, **{c: r[c] for c in ENTRY_COLUMNS}} for r in rows],
                            ("user_id", "id"), update=[c for c in ENTRY_COLUMNS if c != "id"])
    except errors.ForeignKeyViolation:
        raise InvalidFood("A food or preset in this entry isn't in your library.") from None
    saved_ids = {key[1] for key in saved}
    return {r["id"]: APPLIED if r["id"] in saved_ids else _why_not(conn, "food_log_entry", user_id, r["id"])
            for r in rows}


@_for_user
def delete_entries(conn: psycopg.Connection, user_id: str, ids: list[str], at: datetime) -> dict[str, str]:
    checked = [_id(i, "Entry") for i in ids]
    done = _soft_delete(conn, "food_log_entry", user_id, checked, moment(at))
    return {i: APPLIED if i in done else MISSING for i in checked}


@_for_user
def delete_group(conn: psycopg.Connection, user_id: str, group_id: str, at: datetime) -> int:
    """Undo for a preset tap: every entry it logged."""
    rows = conn.execute(
        "update food_log_entry set deleted_at = coalesce(deleted_at, %s), updated_at = now() "
        "where user_id = %s and group_id = %s returning id",
        (moment(at), user_id, _id(group_id, "Group")),
    ).fetchall()
    return len(rows)


def _entry_row(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, **{k: str(row[k]) if row[k] is not None else None
                      for k in ("id", "group_id", "preset_id", "food_id")}}


@_for_user
def entries_between(conn: psycopg.Connection, user_id: str, start: date, end: date) -> list[dict[str, Any]]:
    """Live entries on these local days, in time order."""
    rows = conn.execute(
        sql.SQL("select {} from food_log_entry where user_id = %s and deleted_at is null "
                "and local_date between %s and %s order by logged_at, id").format(
            sql.SQL(", ").join(map(sql.Identifier, ENTRY_COLUMNS))),
        (user_id, start, end),
    ).fetchall()
    return [_entry_row(r) for r in rows]


@_for_user
def last_logged_at(conn: psycopg.Connection, user_id: str) -> datetime | None:
    """For reminders: nothing logged recently means a nudge."""
    return conn.execute("select max(logged_at) as at from food_log_entry where user_id = %s and deleted_at is null",
                        (user_id,)).fetchone()["at"]


# ---------------------------------------------------------------- targets and day types

@_for_user
def save_targets(conn: psycopg.Connection, user_id: str, day_type: str, effective_from: date,
                 values: Mapping[str, Any], changed_at: datetime) -> str:
    """A day type's targets from a date onwards. A missing nutrient has no target, so no ring."""
    if day_type not in targets.DAY_TYPES:
        raise InvalidFood("Targets are for training days or rest days.")
    known = nutrient_units(conn, user_id)
    if not isinstance(values, Mapping):
        raise InvalidFood("Targets must be a list of values.")
    cleaned: dict[str, float] = {}
    for key, value in values.items():
        if key not in known:
            raise InvalidFood(f"Unknown nutrient: {key}.")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 100_000:
            raise InvalidFood("A target must be more than 0.")
        cleaned[key] = float(value)
    saved = _upsert(conn, "food_target_set",
                    [{"user_id": user_id, "day_type": day_type, "effective_from": effective_from,
                      "targets": Jsonb(cleaned), "changed_at": moment(changed_at)}],
                    ("user_id", "day_type", "effective_from"), update=("targets", "changed_at"), soft_delete=False)
    return APPLIED if saved else STALE


@_for_user
def target_sets(conn: psycopg.Connection, user_id: str) -> list[targets.TargetSet]:
    rows = conn.execute("select day_type, effective_from, targets from food_target_set where user_id = %s",
                        (user_id,)).fetchall()
    return [targets.TargetSet(r["day_type"], r["effective_from"], dict(r["targets"])) for r in rows]


@_for_user
def set_day_type(conn: psycopg.Connection, user_id: str, day: date, day_type: str | None,
                 changed_at: datetime) -> str:
    """Set a day by hand, or None to go back to deciding it from Garmin."""
    if day_type is not None and day_type not in targets.DAY_TYPES:
        raise InvalidFood("A day is a training day or a rest day.")
    saved = _upsert(conn, "food_day_type",
                    [{"user_id": user_id, "local_date": day, "day_type": day_type, "changed_at": moment(changed_at)}],
                    ("user_id", "local_date"), update=("day_type", "changed_at"), soft_delete=False)
    return APPLIED if saved else STALE


@_for_user
def day_type_overrides(conn: psycopg.Connection, user_id: str, start: date, end: date) -> dict[date, str | None]:
    rows = conn.execute(
        "select local_date, day_type from food_day_type where user_id = %s and local_date between %s and %s",
        (user_id, start, end),
    ).fetchall()
    return {r["local_date"]: r["day_type"] for r in rows}


def is_owner(conn: psycopg.Connection, user_id: str) -> bool:
    """The owner is the one person whose Garmin data this deployment holds."""
    _not_acting(conn)
    row = conn.execute("select is_owner from app_user where id = %s", (_id(user_id, "User"),)).fetchone()
    return bool(row and row["is_owner"])


def activity_durations(conn: psycopg.Connection, user_id: str, start: date, end: date) -> dict[date, list[float | None]]:
    """Each synced activity's duration by local day. Only the owner has Garmin data, so anyone else gets none."""
    if not is_owner(conn, user_id):
        return {}
    rows = conn.execute(
        "select local_date, duration_seconds from activity where local_date between %s and %s",
        (start, end),
    ).fetchall()
    by_day: dict[date, list[float | None]] = {}
    for r in rows:
        by_day.setdefault(r["local_date"], []).append(r["duration_seconds"])
    return by_day


def day_types(conn: psycopg.Connection, user_id: str, start: date, end: date,
              threshold_minutes: float) -> dict[date, targets.DayType]:
    """Training or rest for each day. Call it outside as_user, since it reads Garmin data too."""
    durations = activity_durations(conn, user_id, start, end)
    overrides = day_type_overrides(conn, user_id, start, end)
    days: dict[date, targets.DayType] = {}
    day = start
    while day <= end:
        days[day] = targets.day_type(overrides.get(day), durations.get(day, []), threshold_minutes)
        day += timedelta(days=1)
    return days
