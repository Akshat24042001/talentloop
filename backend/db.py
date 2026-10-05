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

import contextvars
import time as _time

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
    # No pool_pre_ping: it costs one network round trip on every checkout (Render Singapore <-> Supabase Mumbai is
    # ~50 ms). Instead a connection is checked only when it sat idle long enough for the pooler to have dropped it.
    engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=5, pool_recycle=300,
                           connect_args={"prepare_threshold": None, "keepalives": 1, "keepalives_idle": 30,
                                         "keepalives_interval": 10, "keepalives_count": 3})

    @event.listens_for(engine, "checkin")
    def _idle_from(dbapi_conn, record):
        record.info["idle_since"] = _time.monotonic()

    @event.listens_for(engine, "checkout")
    def _ping_if_idle(dbapi_conn, record, proxy):
        since = record.info.get("idle_since")
        if since is not None and _time.monotonic() - since > 30:
            try:
                cur = dbapi_conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                dbapi_conn.rollback()
            except Exception as e:
                from sqlalchemy import exc
                raise exc.DisconnectionError() from e     # the pool throws this connection away and opens a new one

    @event.listens_for(engine, "handle_error")
    def _lost_connection(ctx):
        """Treat 'the server closed this connection' errors (SQLSTATE 08xxx, 57P01-57P03: admin/crash shutdown, as when
        the pooler restarts) as a lost connection, so the pool discards it and the request retry gets a fresh one."""
        code = getattr(getattr(ctx, "original_exception", None), "sqlstate", None) or ""
        if code.startswith("08") or code in ("57P01", "57P02", "57P03"):
            ctx.is_disconnect = True
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
    email_verified_at: Mapped[float | None] = mapped_column(Float, nullable=True)   # None = has not confirmed the email yet


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120), default="")      # e.g. "Sales Manager"
    active: Mapped[bool] = mapped_column(Boolean, default=True)        # off = can't sign in to this company
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
    last_seen_at: Mapped[float | None] = mapped_column(Float, nullable=True)     # updated at most once a minute


class UserDay(Base):
    """One row per person per day they used the app (staff accounts), for daily/weekly/monthly active counts."""
    __tablename__ = "user_days"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)       # YYYY-MM-DD in REPORT_TZ
    user_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")      # draft | open | paused | closed
    fields: Mapped[dict] = mapped_column(JSON, default=dict)               # every JD parameter
    top_n: Mapped[int] = mapped_column(Integer, default=5)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)    # per company: readable URLs (title-slug-12)
    flow: Mapped[list | None] = mapped_column(JSON, nullable=True)        # hiring rounds, see flows.py
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
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Computed once whenever the resume or profile changes (matching.compute_features), so lists and matching
    # never re-read or re-tokenize resume text.
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    skills_text: Mapped[str] = mapped_column(Text, default="")          # "|java|spring boot|" for fast skill filters
    years: Mapped[float | None] = mapped_column(Float, nullable=True)
    notice_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_company: Mapped[str] = mapped_column(String(200), default="")
    college: Mapped[str] = mapped_column(String(200), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")   # resume + profile: AI report cache key
    photo_file: Mapped[str] = mapped_column(String(200), default="")    # live photo (campus registration, identity match)
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
    round_id: Mapped[str | None] = mapped_column(String(24), nullable=True)       # current round in the job's flow
    round_status: Mapped[str] = mapped_column(String(20), default="")              # see flows.ROUND_STATUSES
    drive_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    portal_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)   # candidate status page
    portal_token: Mapped[str] = mapped_column(String(64), default="")                    # so HR can copy the link
    human_requested_at: Mapped[float | None] = mapped_column(Float, nullable=True)       # asked for a human instead of AI
    human_request_note: Mapped[str] = mapped_column(Text, default="")
    accommodation: Mapped[dict | None] = mapped_column(JSON, nullable=True)        # {request, status, extra_time_pct}
    decided_at: Mapped[float | None] = mapped_column(Float, nullable=True)
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


class Counter(Base):
    """Per-company running numbers for readable references (jobs, candidates, interviews)."""
    __tablename__ = "counters"
    org_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class AppSecret(Base):
    """Server-side keys generated once (for example the key that encrypts ids in URLs)."""
    __tablename__ = "app_secrets"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class InterviewIndex(Base):
    """Summary row per AI interview (the full record stays in store.py), so lists never read every JSON file."""
    __tablename__ = "interview_index"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    candidate: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="created")
    channel: Mapped[str] = mapped_column(String(10), default="web")        # web | phone
    language: Mapped[str] = mapped_column(String(20), default="en")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # recommendation, overall, risk, warnings...
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class FlowTemplate(Base):
    __tablename__ = "flow_templates"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)   # None = built-in
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    rounds: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class RoundResult(Base):
    """One candidate in one round of a job's flow: a test attempt, a video, a task, an AI or human interview,
    a manager decision. `token_hash` lets the candidate (or a manager) open their page without signing in."""
    __tablename__ = "round_results"
    __table_args__ = (UniqueConstraint("application_id", "round_id"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(24), index=True)
    job_id: Mapped[str] = mapped_column(String(24), index=True)
    application_id: Mapped[str] = mapped_column(String(24), index=True)
    candidate_id: Mapped[str] = mapped_column(String(24), index=True)
    round_id: Mapped[str] = mapped_column(String(24))
    round_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)            # 0-100
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)               # answers, paper, transcript, booking...
    integrity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    manager_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    deadline_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(20), default="")                # pass | fail | hold (HR/manager)
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Question(Base):
    """Aptitude and domain question bank."""
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(24), index=True)
    section: Mapped[str] = mapped_column(String(60), index=True)                 # quantitative, logical, english...
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")        # easy | medium | hard
    kind: Mapped[str] = mapped_column(String(20), default="single")              # single | multiple | numeric
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[list] = mapped_column(JSON, default=list)                     # option indexes, or [number]
    marks: Mapped[float] = mapped_column(Float, default=1)
    explanation: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Drive(Base):
    """A campus drive: one college, one job, a registration link and QR code, a test window."""
    __tablename__ = "drives"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(24), index=True)
    job_id: Mapped[str] = mapped_column(String(24), index=True)
    college: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)       # public registration link
    share_code: Mapped[str] = mapped_column(String(40), unique=True, index=True) # results link for the placement officer
    opens_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    closes_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")             # open | closed
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Message(Base):
    """Every email or WhatsApp message to a candidate or manager (the outbox and its delivery status)."""
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(24), index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    channel: Mapped[str] = mapped_column(String(10))                             # email | whatsapp
    to: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")           # queued | sent | failed | not_configured
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)
    sent_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Slot(Base):
    """An interviewer's available time for a human round; candidates book one themselves."""
    __tablename__ = "slots"
    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(24), index=True)
    job_id: Mapped[str] = mapped_column(String(24), index=True)
    round_id: Mapped[str] = mapped_column(String(24))
    interviewer_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    starts_at: Mapped[float] = mapped_column(Float, index=True)
    ends_at: Mapped[float] = mapped_column(Float)
    meeting_url: Mapped[str] = mapped_column(String(500), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    booked_by: Mapped[str | None] = mapped_column(String(24), nullable=True)     # round_results.id
    created_at: Mapped[float] = mapped_column(Float, default=now)


def migrate() -> None:
    Base.metadata.create_all(engine)
    # Additive column checks go here as the schema evolves (create_all does not alter existing tables).
    insp = inspect(engine)
    js = "JSON"
    want = {
        "users": {"login_count": "INTEGER DEFAULT 0"},
        "sessions": {"last_seen_at": "FLOAT"},
        "memberships": {"active": "BOOLEAN DEFAULT TRUE"},
        "jobs": {"number": "INTEGER", "flow": js},
        "candidates": {"number": "INTEGER", "features": js, "skills_text": "TEXT DEFAULT ''", "years": "FLOAT",
                       "notice_days": "FLOAT", "expected_salary": "FLOAT", "current_company": "VARCHAR(200) DEFAULT ''",
                       "college": "VARCHAR(200) DEFAULT ''", "content_hash": "VARCHAR(64) DEFAULT ''", "photo_file": "VARCHAR(200) DEFAULT ''"},
        "applications": {"round_id": "VARCHAR(24)", "round_status": "VARCHAR(20) DEFAULT ''", "drive_id": "VARCHAR(24)",
                         "portal_token_hash": "VARCHAR(64) DEFAULT ''", "portal_token": "VARCHAR(64) DEFAULT ''", "human_requested_at": "FLOAT", "human_request_note": "TEXT DEFAULT ''",
                         "accommodation": js, "decided_at": "FLOAT"},
    }
    if "email_verified_at" not in {c["name"] for c in insp.get_columns("users")}:
        # accounts made before email confirmation existed are trusted as they are (once, when the column is added)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at FLOAT"))
            conn.execute(text("UPDATE users SET email_verified_at = created_at"))
    for table, cols in want.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for col, ddl in cols.items():
            if col not in have:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
    with engine.begin() as conn:
        for ddl in ("CREATE INDEX IF NOT EXISTS ix_jobs_org_number ON jobs (org_id, number)",
                    "CREATE INDEX IF NOT EXISTS ix_candidates_org_number ON candidates (org_id, number)",
                    "CREATE INDEX IF NOT EXISTS ix_candidates_org_created ON candidates (org_id, created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_applications_portal ON applications (portal_token_hash)",
                    "CREATE INDEX IF NOT EXISTS ix_matches_job_rank ON matches (job_id, rank)",
                    "CREATE INDEX IF NOT EXISTS ix_activity_org_at ON activity (org_id, at)"):
            conn.execute(text(ddl))
    if engine.dialect.name == "postgresql":          # app_secrets.value was VARCHAR(200); settings like the model choice are longer
        cols = {c["name"]: c for c in insp.get_columns("app_secrets")}
        if "value" in cols and getattr(cols["value"]["type"], "length", None):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE app_secrets ALTER COLUMN value TYPE TEXT"))
    _backfill_numbers()
    log.info("database ready (%s)", "sqlite" if IS_SQLITE else "postgres")


def next_number(s: Session, org_id: str, kind: str) -> int:
    """Next running number for this company and kind (jobs, candidates, interviews). Row-locked on Postgres."""
    row = s.query(Counter).filter_by(org_id=org_id, kind=kind).with_for_update().first()
    if row is None:
        row = Counter(org_id=org_id, kind=kind, value=0)
        s.add(row)
        s.flush()
    row.value += 1
    s.flush()
    return row.value


def _backfill_numbers() -> None:
    """Give older jobs and candidates their readable numbers (once)."""
    with session() as s:
        for model, kind in ((Job, "job"), (Candidate, "candidate")):
            missing = s.query(model.org_id).filter(model.number.is_(None)).distinct().all()
            for (org_id,) in missing:
                rows = s.query(model).filter(model.org_id == org_id, model.number.is_(None)).order_by(model.created_at).all()
                for r in rows:
                    r.number = next_number(s, org_id, kind)


# Per-request database timing for the Server-Timing header (main.py). A mutable box in a context variable: request
# handlers run in worker threads that copy the context, and they add to the same box.
_timing_box: contextvars.ContextVar[list | None] = contextvars.ContextVar("db_timing", default=None)


def start_timing() -> list:
    box = [0, 0.0]
    _timing_box.set(box)
    return box


@event.listens_for(engine, "before_cursor_execute")
def _q_start(conn, cursor, statement, parameters, context, executemany):
    conn.info["_t0"] = _time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _q_end(conn, cursor, statement, parameters, context, executemany):
    box = _timing_box.get()
    if box is not None:
        box[0] += 1
        box[1] += (_time.perf_counter() - conn.info.get("_t0", _time.perf_counter())) * 1000


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
