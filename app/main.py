"""FastAPI application: routes, middleware, and startup hooks.

The app is organized in a single file because the surface is small and
cohesive. Sections below:
  1. App setup (middleware, static, templates)
  2. Startup / shutdown
  3. Helpers (balance/leaderboard computations over a Session)
  4. Public routes
  5. Auth routes (login / logout)
  6. Parent routes (quick actions + CRUD)
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app import achievements, models
from app.auth import (
    SESSION_KEY,
    is_authenticated,
    parent_pin,
    require_parent,
    session_secret,
)
from app.database import SessionLocal, get_db, init_db
from app.seed import seed_if_empty

log = logging.getLogger("summer")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# 1. App setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Summer", version="0.0.10")

# SessionMiddleware signs the cookie using SESSION_SECRET. Set
# https_only=True in production behind HTTPS.
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    max_age=60 * 60 * 24 * 7,  # 1 week
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fmt_time(dt: datetime) -> str:
    """Format hour:minute AM/PM in a way that works on both Windows and Unix.

    Python's `%I` is portable but the no-pad specifier (`%-I`) is not. We
    strip the leading zero manually.
    """
    raw = dt.strftime("%I:%M %p").lstrip("0")
    return raw or "12:00 AM"


def _utcnow() -> datetime:
    """Return the current UTC time. Used for stamping approval timestamps."""
    return datetime.now(timezone.utc)


def _fmt_day(d) -> str:  # noqa: ANN001 - accepts date or datetime
    """Format 'Mon DD' (no zero-pad) portably across platforms."""
    return f"{d.strftime('%b')} {int(d.strftime('%d'))}"


def _humanize_timedelta(dt: datetime) -> str:
    """Format a datetime for the kid-facing UI, e.g. 'Today 3:42 PM'."""
    local_tz = datetime.now().astimezone().tzinfo
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(local_tz)
    now = datetime.now(local_tz)
    if local.date() == now.date():
        return f"Today {_fmt_time(local)}"
    if local.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {_fmt_time(local)}"
    if (now - local).days < 7:
        return f"{local.strftime('%a')} {_fmt_time(local)}"
    return _fmt_day(local)


def _week_label(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now().astimezone()
    monday = now - timedelta(days=now.weekday())
    return f"Week of {_fmt_day(monday)}, {monday.year}"


# Make helpers available in all templates
templates.env.filters["humantime"] = _humanize_timedelta
templates.env.globals["week_label"] = _week_label
templates.env.globals["app_version"] = app.version

# Curated emoji set the parent can pick from for a kid's avatar. Roughly
# grouped: mammals, bears, misc animals, mythical / dinos, sea / bugs, fun.
# The first entry is the default for new kids (matches the existing seed).
KID_AVATAR_CHOICES: list[str] = [
    "🦊", "🦁", "🐯", "🐰", "🐱", "🐶", "🐕", "🐩",
    "🐼", "🐨", "🐻", "🐻‍❄️",
    "🐸", "🐵", "🐮", "🐷", "🦉", "🐢",
    "🦄", "🐲", "🐉", "🦖", "🦕",
    "🐬", "🐳", "🦋", "🐝", "🐙",
    "⚡", "🌈", "🚀", "🤖",
]
templates.env.globals["kid_avatars"] = KID_AVATAR_CHOICES

# Curated emoji set for chore category icons. Roughly grouped by area so the
# picker feels organized: misc / default, rooms, food/kitchen, cleaning,
# outdoors, animals, school, sports, more misc. The first entry ("⭐") is
# the default for new categories and matches the existing seed.
CATEGORY_EMOJI_CHOICES: list[str] = [
    # Default / misc
    "⭐", "🌟", "✨", "💫", "❤️", "🔔", "🎁", "🏆",
    # Rooms
    "🛏️", "🛋️", "🚪", "🪟", "🪑", "🚽", "🛁", "🚿",
    # Kitchen / food
    "🍳", "🥣", "🍽️", "🥄", "🍴", "🧽", "🧊",
    # Cleaning / laundry
    "🧹", "🧼", "🧴", "🧺", "🗑️",
    # Outdoors / garden
    "🌳", "🌲", "🌱", "🌻", "🌷", "🌿", "🍂", "⛲",
    # Animals / pets
    "🐶", "🐱", "🐰", "🐹", "🐠", "🐦", "🐢", "🐾",
    # School / learning
    "📚", "✏️", "📝", "🎒", "📖", "🎨", "🎵", "🧮",
    # Sports / active
    "⚽", "🏀", "🚴", "🏊", "🎮", "🎲", "🪀", "🛹",
]
templates.env.globals["category_emojis"] = CATEGORY_EMOJI_CHOICES


# ---------------------------------------------------------------------------
# 2. Startup / shutdown
# ---------------------------------------------------------------------------


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    log.info("Summer is ready.")


@app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz() -> str:
    return "ok"


# ---------------------------------------------------------------------------
# 3. Helpers (per-request DB queries)
# ---------------------------------------------------------------------------


def _kid_balances(db: Session) -> dict[int, int]:
    """Return {kid_id: current_balance} for every kid.

    Only approved completions count toward the balance — pending requests
    haven't been awarded yet, and denied rows shouldn't subtract.
    """
    earned_rows = db.execute(
        select(models.ChoreCompletion.kid_id, func.coalesce(func.sum(models.ChoreCompletion.points_earned), 0))
        .where(models.ChoreCompletion.status == models.STATUS_APPROVED)
        .group_by(models.ChoreCompletion.kid_id)
    ).all()
    spent_rows = db.execute(
        select(models.RewardRedemption.kid_id, func.coalesce(func.sum(models.RewardRedemption.points_spent), 0))
        .group_by(models.RewardRedemption.kid_id)
    ).all()
    earned = {kid_id: total for kid_id, total in earned_rows}
    spent = {kid_id: total for kid_id, total in spent_rows}
    balances: dict[int, int] = defaultdict(int)
    for kid_id, total in earned.items():
        balances[kid_id] += total
    for kid_id, total in spent.items():
        balances[kid_id] -= total
    return dict(balances)


def _kid_weekly_earned(db: Session) -> dict[int, int]:
    """Sum of approved points earned per kid in the current (Mon-Sun) week."""
    week_start_utc, week_end_utc = achievements.week_bounds()
    rows = db.execute(
        select(models.ChoreCompletion.kid_id, func.coalesce(func.sum(models.ChoreCompletion.points_earned), 0))
        .where(models.ChoreCompletion.completed_at >= week_start_utc)
        .where(models.ChoreCompletion.completed_at < week_end_utc)
        .where(models.ChoreCompletion.status == models.STATUS_APPROVED)
        .group_by(models.ChoreCompletion.kid_id)
    ).all()
    return {kid_id: total for kid_id, total in rows}


def _kid_weekly_spent(db: Session) -> dict[int, int]:
    week_start_utc, week_end_utc = achievements.week_bounds()
    rows = db.execute(
        select(models.RewardRedemption.kid_id, func.coalesce(func.sum(models.RewardRedemption.points_spent), 0))
        .where(models.RewardRedemption.redeemed_at >= week_start_utc)
        .where(models.RewardRedemption.redeemed_at < week_end_utc)
        .group_by(models.RewardRedemption.kid_id)
    ).all()
    return {kid_id: total for kid_id, total in rows}


def _leaderboard(db: Session) -> list[dict]:
    """Return kids ranked by current balance, descending, with medal flags."""
    kids = db.execute(select(models.Kid).order_by(models.Kid.name)).scalars().all()
    balances = _kid_balances(db)
    ranked = sorted(
        kids,
        key=lambda k: (-balances.get(k.id, 0), k.name.lower()),
    )
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    result = []
    for idx, kid in enumerate(ranked):
        result.append(
            {
                "kid": kid,
                "balance": balances.get(kid.id, 0),
                "rank": idx + 1,
                "medal": medals.get(idx),
            }
        )
    return result


def _render(
    request: Request,
    template_name: str,
    db: Session,
    **context,
) -> HTMLResponse:
    """Render a template with the standard context (auth state, flashes)."""
    base = {
        "is_parent": is_authenticated(request),
        "msg": request.query_params.get("msg"),
        "error": request.query_params.get("error"),
    }
    base.update(context)
    return templates.TemplateResponse(request, template_name, base)


def _redirect(path: str, msg: str | None = None, error: str | None = None) -> RedirectResponse:
    qs = []
    if msg:
        qs.append(f"msg={msg}")
    if error:
        qs.append(f"error={error}")
    if qs:
        path = f"{path}?{'&'.join(qs)}"
    return RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# 4. Public routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    leaderboard = _leaderboard(db)
    weekly_earned = _kid_weekly_earned(db)
    weekly_spent = _kid_weekly_spent(db)
    return _render(
        request,
        "index.html",
        db,
        leaderboard=leaderboard,
        weekly_earned=weekly_earned,
        weekly_spent=weekly_spent,
    )


@app.get("/kid/{kid_id}", response_class=HTMLResponse)
def kid_detail(kid_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    kid = db.get(models.Kid, kid_id)
    if kid is None:
        raise HTTPException(status_code=404, detail="Kid not found")
    completions = (
        db.execute(
            select(models.ChoreCompletion)
            .where(models.ChoreCompletion.kid_id == kid_id)
            .order_by(models.ChoreCompletion.completed_at.desc())
            .limit(25)
        )
        .scalars()
        .all()
    )
    redemptions = (
        db.execute(
            select(models.RewardRedemption)
            .where(models.RewardRedemption.kid_id == kid_id)
            .order_by(models.RewardRedemption.redeemed_at.desc())
            .limit(25)
        )
        .scalars()
        .all()
    )
    all_completions = (
        db.execute(
            select(models.ChoreCompletion).where(models.ChoreCompletion.kid_id == kid_id)
        )
        .scalars()
        .all()
    )
    all_redemptions = (
        db.execute(
            select(models.RewardRedemption).where(models.RewardRedemption.kid_id == kid_id)
        )
        .scalars()
        .all()
    )
    balance = achievements.compute_balance(all_completions, all_redemptions)
    streak = achievements.compute_streak(all_completions)
    badges = achievements.compute_badges(all_completions, all_redemptions)
    active_chores = (
        db.execute(
            select(models.Chore)
            .where(models.Chore.is_active.is_(True))
            .order_by(models.Chore.name)
        )
        .scalars()
        .all()
    )
    return _render(
        request,
        "kid.html",
        db,
        kid=kid,
        completions=completions,
        redemptions=redemptions,
        balance=balance,
        streak=streak,
        badges=badges,
        lifetime_earned=achievements.compute_lifetime_earned(all_completions),
        active_chores=active_chores,
    )


@app.get("/chores", response_class=HTMLResponse)
def chore_list(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    categories = (
        db.execute(select(models.Category).order_by(models.Category.name)).scalars().all()
    )
    active_chores = (
        db.execute(
            select(models.Chore)
            .where(models.Chore.is_active.is_(True))
            .order_by(models.Chore.name)
        )
        .scalars()
        .all()
    )
    # Group chores by category
    grouped: dict[int | None, list[models.Chore]] = defaultdict(list)
    for chore in active_chores:
        grouped[chore.category_id].append(chore)
    return _render(
        request,
        "chores.html",
        db,
        categories=categories,
        grouped_chores=grouped,
    )


@app.get("/rewards", response_class=HTMLResponse)
def rewards_catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Public kid-facing rewards catalog. Printable via the in-page button."""
    rewards = (
        db.execute(
            select(models.Reward)
            .where(models.Reward.is_active.is_(True))
            .order_by(models.Reward.cost)
        )
        .scalars()
        .all()
    )
    return _render(request, "rewards_public.html", db, rewards=rewards)


@app.get("/print", response_class=HTMLResponse)
def printable_summary(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    kids = db.execute(select(models.Kid).order_by(models.Kid.name)).scalars().all()
    balances = _kid_balances(db)
    weekly_earned = _kid_weekly_earned(db)
    weekly_spent = _kid_weekly_spent(db)
    week_start_utc, _ = achievements.week_bounds()

    # This-week activity per kid, oldest first
    this_week_completions: dict[int, list[models.ChoreCompletion]] = defaultdict(list)
    rows = db.execute(
        select(models.ChoreCompletion)
        .where(models.ChoreCompletion.completed_at >= week_start_utc)
        .order_by(models.ChoreCompletion.completed_at.asc())
    ).scalars().all()
    for c in rows:
        this_week_completions[c.kid_id].append(c)

    this_week_redemptions: dict[int, list[models.RewardRedemption]] = defaultdict(list)
    rows = db.execute(
        select(models.RewardRedemption)
        .where(models.RewardRedemption.redeemed_at >= week_start_utc)
        .order_by(models.RewardRedemption.redeemed_at.asc())
    ).scalars().all()
    for r in rows:
        this_week_redemptions[r.kid_id].append(r)

    return _render(
        request,
        "print.html",
        db,
        kids=kids,
        balances=balances,
        weekly_earned=weekly_earned,
        weekly_spent=weekly_spent,
        this_week_completions=this_week_completions,
        this_week_redemptions=this_week_redemptions,
    )


# ---------------------------------------------------------------------------
# 5. Auth routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return _render(request, "login.html", db=None)  # type: ignore[arg-type]


@app.post("/login")
def login_submit(
    request: Request,
    pin: Annotated[str, Form()],
) -> RedirectResponse:
    if pin.strip() != parent_pin():
        return _redirect("/login", error="Wrong PIN — try again.")
    request.session[SESSION_KEY] = True
    return _redirect("/parent", msg="Welcome back, parent!")


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.pop(SESSION_KEY, None)
    return _redirect("/", msg="Logged out.")


# ---------------------------------------------------------------------------
# 6. Parent routes
# ---------------------------------------------------------------------------


def _require_parent_or_redirect(request: Request) -> None:
    """For routes that should 303 to /login if not authenticated."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )


@app.get("/parent", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    kids = db.execute(select(models.Kid).order_by(models.Kid.name)).scalars().all()
    active_chores = (
        db.execute(
            select(models.Chore)
            .where(models.Chore.is_active.is_(True))
            .order_by(models.Chore.name)
        )
        .scalars()
        .all()
    )
    active_rewards = (
        db.execute(
            select(models.Reward)
            .where(models.Reward.is_active.is_(True))
            .order_by(models.Reward.cost)
        )
        .scalars()
        .all()
    )
    balances = _kid_balances(db)
    pending_completions = (
        db.execute(
            select(models.ChoreCompletion)
            .where(models.ChoreCompletion.status == models.STATUS_PENDING)
            .order_by(models.ChoreCompletion.completed_at.asc())
        )
        .scalars()
        .all()
    )
    return _render(
        request,
        "parent.html",
        db,
        kids=kids,
        active_chores=active_chores,
        active_rewards=active_rewards,
        balances=balances,
        pending_completions=pending_completions,
    )


@app.post("/parent/complete-chore", dependencies=[Depends(_require_parent_or_redirect)])
def parent_complete_chore(
    request: Request,
    kid_id: Annotated[int, Form()],
    chore_id: Annotated[int, Form()],
    note: Annotated[str, Form()] = "",
    points_override: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Parent marks a chore complete for a kid (no kid request involved).

    `points_override` lets the parent award a different point value at
    the moment of completion (e.g. "Sam pulled 25 weeds, give them 25
    instead of 15"). Falls back to the chore's `points` when blank, and
    is clamped to >= 0. The actual amount is recorded on the completion
    row so future chore edits don't rewrite history.

    `points_override` is taken as a string so an empty field is treated
    as "use the chore's default" rather than a FastAPI 422.
    """
    db = SessionLocal()
    try:
        chore = db.get(models.Chore, chore_id)
        kid = db.get(models.Kid, kid_id)
        if not chore or not chore.is_active:
            return _redirect("/parent", error="That chore isn't available right now.")
        if not kid:
            return _redirect("/parent", error="Unknown kid.")
        override_val: Optional[int]
        if points_override.strip() == "":
            override_val = None
        else:
            try:
                override_val = int(points_override)
            except ValueError:
                return _redirect(
                    "/parent",
                    error="Points override must be a whole number, or blank.",
                )
        actual_points = (
            max(0, override_val) if override_val is not None else chore.points
        )
        db.add(
            models.ChoreCompletion(
                kid_id=kid.id,
                chore_id=chore.id,
                points_earned=actual_points,
                note=note.strip(),
                status=models.STATUS_APPROVED,
            )
        )
        db.commit()
        msg = f"🎉 {kid.name} earned {actual_points} points for '{chore.name}'!"
        if override_val is not None and override_val != chore.points:
            msg += f" (override; default was {chore.points})"
        return _redirect("/parent", msg=msg)
    finally:
        db.close()


@app.post("/parent/undo-completion/{completion_id}", dependencies=[Depends(_require_parent_or_redirect)])
def parent_undo_completion(completion_id: int) -> RedirectResponse:
    """Undo a chore completion that was already approved (or awarded directly
    by the parent). Marks the row as `denied` with a reason so the audit
    trail is preserved — we don't delete the row, the kid's history stays
    intact and the balance/lifetime recompute correctly without it.

    Only approved completions can be undone. Pending requests should be
    denied (which keeps the same row) rather than undone, and denied
    rows have nothing to undo.
    """
    db = SessionLocal()
    try:
        c = db.get(models.ChoreCompletion, completion_id)
        if not c:
            return _redirect("/parent/history", error="That entry is gone.")
        if c.status != models.STATUS_APPROVED:
            return _redirect(
                "/parent/history",
                error="Only approved completions can be undone.",
            )
        chore = db.get(models.Chore, c.chore_id)
        chore_name = chore.name if chore else "(deleted chore)"
        c.status = models.STATUS_DENIED
        c.denial_reason = "Undone by parent"
        c.points_earned = 0
        db.commit()
        return _redirect(
            "/parent/history",
            msg=f"↩️ Undid '{chore_name}' — points removed from {c.kid.name}.",
        )
    finally:
        db.close()


@app.post("/parent/undo-redemption/{redemption_id}", dependencies=[Depends(_require_parent_or_redirect)])
def parent_undo_redemption(redemption_id: int) -> RedirectResponse:
    """Undo a reward redemption. Deletes the row so the kid's balance
    is restored. (For chore completions we keep the row as 'denied'
    to preserve audit trail; redemptions don't have an approval step
    so deletion is the simpler equivalent.)
    """
    db = SessionLocal()
    try:
        r = db.get(models.RewardRedemption, redemption_id)
        if not r:
            return _redirect("/parent/history", error="That entry is gone.")
        reward = db.get(models.Reward, r.reward_id)
        reward_name = reward.name if reward else "(deleted reward)"
        db.delete(r)
        db.commit()
        return _redirect(
            "/parent/history",
            msg=f"↩️ Undid redemption of '{reward_name}' — {r.points_spent} points restored to {r.kid.name}.",
        )
    finally:
        db.close()


@app.post("/parent/redeem", dependencies=[Depends(_require_parent_or_redirect)])
def parent_redeem(
    request: Request,
    kid_id: Annotated[int, Form()],
    reward_id: Annotated[int, Form()],
    note: Annotated[str, Form()] = "",
    cost_override: Annotated[Optional[int], Form()] = None,
) -> RedirectResponse:
    """Redeem a reward for a kid.

    `cost_override` lets a parent discount or adjust the redemption cost
    at the moment of redemption (e.g. "this ice cream is on sale, charge
    20 instead of 30"). The actual amount charged is recorded on the
    redemption row so future reward-cost edits don't rewrite history.
    Falls back to `reward.cost` when not provided.
    """
    db = SessionLocal()
    try:
        reward = db.get(models.Reward, reward_id)
        kid = db.get(models.Kid, kid_id)
        if not reward or not reward.is_active:
            return _redirect("/parent", error="That reward isn't available right now.")
        if not kid:
            return _redirect("/parent", error="Unknown kid.")

        # Use the override if provided, otherwise the reward's default cost.
        # The override is clamped to at least 1 (no negative or zero redemptions)
        # and at most the kid's current balance (can't spend more than they have).
        effective_cost = cost_override if cost_override is not None else reward.cost
        effective_cost = max(1, effective_cost)

        # Check balance first
        completions = (
            db.execute(
                select(models.ChoreCompletion).where(models.ChoreCompletion.kid_id == kid.id)
            )
            .scalars()
            .all()
        )
        redemptions = (
            db.execute(
                select(models.RewardRedemption).where(models.RewardRedemption.kid_id == kid.id)
            )
            .scalars()
            .all()
        )
        balance = achievements.compute_balance(completions, redemptions)
        if balance < effective_cost:
            return _redirect(
                "/parent",
                error=(
                    f"❌ {kid.name} only has {balance} points — "
                    f"needs {effective_cost} for '{reward.name}'."
                ),
            )
        db.add(
            models.RewardRedemption(
                kid_id=kid.id,
                reward_id=reward.id,
                points_spent=effective_cost,
                note=note.strip(),
            )
        )
        db.commit()
        if cost_override is not None and cost_override != reward.cost:
            msg = (
                f"🎁 {kid.name} redeemed '{reward.name}' for {effective_cost} points "
                f"(override; default was {reward.cost})!"
            )
        else:
            msg = f"🎁 {kid.name} redeemed '{reward.name}' for {effective_cost} points!"
        return _redirect("/parent", msg=msg)
    finally:
        db.close()


# ----- Chore approval workflow -----


@app.post("/kid/{kid_id}/request-chore")
def kid_request_chore(
    kid_id: int,
    chore_id: Annotated[int, Form()],
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Kid-facing: log a pending chore completion for a parent to approve.

    No PIN required — kids are the intended users. The completion lands
    with `status='pending'` and `points_earned=0` (a server-side default
    would also work, but setting it explicitly is clearer). A parent
    then approves from `/parent`, where they can also override the
    chore's default points to reward extra effort.
    """
    db = SessionLocal()
    try:
        kid = db.get(models.Kid, kid_id)
        if not kid:
            return _redirect("/", error="Unknown kid.")
        chore = db.get(models.Chore, chore_id)
        if not chore or not chore.is_active:
            return _redirect(
                f"/kid/{kid_id}", error="That chore isn't available right now."
            )
        db.add(
            models.ChoreCompletion(
                kid_id=kid.id,
                chore_id=chore.id,
                points_earned=0,  # real value is captured on approval
                note=note.strip(),
                status=models.STATUS_PENDING,
            )
        )
        db.commit()
        return _redirect(
            f"/kid/{kid_id}",
            msg=f"⏳ '{chore.name}' sent to a parent for approval!",
        )
    finally:
        db.close()


@app.post(
    "/parent/approve-completion/{completion_id}",
    dependencies=[Depends(_require_parent_or_redirect)],
)
def parent_approve_completion(
    completion_id: int,
    points_override: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Approve a pending chore request. Captures the awarded point value
    into the completion row (so future chore edits don't rewrite history)
    and stamps the approval as the completion time.

    `points_override` lets the parent award a different point value at
    approval time (e.g. "they pulled 25 weeds, give them 25 instead of
    15"). Falls back to the chore's `points` when blank, and is clamped
    to >= 0. Taken as a string so an empty field means "use default"
    rather than a FastAPI 422.
    """
    db = SessionLocal()
    try:
        c = db.get(models.ChoreCompletion, completion_id)
        if not c:
            return _redirect("/parent", error="That request is gone.")
        if c.status != models.STATUS_PENDING:
            return _redirect("/parent", error="Already handled.")
        chore = db.get(models.Chore, c.chore_id)
        if not chore:
            return _redirect("/parent", error="That chore is gone.")
        override_val: Optional[int]
        if points_override.strip() == "":
            override_val = None
        else:
            try:
                override_val = int(points_override)
            except ValueError:
                return _redirect(
                    "/parent",
                    error="Points override must be a whole number, or blank.",
                )
        actual_points = (
            max(0, override_val) if override_val is not None else chore.points
        )
        c.status = models.STATUS_APPROVED
        c.points_earned = actual_points
        c.completed_at = _utcnow()
        c.denial_reason = ""
        db.commit()
        msg = f"🎉 {c.kid.name} earned {actual_points} points for '{chore.name}'!"
        if override_val is not None and override_val != chore.points:
            msg += f" (override; default was {chore.points})"
        return _redirect("/parent", msg=msg)
    finally:
        db.close()


@app.post(
    "/parent/deny-completion/{completion_id}",
    dependencies=[Depends(_require_parent_or_redirect)],
)
def parent_deny_completion(
    completion_id: int,
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Deny a pending chore request. Stores the reason so the kid sees
    feedback on their timeline.
    """
    db = SessionLocal()
    try:
        c = db.get(models.ChoreCompletion, completion_id)
        if not c:
            return _redirect("/parent", error="That request is gone.")
        if c.status != models.STATUS_PENDING:
            return _redirect("/parent", error="Already handled.")
        c.status = models.STATUS_DENIED
        c.denial_reason = reason.strip()
        c.points_earned = 0
        db.commit()
        return _redirect(
            "/parent",
            msg=f"Marked '{c.chore.name}' as not done.",
        )
    finally:
        db.close()


@app.get("/parent/history", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_history(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    completions = (
        db.execute(
            select(models.ChoreCompletion)
            .order_by(models.ChoreCompletion.completed_at.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    redemptions = (
        db.execute(
            select(models.RewardRedemption)
            .order_by(models.RewardRedemption.redeemed_at.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    kids = {k.id: k for k in db.execute(select(models.Kid)).scalars().all()}
    return _render(
        request,
        "history.html",
        db,
        completions=completions,
        redemptions=redemptions,
        kids=kids,
    )


# ----- Kids CRUD -----


@app.get("/parent/kids", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_kids(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    kids = db.execute(select(models.Kid).order_by(models.Kid.name)).scalars().all()
    balances = _kid_balances(db)
    return _render(request, "kids.html", db, kids=kids, balances=balances)


@app.post("/parent/kids/add", dependencies=[Depends(_require_parent_or_redirect)])
def parent_kids_add(
    request: Request,
    name: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#3b82f6",
    avatar_emoji: Annotated[str, Form()] = "🙂",
) -> RedirectResponse:
    name = name.strip()
    if not name:
        return _redirect("/parent/kids", error="Kid name is required.")
    db = SessionLocal()
    try:
        db.add(models.Kid(name=name, color=color, avatar_emoji=avatar_emoji or "🙂"))
        db.commit()
        return _redirect("/parent/kids", msg=f"Added {name}!")
    finally:
        db.close()


@app.post("/parent/kids/{kid_id}/edit", dependencies=[Depends(_require_parent_or_redirect)])
def parent_kids_edit(
    kid_id: int,
    name: Annotated[str, Form()],
    color: Annotated[str, Form()],
    avatar_emoji: Annotated[str, Form()],
) -> RedirectResponse:
    db = SessionLocal()
    try:
        kid = db.get(models.Kid, kid_id)
        if not kid:
            return _redirect("/parent/kids", error="Kid not found.")
        kid.name = name.strip() or kid.name
        kid.color = color or kid.color
        kid.avatar_emoji = avatar_emoji or kid.avatar_emoji
        db.commit()
        return _redirect("/parent/kids", msg=f"Updated {kid.name}.")
    finally:
        db.close()


@app.post("/parent/kids/{kid_id}/delete", dependencies=[Depends(_require_parent_or_redirect)])
def parent_kids_delete(kid_id: int) -> RedirectResponse:
    db = SessionLocal()
    try:
        kid = db.get(models.Kid, kid_id)
        if not kid:
            return _redirect("/parent/kids", error="Kid not found.")
        name = kid.name
        db.delete(kid)
        db.commit()
        return _redirect("/parent/kids", msg=f"Removed {name}.")
    finally:
        db.close()


# ----- Chores CRUD -----


@app.get("/parent/chores", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_chores(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    chores = (
        db.execute(
            select(models.Chore)
            .options(selectinload(models.Chore.category))
            .order_by(models.Chore.name)
        )
        .scalars()
        .all()
    )
    categories = (
        db.execute(select(models.Category).order_by(models.Category.name)).scalars().all()
    )
    return _render(request, "chores_manage.html", db, chores=chores, categories=categories)


@app.post("/parent/chores/add", dependencies=[Depends(_require_parent_or_redirect)])
def parent_chores_add(
    name: Annotated[str, Form()],
    points: Annotated[int, Form()],
    description: Annotated[str, Form()] = "",
    category_id: Annotated[int, Form()] = 0,
) -> RedirectResponse:
    name = name.strip()
    if not name:
        return _redirect("/parent/chores", error="Chore name is required.")
    db = SessionLocal()
    try:
        db.add(
            models.Chore(
                name=name,
                points=max(1, points),
                description=description.strip(),
                category_id=category_id or None,
                is_active=True,
            )
        )
        db.commit()
        return _redirect("/parent/chores", msg=f"Added chore '{name}'.")
    finally:
        db.close()


@app.post("/parent/chores/{chore_id}/edit", dependencies=[Depends(_require_parent_or_redirect)])
def parent_chores_edit(
    chore_id: int,
    name: Annotated[str, Form()],
    points: Annotated[int, Form()],
    description: Annotated[str, Form()],
    category_id: Annotated[int, Form()],
    is_active: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    db = SessionLocal()
    try:
        chore = db.get(models.Chore, chore_id)
        if not chore:
            return _redirect("/parent/chores", error="Chore not found.")
        chore.name = name.strip() or chore.name
        chore.points = max(1, points)
        chore.description = description.strip()
        chore.category_id = category_id or None
        chore.is_active = is_active == "on"
        db.commit()
        return _redirect("/parent/chores", msg=f"Updated '{chore.name}'.")
    finally:
        db.close()


@app.post("/parent/chores/{chore_id}/delete", dependencies=[Depends(_require_parent_or_redirect)])
def parent_chores_delete(chore_id: int) -> RedirectResponse:
    db = SessionLocal()
    try:
        chore = db.get(models.Chore, chore_id)
        if not chore:
            return _redirect("/parent/chores", error="Chore not found.")
        name = chore.name
        db.delete(chore)
        db.commit()
        return _redirect("/parent/chores", msg=f"Removed chore '{name}'.")
    finally:
        db.close()


# ----- Rewards CRUD -----


@app.get("/parent/rewards", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_rewards(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    rewards = (
        db.execute(select(models.Reward).order_by(models.Reward.cost))
        .scalars()
        .all()
    )
    return _render(request, "rewards.html", db, rewards=rewards)


@app.post("/parent/rewards/add", dependencies=[Depends(_require_parent_or_redirect)])
def parent_rewards_add(
    name: Annotated[str, Form()],
    cost: Annotated[int, Form()],
    description: Annotated[str, Form()] = "",
    emoji: Annotated[str, Form()] = "🎁",
) -> RedirectResponse:
    name = name.strip()
    if not name:
        return _redirect("/parent/rewards", error="Reward name is required.")
    db = SessionLocal()
    try:
        db.add(
            models.Reward(
                name=name,
                cost=max(1, cost),
                description=description.strip(),
                emoji=emoji or "🎁",
                is_active=True,
            )
        )
        db.commit()
        return _redirect("/parent/rewards", msg=f"Added reward '{name}'.")
    finally:
        db.close()


@app.post("/parent/rewards/{reward_id}/edit", dependencies=[Depends(_require_parent_or_redirect)])
def parent_rewards_edit(
    reward_id: int,
    name: Annotated[str, Form()],
    cost: Annotated[int, Form()],
    description: Annotated[str, Form()],
    emoji: Annotated[str, Form()],
    is_active: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    db = SessionLocal()
    try:
        reward = db.get(models.Reward, reward_id)
        if not reward:
            return _redirect("/parent/rewards", error="Reward not found.")
        reward.name = name.strip() or reward.name
        reward.cost = max(1, cost)
        reward.description = description.strip()
        reward.emoji = emoji or "🎁"
        reward.is_active = is_active == "on"
        db.commit()
        return _redirect("/parent/rewards", msg=f"Updated '{reward.name}'.")
    finally:
        db.close()


@app.post("/parent/rewards/{reward_id}/delete", dependencies=[Depends(_require_parent_or_redirect)])
def parent_rewards_delete(reward_id: int) -> RedirectResponse:
    db = SessionLocal()
    try:
        reward = db.get(models.Reward, reward_id)
        if not reward:
            return _redirect("/parent/rewards", error="Reward not found.")
        name = reward.name
        db.delete(reward)
        db.commit()
        return _redirect("/parent/rewards", msg=f"Removed reward '{name}'.")
    finally:
        db.close()


# ----- Categories CRUD -----


@app.get("/parent/categories", response_class=HTMLResponse, dependencies=[Depends(_require_parent_or_redirect)])
def parent_categories(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    categories = db.execute(
        select(models.Category).order_by(models.Category.name)
    ).scalars().all()
    # Count chores per category so the admin can see which are in use
    chore_counts = dict(
        db.execute(
            select(models.Chore.category_id, func.count(models.Chore.id))
            .group_by(models.Chore.category_id)
        ).all()
    )
    return _render(
        request,
        "categories.html",
        db,
        categories=categories,
        chore_counts=chore_counts,
    )


@app.post("/parent/categories/add", dependencies=[Depends(_require_parent_or_redirect)])
def parent_categories_add(
    name: Annotated[str, Form()],
    emoji: Annotated[str, Form()] = "⭐",
) -> RedirectResponse:
    name = name.strip()
    if not name:
        return _redirect("/parent/categories", error="Category name is required.")
    db = SessionLocal()
    try:
        db.add(models.Category(name=name, emoji=emoji or "⭐"))
        db.commit()
        return _redirect("/parent/categories", msg=f"Added category '{name}'.")
    except IntegrityError:
        db.rollback()
        return _redirect(
            "/parent/categories",
            error=f"A category named '{name}' already exists.",
        )
    finally:
        db.close()


@app.post("/parent/categories/{category_id}/edit", dependencies=[Depends(_require_parent_or_redirect)])
def parent_categories_edit(
    category_id: int,
    name: Annotated[str, Form()],
    emoji: Annotated[str, Form()],
) -> RedirectResponse:
    db = SessionLocal()
    try:
        cat = db.get(models.Category, category_id)
        if not cat:
            return _redirect("/parent/categories", error="Category not found.")
        cat.name = name.strip() or cat.name
        cat.emoji = emoji or cat.emoji
        db.commit()
        return _redirect("/parent/categories", msg=f"Updated '{cat.name}'.")
    except IntegrityError:
        db.rollback()
        return _redirect(
            "/parent/categories",
            error=f"A category named '{name}' already exists.",
        )
    finally:
        db.close()


@app.post("/parent/categories/{category_id}/delete", dependencies=[Depends(_require_parent_or_redirect)])
def parent_categories_delete(category_id: int) -> RedirectResponse:
    db = SessionLocal()
    try:
        cat = db.get(models.Category, category_id)
        if not cat:
            return _redirect("/parent/categories", error="Category not found.")
        in_use = (
            db.execute(
                select(func.count(models.Chore.id))
                .where(models.Chore.category_id == category_id)
            ).scalar_one()
        )
        if in_use > 0:
            return _redirect(
                "/parent/categories",
                error=(
                    f"'{cat.name}' is used by {in_use} chore(s) — "
                    "reassign or delete those first."
                ),
            )
        name = cat.name
        db.delete(cat)
        db.commit()
        return _redirect("/parent/categories", msg=f"Removed '{name}'.")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PWA manifest
# ---------------------------------------------------------------------------


@app.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest() -> JSONResponse:
    return JSONResponse(
        {
            "name": "Summer Chores",
            "short_name": "Summer",
            "start_url": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#fffaf0",
            "theme_color": "#f59e0b",
            "icons": [
                {
                    "src": "/static/icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": "/static/icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
        }
    )
