"""The API. Every route that returns data requires a signed-in session, and access is denied by default."""
from __future__ import annotations

import hmac
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

import psycopg
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from creed import auth, config, feedback, notify, signup
from creed.forms import NotDelivered
from creed import settings as app_settings
from creed.api import views
from creed.api.auth_routes import router as auth_router
from creed.api.deps import Conn, OwnerSession
from creed.api.food_routes import push_info, push_router
from creed.api.food_routes import router as food_router
from creed.db import push as db_push
from creed.db import reads
from creed.db.store import Store
from creed.garmin import fit, track
from creed.garmin.client import BASE_URL_ENV_VAR, DEFAULT_BASE_URL, AuthFailed, Client
from creed.garmin.keys import resolve_api_key
from creed.intervals import api as intervals_api
from creed.intervals.client import BASE_URL_ENV_VAR as INTERVALS_BASE_URL_ENV_VAR
from creed.intervals.client import DEFAULT_BASE_URL as INTERVALS_DEFAULT_BASE_URL
from creed.intervals.client import Client as IntervalsClient
from creed.metrics import compute_all, race
from creed.sync.engine import TOKEN_SECRET, run_sync
from creed.sync.intervals import run_intervals_sync

config.load_dotenv()

app = FastAPI(title="Creed", docs_url=None, redoc_url=None, openapi_url=None)

ISSUE_LOOKBACK_DAYS = 7
SYNC_TIME_BUDGET_SECONDS = 240
SYNC_MAX_REQUESTS = 150
# intervals.icu allows 2,500 requests per 15 minutes, and most of a run's requests are activity files.
INTERVALS_MAX_REQUESTS = 400
# A run that started this recently and hasn't finished is still going. Longer than any run can last.
SYNC_RUNNING_MINUTES = 6
GARMIN_DAILY = ["body_battery_latest", "body_battery_max", "body_battery_min", "body_battery_charged",
                "body_battery_drained", "stress_avg", "stress_qualifier", "hrv_status", "hrv_last_night_avg",
                "hrv_weekly_avg", "hrv_balanced_low", "hrv_balanced_high", "resting_hr", "steps",
                "intensity_moderate", "intensity_vigorous", "respiration_avg"]
# Yesterday's value still answers "what's my latest" for these, but older values could mislead.
GARMIN_LATEST_DAYS = 2
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


@app.middleware("http")
async def refuse_changes_from_other_sites(request: Request, call_next):
    """Browsers name the page that sent a request, so another site can't act with the session cookie.

    SameSite=Strict on the cookie already stops this. It's checked twice because the cost of being wrong is high.
    The scheduled sync has no browser and its own secret.
    """
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin is not None and not request.url.path.startswith("/api/cron/"):
        expected = os.environ.get(auth.ORIGIN_ENV_VAR, "").strip().rstrip("/")
        if not expected:
            return JSONResponse({"detail": f"Set {auth.ORIGIN_ENV_VAR} to this app's address first."}, status_code=503)
        if origin.rstrip("/") != expected:
            return JSONResponse({"detail": "Not allowed."}, status_code=403)
    return await call_next(request)


# Added last, so it runs outermost and covers every response, including refusals.
@app.middleware("http")
async def no_caching_of_personal_data(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(auth.Refused)
def sign_in_refused(_request: Request, exc: auth.Refused) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(auth.NotConfigured)
def sign_in_not_configured(_request: Request, exc: auth.NotConfigured) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


app.include_router(auth_router)
app.include_router(food_router)
app.include_router(push_router)


def _secret_matches(given: str | None, expected: str | None) -> bool:
    return bool(given and expected) and hmac.compare_digest(given.encode(), expected.encode())


def require_cron(request: Request) -> None:
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else None
    if not _secret_matches(token, os.environ.get("CRON_SECRET")):
        raise HTTPException(status_code=401, detail="Not allowed.")


def _today(tz_name: str) -> date:
    return config.local_today(tz_name)


def _context(conn: psycopg.Connection):
    saved = app_settings.load(conn)
    today = _today(saved.timezone)
    return saved, reads.load_context(conn, today, saved.for_metrics(), datetime.now(timezone.utc))


def _latest(series: dict[str, dict[date, Any]], today: date) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for name, values in series.items():
        for back in range(GARMIN_LATEST_DAYS):
            day = today - timedelta(days=back)
            if day in values:
                latest[name] = values[day]
                break
    return latest


def _sync_status(conn: psycopg.Connection) -> dict[str, Any]:
    run = reads.latest_run(conn)
    return {
        "latest_run": run,
        "last_good_finish": reads.last_good_run(conn),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    """Says only that the app is up. Reveals nothing about the data."""
    return {"status": "ok"}


# The public homepage's "Try Creed" button counts how many people tapped it. It's the one number the API shares
# without a session: a single total, with nothing about who tapped. It lives in app_setting, which ignores keys
# that aren't settings, so it needed no new table.
TRY_CLICKS_KEY = "welcome_try_clicks"


@app.get("/api/public/try")
def try_clicks(conn: Conn) -> dict[str, int]:
    row = conn.execute("select value from app_setting where key = %s", (TRY_CLICKS_KEY,)).fetchone()
    return {"count": int(row["value"]) if row else 0}


@app.post("/api/public/try")
def count_try_click(conn: Conn) -> dict[str, int]:
    """Adds one in a single statement, so taps arriving together are all counted."""
    row = conn.execute(
        "insert into app_setting (key, value) values (%s, '1'::jsonb) "
        "on conflict (key) do update set value = to_jsonb((app_setting.value #>> '{}')::bigint + 1), "
        "updated_at = now() returning value",
        (TRY_CLICKS_KEY,),
    ).fetchone()
    conn.commit()
    return {"count": int(row["value"])}


@app.post("/api/public/feedback")
def send_feedback(data: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """A bug report or feature idea from the public feedback page, passed on to the creator's form, which emails them.

    Nothing is stored here. The hidden "website" field is left empty by people and filled by many bots, so a filled one
    is quietly accepted and dropped.
    """
    if isinstance(data.get("website"), str) and data["website"].strip():
        return {"sent": True}
    try:
        report = feedback.clean(data)
    except feedback.InvalidFeedback as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        feedback.send(report)
    except feedback.NotDelivered:
        raise HTTPException(status_code=502, detail="It didn't go through. Please try again in a minute.") from None
    return {"sent": True}


@app.post("/api/public/try-form")
def send_signup(data: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """Answers from the public Try Creed page, passed on to the creator's form, which emails them. Nothing is stored."""
    if isinstance(data.get("website"), str) and data["website"].strip():
        return {"sent": True}
    try:
        answers = signup.clean(data)
    except signup.InvalidSignup as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        signup.send(answers)
    except NotDelivered:
        raise HTTPException(status_code=502, detail="It didn't go through. Please try again in a minute.") from None
    return {"sent": True}


@app.get("/api/race")
def race_countdown(_: OwnerSession, conn: Conn) -> dict[str, Any]:
    """Just the countdown, so the bib on every screen doesn't need the whole of today's numbers."""
    saved = app_settings.load(conn)
    metric_settings = saved.for_metrics()
    return {
        "race_date": saved.race_date,
        "timezone": saved.timezone,
        "countdown": race.countdown(datetime.now(timezone.utc), metric_settings.race_date, saved.timezone),
    }


@app.get("/api/today")
def today_screen(_: OwnerSession, conn: Conn) -> dict[str, Any]:
    _saved, ctx = _context(conn)
    results = compute_all(ctx)
    series = reads.metric_series(conn, GARMIN_DAILY, ctx.today - timedelta(days=GARMIN_LATEST_DAYS), ctx.today)
    latest = _latest(series, ctx.today)
    last_night = next((n for n in ctx.sleep if n.day == ctx.today), None)
    garmin = {
        "tag": config.source_label(),
        "source": config.data_source(),
        "body_battery": latest.get("body_battery_latest"),
        "stress": latest.get("stress_avg"),
        "sleep_score": last_night.score if last_night else None,
        "hrv_status": latest.get("hrv_status"),
    }
    issues = reads.recent_quality_flags(conn, ctx.today - timedelta(days=ISSUE_LOOKBACK_DAYS), ("warning", "problem"))
    return views.today_view(ctx, results, garmin, issues, _sync_status(conn))


@app.get("/api/in-depth")
def in_depth_screen(_: OwnerSession, conn: Conn, days: Annotated[int, Query()] = 90) -> dict[str, Any]:
    if days not in (7, 30, 90, 180):
        raise HTTPException(status_code=422, detail="days must be 7, 30, 90 or 180.")
    _saved, ctx = _context(conn)
    results = compute_all(ctx)
    series = reads.metric_series(conn, GARMIN_DAILY, ctx.today - timedelta(days=days - 1), ctx.today)
    issues = reads.recent_quality_flags(conn, ctx.today - timedelta(days=ISSUE_LOOKBACK_DAYS), ("warning", "problem"))
    return views.in_depth_view(ctx, results, series, _latest(series, ctx.today), days, issues)


@app.get("/api/activities")
def activities(
    _: OwnerSession,
    conn: Conn,
    discipline: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if discipline is not None and discipline not in ("run", "bike", "swim", "multisport", "other"):
        raise HTTPException(status_code=422, detail="Unknown discipline.")
    _saved, ctx = _context(conn)
    loads = views.activity_loads(ctx)
    rows = reads.list_activities(conn, discipline, limit, offset)
    return {"activities": [{**row, **loads.get(row["activity_id"], views.NO_LOAD)} for row in rows]}


@app.get("/api/activities/{activity_id}")
def activity_detail(activity_id: int, _: OwnerSession, conn: Conn) -> dict[str, Any]:
    row = reads.get_activity(conn, activity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such activity.")
    _saved, ctx = _context(conn)
    load = views.activity_loads(ctx).get(activity_id, views.NO_LOAD)
    return {
        **row,
        **load,
        "flags": reads.activity_flags(conn, activity_id),
        "map_available": track.can_have_map(row["discipline"], row["type_key"]),
    }


@app.get("/api/activities/{activity_id}/route")
def activity_route(activity_id: int, _: OwnerSession, conn: Conn) -> dict[str, Any]:
    """One run or ride's GPS line, read from its file only when someone opens its map, and never saved."""
    row = reads.get_activity(conn, activity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such activity.")
    if not track.can_have_map(row["discipline"], row["type_key"]):
        raise HTTPException(status_code=422, detail="Maps are for outdoor runs and rides.")
    content = reads.activity_file(conn, activity_id)
    data = fit.unzip_fit(content) if content else None
    points, problem = fit.read_track(data) if data else ([], None)
    return {"discipline": row["discipline"], "incomplete": problem is not None, **track.build_route(points)}


@app.get("/api/data-quality")
def data_quality(_: OwnerSession, conn: Conn) -> dict[str, Any]:
    saved, ctx = _context(conn)
    last_28 = sum(1 for n in ctx.sleep if (ctx.today - n.day).days < 28)
    return {
        "summary": reads.quality_summary(conn),
        "nights_recorded_last_28": last_28,
        "garmin_key_expires": saved.garmin_key_expires,
        "sync": _sync_status(conn),
    }


@app.get("/api/settings")
def get_settings(session: OwnerSession, conn: Conn) -> dict[str, Any]:
    saved, ctx = _context(conn)
    return _settings_screen(saved, ctx, session, conn)


def _settings_screen(saved: app_settings.AppSettings, ctx: Any, session: dict[str, Any],
                     conn: psycopg.Connection) -> dict[str, Any]:
    """Settings, plus what the phone needs to turn notifications on and how many phones have them."""
    return {**views.settings_view(saved, ctx),
            "push": {**push_info(), "phones": db_push.phone_count(conn, session["user_id"])}}


@app.put("/api/settings")
async def put_settings(request: Request, session: OwnerSession, conn: Conn) -> dict[str, Any]:
    changes = await request.json()
    if not isinstance(changes, dict):
        raise HTTPException(status_code=422, detail="Send an object of settings to change.")
    try:
        app_settings.save(conn, changes)
    except app_settings.InvalidSetting as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    conn.commit()
    saved, ctx = _context(conn)
    return _settings_screen(saved, ctx, session, conn)


def _sync(conn: psycopg.Connection, trigger: str) -> dict[str, Any]:
    if config.data_source() == config.NONE:
        return {"status": "skipped", "message": "No watch is connected, so there's nothing to sync."}
    if config.data_source() == config.INTERVALS:
        return _sync_intervals(conn, trigger)
    saved = app_settings.load(conn)
    store = Store(conn)
    try:
        api_key = resolve_api_key()
    except AuthFailed:
        return {"status": "auth_failed", "message": "The Garmin key isn't configured."}
    client = Client(
        os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL),
        api_key,
        max_requests=SYNC_MAX_REQUESTS,
        deadline=time.monotonic() + SYNC_TIME_BUDGET_SECONDS,
        token=store.get_secret(TOKEN_SECRET),
        on_token=lambda token, expires: store.set_secret(TOKEN_SECRET, token, expires),
    )
    result = run_sync(store, client, today=_today(saved.timezone), trigger=trigger)
    return {"status": result.status, "requests": result.requests, "records": result.records,
            "backfill_pending": result.backfill_pending, "message": result.message}


def _sync_intervals(conn: psycopg.Connection, trigger: str) -> dict[str, Any]:
    saved = app_settings.load(conn)
    try:
        client = IntervalsClient(
            os.environ.get(INTERVALS_BASE_URL_ENV_VAR, INTERVALS_DEFAULT_BASE_URL),
            intervals_api.resolve_api_key(),
            max_requests=INTERVALS_MAX_REQUESTS,
            deadline=time.monotonic() + SYNC_TIME_BUDGET_SECONDS,
        )
        athlete = intervals_api.athlete_id()
    except AuthFailed as exc:
        return {"status": "auth_failed", "message": str(exc)}
    result = run_intervals_sync(Store(conn), client, athlete=athlete, today=_today(saved.timezone), trigger=trigger)
    return {"status": result.status, "requests": result.requests, "records": result.records,
            "backfill_pending": result.backfill_pending, "message": result.message}


@app.api_route("/api/cron/sync", methods=["GET", "POST"], dependencies=[Depends(require_cron)])
def cron_sync(conn: Conn) -> Response:
    """Called on a schedule by GitHub Actions (POST) and once a day by Vercel (GET), with a secret only they hold.
    Food reminders go first, as they're quick. Training notifications go after the sync, so they see its data.
    A problem with either never stops the sync or changes its result."""
    try:
        sent = notify.send_food_reminders(conn)
    except Exception:  # noqa: BLE001
        conn.rollback()
        sent = {"status": "failed"}
    result = _sync(conn, "cron")
    return JSONResponse({**result, "reminders": sent, "notifications": _training_notifications(conn, "cron")})


def _training_notifications(conn: psycopg.Connection, trigger: str) -> dict[str, Any]:
    try:
        return notify.send_training_notifications(conn, trigger=trigger)
    except Exception:  # noqa: BLE001
        conn.rollback()
        return {"status": "failed"}


@app.post("/api/sync")
def sync_now(_: OwnerSession, conn: Conn) -> dict[str, Any]:
    """The Sync now button. One at a time, so repeated taps can't send Garmin several syncs at once."""
    if reads.sync_running(conn, SYNC_RUNNING_MINUTES):
        raise HTTPException(status_code=409, detail="A sync is already running. Try again in a minute.")
    result = _sync(conn, "manual")
    # What this sync brought in is on screen now, so it isn't sent as a notification later.
    _training_notifications(conn, "manual")
    return {"status": result["status"], "sync": _sync_status(conn)}
