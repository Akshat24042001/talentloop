"""Relational data: companies, users, roles, jobs, candidates, applications, matches.

SQLite file locally (DATA_DIR/talentloop.db); Postgres in production via DATABASE_URL, for example a Supabase
"Session pooler" connection string. Interviews keep their own JSON store (store.py) and point here by id.
Tables are created on startup (create_all); new columns are added with additive checks in `migrate()`.
"""
import logging
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine,
                        event, inspect, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .store import DATA_DIR

log = logging.getLogger("db")


def _url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return f"sqlite:///{Path(DATA_DIR) / 'talentloop.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")
if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
else:
    # prepare_threshold=None: works behind Supabase's pooler (PgBouncer/Supavisor) in transaction mode too.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
                           connect_args={"prepare_threshold": None})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def new_id(n: int = 9) -> str:
    return secrets.token_urlsafe(n).replace("-", "x").replace("_", "y")


def now() -> float:
    return time.time()


class Base(DeclarativeBase):
    pass


class Org(Base):
    __tablename__ = "orgs"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    last_login_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    login_count: Mapped[int] = mapped_column(Integer, default=0)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120), default="")      # e.g. "Sales Manager"
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    expires_at: Mapped[float] = mapped_column(Float)
    accepted_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AuthSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    expires_at: Mapped[float] = mapped_column(Float)
    ip: Mapped[str] = mapped_column(String(64), default="")
    ua: Mapped[str] = mapped_column(String(300), default="")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")      # draft | open | paused | closed
    fields: Mapped[dict] = mapped_column(JSON, default=dict)               # every JD parameter
    top_n: Mapped[int] = mapped_column(Integer, default=5)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    published_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class JobCollaborator(Base):
    __tablename__ = "job_collaborators"
    __table_args__ = (UniqueConstraint("job_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    permission: Mapped[str] = mapped_column(String(20), default="editor")   # editor | reviewer
    added_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (Index("ix_candidates_org_email", "org_id", "email"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)      # structured: experience, education, skills, links...
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)       # free parse: skills, years, emails, phones
    resume_file: Mapped[str] = mapped_column(String(200), default="")
    resume_name: Mapped[str] = mapped_column(String(200), default="")
    resume_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="upload")   # careers | talent_pool | upload | bulk | demo
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20), default="applied")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    knockout_failed: Mapped[list] = mapped_column(JSON, default=list)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    interview_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="careers")
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    knocked_out: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_model: Mapped[str] = mapped_column(String(120), default="")
    ai_hash: Mapped[str] = mapped_column(String(64), default="")
    ai_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Activity(Base):
    __tablename__ = "activity"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[float] = mapped_column(Float, default=now, index=True)


class AIUsage(Base):
    """One row per AI call made by the platform (matching reports, JD writing): cost visibility for the admin."""
    __tablename__ = "ai_usage"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120), default="")
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[float] = mapped_column(Float, default=now)


def migrate() -> None:
    Base.metadata.create_all(engine)
    # Additive column checks go here as the schema evolves (create_all does not alter existing tables).
    insp = inspect(engine)
    want = {"users": {"login_count": "INTEGER DEFAULT 0"}}
    for table, cols in want.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for col, ddl in cols.items():
            if col not in have:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
    log.info("database ready (%s)", "sqlite" if IS_SQLITE else "postgres")


@contextmanager
def session() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
