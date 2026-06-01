"""Populate an empty database with example kids, chores, and rewards.

Only runs on first start (or whenever the kids table is empty). The data is
deliberately generic so the parent can edit/delete it from the admin UI.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import models

log = logging.getLogger("summer.seed")

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Kitchen", "🍳"),
    ("Bedroom", "🛏️"),
    ("Bathroom", "🛁"),
    ("Outdoor", "🌳"),
    ("Pets", "🐾"),
    ("Other", "⭐"),
]

DEFAULT_KIDS: list[dict] = [
    {"name": "Alex", "color": "#3b82f6", "avatar_emoji": "🦊"},
    {"name": "Sam", "color": "#10b981", "avatar_emoji": "🐼"},
]

DEFAULT_CHORES: list[dict] = [
    {"name": "Make your bed", "points": 5, "category": "Bedroom",
     "description": "Pillow fluffed, blanket pulled up."},
    {"name": "Tidy your room", "points": 15, "category": "Bedroom",
     "description": "Toys put away, clothes in the hamper."},
    {"name": "Clear the table", "points": 5, "category": "Kitchen",
     "description": "Plates to the sink after dinner."},
    {"name": "Load the dishwasher", "points": 10, "category": "Kitchen"},
    {"name": "Take out the trash", "points": 10, "category": "Other"},
    {"name": "Brush teeth (morning & night)", "points": 5, "category": "Bathroom"},
    {"name": "Wipe bathroom counter", "points": 10, "category": "Bathroom"},
    {"name": "Water the garden", "points": 10, "category": "Outdoor"},
    {"name": "Read for 20 minutes", "points": 10, "category": "Other"},
    {"name": "Walk the dog", "points": 15, "category": "Pets"},
    {"name": "Feed the pets", "points": 5, "category": "Pets"},
    {"name": "Help with laundry", "points": 15, "category": "Other",
     "description": "Sort, fold, or put away."},
]

DEFAULT_REWARDS: list[dict] = [
    {"name": "Extra screen time (30 min)", "cost": 20, "emoji": "📱"},
    {"name": "Pick the family movie", "cost": 40, "emoji": "🎬"},
    {"name": "Ice cream treat", "cost": 30, "emoji": "🍦"},
    {"name": "Stay up 30 min late", "cost": 50, "emoji": "🌙"},
    {"name": "Friend sleepover", "cost": 100, "emoji": "🏕️"},
    {"name": "Pick the family dinner", "cost": 60, "emoji": "🍕"},
]


def seed_if_empty(db: Session) -> None:
    """Insert defaults if the kids table is currently empty."""
    if db.query(models.Kid).count() > 0:
        log.info("Skipping seed; data already present.")
        return

    log.info("Seeding initial data...")

    categories: dict[str, models.Category] = {}
    for name, emoji in DEFAULT_CATEGORIES:
        cat = models.Category(name=name, emoji=emoji)
        db.add(cat)
        categories[name] = cat
    db.flush()

    for kid_spec in DEFAULT_KIDS:
        db.add(models.Kid(**kid_spec))

    for chore_spec in DEFAULT_CHORES:
        cat_name = chore_spec.pop("category", None)
        category = categories.get(cat_name) if cat_name else None
        db.add(models.Chore(category_id=category.id if category else None, **chore_spec))

    for reward_spec in DEFAULT_REWARDS:
        db.add(models.Reward(**reward_spec))

    db.commit()
    log.info("Seed complete.")
