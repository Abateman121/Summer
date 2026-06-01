"""Pure functions for streaks, balances, and achievement badges.

Kept free of database and FastAPI imports so they're easy to unit-test.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import models

# Some platforms (notably the stock Windows Python build) ship without the
# IANA tz database, so ZoneInfo lookup fails even for "UTC". We fall back to
# a stdlib `datetime.timezone.utc` in that case.
_TzLike = Union[ZoneInfo, timezone]


def _local_tz() -> _TzLike:
    """Resolve the local timezone from the TZ env var, falling back to UTC."""
    name = os.environ.get("TZ", "UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def to_local_date(dt: datetime) -> date:
    """Convert a datetime (UTC or otherwise) to a local calendar date."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_local_tz()).date()


def compute_balance(
    completions: list[models.ChoreCompletion],
    redemptions: list[models.RewardRedemption],
) -> int:
    """Current point balance = lifetime earned - lifetime spent."""
    earned = sum(c.points_earned for c in completions)
    spent = sum(r.points_spent for r in redemptions)
    return earned - spent


def compute_lifetime_earned(completions: list[models.ChoreCompletion]) -> int:
    return sum(c.points_earned for c in completions)


def compute_streak(
    completions: list[models.ChoreCompletion],
    today: date | None = None,
) -> int:
    """Number of consecutive days (ending today or yesterday) with a completion.

    The streak is "still alive" if the kid did a chore today or yesterday.
    It only resets to 0 once a full day is missed.
    """
    if today is None:
        today = datetime.now(_local_tz()).date()

    days_with_completion = {to_local_date(c.completed_at) for c in completions}
    if not days_with_completion:
        return 0

    # Pick the most recent completion date as the anchor. If today has a
    # completion we walk back from today; otherwise from yesterday (still
    # alive, just not yet active today).
    if today in days_with_completion:
        anchor = today
    else:
        yesterday = today - timedelta(days=1)
        if yesterday in days_with_completion:
            anchor = yesterday
        else:
            return 0

    streak = 0
    cursor = anchor
    while cursor in days_with_completion:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    emoji: str
    description: str
    earned: bool
    earned_at: datetime | None


# The set of badges the app tracks. Order = display order.
BADGES: list[dict] = [
    {
        "key": "first_steps",
        "name": "First Steps",
        "emoji": "🎉",
        "description": "Completed your very first chore.",
    },
    {
        "key": "half_century",
        "name": "Half Century",
        "emoji": "💵",
        "description": "Earned 50 lifetime points.",
    },
    {
        "key": "century_club",
        "name": "Century Club",
        "emoji": "💯",
        "description": "Earned 100 lifetime points.",
    },
    {
        "key": "superstar",
        "name": "Superstar",
        "emoji": "🌟",
        "description": "Earned 500 lifetime points.",
    },
    {
        "key": "week_warrior",
        "name": "Week Warrior",
        "emoji": "🔥",
        "description": "Hit a 7-day completion streak.",
    },
    {
        "key": "chore_champion",
        "name": "Chore Champion",
        "emoji": "🏆",
        "description": "Completed 10 chores in a single day.",
    },
    {
        "key": "big_spender",
        "name": "Big Spender",
        "emoji": "🎁",
        "description": "Redeemed your first reward.",
    },
]


def compute_badges(
    completions: list[models.ChoreCompletion],
    redemptions: list[models.RewardRedemption],
) -> list[Badge]:
    """Return the full badge list with earned / earned_at populated."""
    earned_total = compute_lifetime_earned(completions)
    streak = compute_streak(completions)

    # Per-day completion count for the "chore champion" badge
    per_day = Counter(to_local_date(c.completed_at) for c in completions)
    max_chores_in_a_day = max(per_day.values(), default=0)

    first_completion_at = min(
        (c.completed_at for c in completions), default=None
    )
    first_redemption_at = min(
        (r.redeemed_at for r in redemptions), default=None
    )

    def earned_at_for(condition: bool) -> datetime | None:
        if not condition:
            return None
        # We don't store *when* the threshold was crossed, so use a sensible
        # proxy: the timestamp of the completion that pushed them over, or
        # the first redemption for the big spender.
        return first_completion_at if first_completion_at else None

    results: list[Badge] = []
    for spec in BADGES:
        key = spec["key"]
        if key == "first_steps":
            earned = first_completion_at is not None
            earned_at = first_completion_at
        elif key == "half_century":
            earned = earned_total >= 50
            earned_at = earned_at_for(earned)
        elif key == "century_club":
            earned = earned_total >= 100
            earned_at = earned_at_for(earned)
        elif key == "superstar":
            earned = earned_total >= 500
            earned_at = earned_at_for(earned)
        elif key == "week_warrior":
            earned = streak >= 7
            earned_at = earned_at_for(earned)
        elif key == "chore_champion":
            earned = max_chores_in_a_day >= 10
            # The completion that made the day reach 10
            earned_at = None
            if earned:
                for c in sorted(completions, key=lambda c: c.completed_at):
                    d = to_local_date(c.completed_at)
                    if per_day[d] >= 10:
                        # First completion of the day that hit 10
                        same_day = sorted(
                            [x for x in completions if to_local_date(x.completed_at) == d],
                            key=lambda x: x.completed_at,
                        )
                        if len(same_day) >= 10:
                            earned_at = same_day[9].completed_at
                            break
        elif key == "big_spender":
            earned = first_redemption_at is not None
            earned_at = first_redemption_at
        else:  # pragma: no cover - defensive
            earned = False
            earned_at = None

        results.append(
            Badge(
                key=key,
                name=spec["name"],
                emoji=spec["emoji"],
                description=spec["description"],
                earned=earned,
                earned_at=earned_at,
            )
        )
    return results


def start_of_week(d: date | None = None) -> date:
    """Return Monday of the week containing d, in the local timezone."""
    if d is None:
        d = datetime.now(_local_tz()).date()
    return d - timedelta(days=d.weekday())


def week_bounds(d: date | None = None) -> tuple[datetime, datetime]:
    """Return (start_of_week_midnight, end_of_week_midnight) as UTC datetimes."""
    if d is None:
        d = datetime.now(_local_tz()).date()
    start_local = datetime.combine(
        start_of_week(d), datetime.min.time(), tzinfo=_local_tz()
    )
    end_local = start_local + timedelta(days=7)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
