"""Postgres tables for Siege pro-match evidence. Every row is scoped to a data namespace
(`live` or `replay:<slug>`); the two are never mixed."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Operator(Base):
    __tablename__ = "siege_operator"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    side: Mapped[str] = mapped_column(String(8))
    __table_args__ = (CheckConstraint("side IN ('attacker', 'defender')", name="side_valid"),)


class MapInfo(Base):
    __tablename__ = "siege_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    name_key: Mapped[str] = mapped_column(String(64), unique=True)


class Team(Base):
    __tablename__ = "siege_team"
    id: Mapped[int] = mapped_column(primary_key=True)
    name_key: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(128))  # first spelling seen


class PageRevision(Base):
    """Raw wikitext exactly as fetched: the evidence every derived row points back to."""

    __tablename__ = "siege_page_revision"
    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64))
    page: Mapped[str] = mapped_column(String(255))
    revid: Mapped[int] = mapped_column(BigInteger)
    revision_timestamp: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    wikitext: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("namespace", "page", "revid"),)


class Match(Base):
    __tablename__ = "siege_match"
    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    match_key: Mapped[str] = mapped_column(String(64), unique=True)
    page: Mapped[str] = mapped_column(String(255))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_precision: Mapped[str | None] = mapped_column(String(8))
    team1_id: Mapped[int] = mapped_column(ForeignKey("siege_team.id"))
    team2_id: Mapped[int] = mapped_column(ForeignKey("siege_team.id"))
    finished: Mapped[bool] = mapped_column(Boolean)
    forfeit: Mapped[bool] = mapped_column(Boolean)
    winner: Mapped[int | None] = mapped_column(Integer)
    siegegg_id: Mapped[str | None] = mapped_column(String(32))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_revision_id: Mapped[int] = mapped_column(ForeignKey("siege_page_revision.id"))
    last_revision_id: Mapped[int] = mapped_column(ForeignKey("siege_page_revision.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)  # canonical resolved record, for audits

    maps: Mapped[list["MapPlayed"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="MapPlayed.order"
    )
    veto: Mapped[list["VetoAction"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="VetoAction.step"
    )
    __table_args__ = (
        CheckConstraint("team1_id <> team2_id", name="distinct_teams"),
        CheckConstraint("winner IS NULL OR winner IN (1, 2)", name="winner_valid"),
    )


class MapPlayed(Base):
    __tablename__ = "siege_map_played"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("siege_match.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer)
    map_id: Mapped[int] = mapped_column(ForeignKey("siege_map.id"))
    status: Mapped[str] = mapped_column(String(10))
    team1_first_side: Mapped[str | None] = mapped_column(String(3))
    t1_atk: Mapped[int] = mapped_column(Integer)
    t1_def: Mapped[int] = mapped_column(Integer)
    t1_ot_atk: Mapped[int] = mapped_column(Integer)
    t1_ot_def: Mapped[int] = mapped_column(Integer)
    t2_atk: Mapped[int] = mapped_column(Integer)
    t2_def: Mapped[int] = mapped_column(Integer)
    t2_ot_atk: Mapped[int] = mapped_column(Integer)
    t2_ot_def: Mapped[int] = mapped_column(Integer)

    match: Mapped[Match] = relationship(back_populates="maps")
    bans: Mapped[list["OperatorBan"]] = relationship(
        back_populates="map_played", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("match_id", "order"),
        CheckConstraint("status IN ('finished', 'skipped', 'unplayed')", name="status_valid"),
        CheckConstraint(
            "LEAST(t1_atk, t1_def, t1_ot_atk, t1_ot_def, t2_atk, t2_def, t2_ot_atk, t2_ot_def) >= 0",
            name="rounds_nonnegative",
        ),
    )


class OperatorBan(Base):
    __tablename__ = "siege_operator_ban"
    id: Mapped[int] = mapped_column(primary_key=True)
    map_played_id: Mapped[int] = mapped_column(ForeignKey("siege_map_played.id", ondelete="CASCADE"))
    team: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)
    operator_id: Mapped[int] = mapped_column(ForeignKey("siege_operator.id"))

    map_played: Mapped[MapPlayed] = relationship(back_populates="bans")
    __table_args__ = (
        UniqueConstraint("map_played_id", "team", "slot"),
        CheckConstraint("team IN (1, 2)", name="team_valid"),
    )


class VetoAction(Base):
    __tablename__ = "siege_veto_action"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("siege_match.id", ondelete="CASCADE"))
    step: Mapped[int] = mapped_column(Integer)
    team: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    map_id: Mapped[int] = mapped_column(ForeignKey("siege_map.id"))

    match: Mapped[Match] = relationship(back_populates="veto")
    __table_args__ = (
        UniqueConstraint("match_id", "step"),
        CheckConstraint("kind IN ('ban', 'pick', 'decider')", name="kind_valid"),
    )


class Correction(Base):
    """A finished map whose data changed in a later Liquipedia revision. Append-only audit."""

    __tablename__ = "siege_correction"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("siege_match.id"))
    revision_id: Mapped[int] = mapped_column(ForeignKey("siege_page_revision.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Quarantine(Base):
    """Records we refused to ingest (unknown names, parse problems). Never counted in metrics."""

    __tablename__ = "siege_quarantine"
    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("siege_page_revision.id"))
    reason: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MapObservation(Base):
    """Append-only history of each map slot's data as we observed it over time.

    A row is added when a map is first seen finished, and whenever its data changes afterwards
    (correction, un-finished, or removed from the page). Stats "as of time T" read the latest row
    per slot with observed_at <= T, so later edits never change earlier values.
    """

    __tablename__ = "siege_map_observation"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("siege_match.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("siege_page_revision.id"))
    status: Mapped[str] = mapped_column(String(10))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)  # same shape as Match.content["maps"][i]
    __table_args__ = (
        CheckConstraint("status IN ('finished', 'skipped', 'unplayed', 'removed')", name="obs_status_valid"),
    )
