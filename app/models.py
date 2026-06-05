"""SQLAlchemy models for the Summer chore tracker.

Design note: `chore_completions.points_earned` and
`reward_redemptions.points_spent` are denormalized on purpose. They capture
the point value at the time of the event, so editing a chore's current point
value does not retroactively change history.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Kid(Base):
    __tablename__ = "kids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#3b82f6")  # hex
    avatar_emoji: Mapped[str] = mapped_column(String(8), default="🙂")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    completions: Mapped[list["ChoreCompletion"]] = relationship(
        back_populates="kid", cascade="all, delete-orphan"
    )
    redemptions: Mapped[list["RewardRedemption"]] = relationship(
        back_populates="kid", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    emoji: Mapped[str] = mapped_column(String(8), default="⭐")

    chores: Mapped[list["Chore"]] = relationship(back_populates="category")


class Chore(Base):
    __tablename__ = "chores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    category: Mapped[Category | None] = relationship(back_populates="chores")
    completions: Mapped[list["ChoreCompletion"]] = relationship(
        back_populates="chore", cascade="all, delete-orphan"
    )


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    emoji: Mapped[str] = mapped_column(String(8), default="🎁")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    redemptions: Mapped[list["RewardRedemption"]] = relationship(
        back_populates="reward", cascade="all, delete-orphan"
    )


# ChoreCompletion lifecycle. A kid-driven request lands in PENDING and
# doesn't count toward balance/streak until a parent approves it. The
# default is APPROVED so legacy rows (and parent-awarded points) don't
# need a separate state.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
COMPLETION_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_DENIED)


class ChoreCompletion(Base):
    __tablename__ = "chore_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(
        ForeignKey("kids.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chore_id: Mapped[int] = mapped_column(
        ForeignKey("chores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Captured at approval time (not request time) so a chore edit between
    # request and approval doesn't shift the value the kid sees. Nullable
    # so a pending request can be stored before the value is known.
    points_earned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_APPROVED, nullable=False, index=True
    )
    denial_reason: Mapped[str] = mapped_column(String(256), default="")

    kid: Mapped[Kid] = relationship(back_populates="completions")
    chore: Mapped[Chore] = relationship(back_populates="completions")


class RewardRedemption(Base):
    __tablename__ = "reward_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(
        ForeignKey("kids.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reward_id: Mapped[int] = mapped_column(
        ForeignKey("rewards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Captured at redemption time
    points_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(String(256), default="")

    kid: Mapped[Kid] = relationship(back_populates="redemptions")
    reward: Mapped[Reward] = relationship(back_populates="redemptions")
