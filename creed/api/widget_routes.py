"""The home screen widget: turning its key on and off from Settings, and the one read the widget makes with it."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from creed import widget
from creed.api.deps import Conn, Session
from creed.api.food_routes import day_screen

router = APIRouter(prefix="/api/widget")


@router.get("/key")
def key_status(session: Session, conn: Conn) -> dict[str, Any]:
    return widget.status(conn, session["user_id"])


@router.post("/key")
def make_key(session: Session, conn: Conn) -> dict[str, Any]:
    """A new key, shown once. Any older key stops working, so a lost phone's widget can be cut off."""
    key = widget.new_key(conn, session["user_id"])
    return {"key": key, **widget.status(conn, session["user_id"])}


@router.delete("/key")
def remove_key(session: Session, conn: Conn) -> dict[str, Any]:
    widget.remove_key(conn, session["user_id"])
    return widget.status(conn, session["user_id"])


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    return header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None


@router.get("/food")
def food_today(request: Request, conn: Conn) -> dict[str, Any]:
    """Today's food for the widget: totals against targets and the day type. No meals, foods or times, since a
    widget shows on the lock screen and the key lives in another app. The key goes in a header, never the URL."""
    person = widget.user_for_key(conn, _bearer(request))
    if person is None:
        raise HTTPException(status_code=401, detail="This widget key isn't on. Turn the widget on in Creed's Settings.")
    day = day_screen({"user_id": person["user_id"], "is_owner": person["is_owner"]}, conn, None)
    return {
        "date": day["date"],
        "day_type": day["day_type"]["type"],
        "kcal_eaten": day["totals"].get("kcal", 0.0),
        "rings": [
            {k: ring[k] for k in ("id", "name", "unit", "eaten", "target", "incomplete")} for ring in day["rings"]
        ],
        "logged": sum(len(meal.get("entries", [])) for meal in day["meals"]),
    }
