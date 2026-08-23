"""
Party Check-In System — Utilities
Database, QR generation, email, and helper functions.
Works with Streamlit (no Flask dependencies).
"""

import hashlib
import html
import os
import io
import base64
import csv
import re
import smtplib
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from functools import lru_cache
from hmac import compare_digest

import qrcode

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey,
    func, inspect, or_, case, select, insert, text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker, Session

import streamlit as st

import config

# ── Configuration ─────────────────────────────────────────────────────────────

# Longest a single person's name may be (sanitize_name enforces it, and the
# `name` columns are sized to match).
MAX_NAME_LENGTH = 100

# One ticket per person, and the booker holds the first one, so the largest
# possible booking names one fewer guest than it has tickets. Derived from the
# constant the Register page clamps its selector to, so the ticket selector and
# the name list can never disagree about the maximum party.
MAX_GUEST_NAMES = config.MAX_TICKETS_PER_REGISTRATION - 1

# How much room a stored guest-name list needs: every name at its maximum
# length, plus the newline joining it to the next. Derived rather than fixed
# because it has to grow with MAX_TICKETS_PER_REGISTRATION — a hardcoded width
# would quietly truncate the tail of a large booking's guest list the moment
# the cap was raised, losing real people off the door list with no error.
#
# This sizes three things that must agree: the plus_one_name columns below,
# the ALTER in init_db() that widens them on an existing Postgres database,
# and the Register form's name box (streamlit_app passes it as max_chars).
GUEST_NAMES_MAX_CHARS = MAX_GUEST_NAMES * (MAX_NAME_LENGTH + 1)

Base = declarative_base()


def _utc_now():
    """Return a naive UTC datetime (replacement for deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_secret(key: str, default="") -> str:
    """Read from st.secrets first, then env var, then default.

    NOTE: this is intentionally separate from config.get_secret(). It refers
    to this module's own `st` symbol so that tests which do
    `patch('utils.st')` correctly control every secret read that affects
    tested behavior (MAIL_*, ADMIN_PASSWORD, DATABASE_URL, TICKET_PRICE_CENTS).
    config.get_secret() reads the real streamlit module and is used only for
    values that aren't exercised by the mocked-secrets test suite (event
    strings, APP_URL, Zelle display info for the UI layer).
    """
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


# ── Database Models ───────────────────────────────────────────────────────────

class Guest(Base):
    __tablename__ = "guests"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=False, index=True)
    phone = Column(String(30), default="")
    ticket_count = Column(Integer, default=1)
    # Sized from GUEST_NAMES_MAX_CHARS so it grows with
    # config.MAX_TICKETS_PER_REGISTRATION — see init_db() for the migration
    # that widens it on an existing database.
    plus_one_name = Column(String(GUEST_NAMES_MAX_CHARS), default="")  # bulk guest names, newline-separated
    zelle_ref = Column(String(100), default="")  # Zelle transaction reference
    qr_code = Column(String(200), unique=True)
    checked_in = Column(Boolean, default=False, index=True)
    band_given = Column(Boolean, default=False)
    checkin_time = Column(DateTime)
    created_at = Column(DateTime, default=_utc_now, index=True)
    veg_count = Column(Integer, default=0)
    non_veg_count = Column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "ticket_count": self.ticket_count,
            "plus_one_name": self.plus_one_name,
            "zelle_ref": self.zelle_ref,
            "qr_code": self.qr_code,
            "checked_in": self.checked_in,
            "band_given": self.band_given,
            "checkin_time": self.checkin_time.isoformat() if self.checkin_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "veg_count": self.veg_count,
            "non_veg_count": self.non_veg_count,
        }


class CheckInLog(Base):
    __tablename__ = "checkin_logs"

    id = Column(Integer, primary_key=True)
    guest_id = Column(Integer, ForeignKey("guests.id"))
    action = Column(String(50))  # 'checkin', 'band_given'
    timestamp = Column(DateTime, default=_utc_now)
    device_info = Column(String(200))


class PageVisit(Base):
    """Lightweight page-visit counter for fun traffic stats."""
    __tablename__ = "page_visits"

    id = Column(Integer, primary_key=True)
    visitor_token = Column(String(64), nullable=False, index=True)
    page = Column(String(50), default="Home")
    visited_at = Column(DateTime, default=_utc_now)


class SubmissionLog(Base):
    """Audit trail for every registration form submission attempt.

    Tracks both successful registrations and failed attempts (validation errors,
    duplicate emails, etc.) so organisers can see how many people tried to
    register, where they got stuck, and which entries succeeded.
    """
    __tablename__ = "submission_logs"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), default="")
    email = Column(String(120), default="")
    phone = Column(String(30), default="")
    ticket_count = Column(Integer, default=1)
    plus_one_name = Column(String(GUEST_NAMES_MAX_CHARS), default="")
    zelle_ref = Column(String(100), default="")
    status = Column(String(50), default="attempted")  # attempted, validation_error, duplicate_email, registered, email_failed
    errors = Column(String(500), default="")
    guest_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    veg_count = Column(Integer, default=0)
    non_veg_count = Column(Integer, default=0)


class AppSetting(Base):
    """Persistent key/value store for admin-controlled settings.

    Unlike st.session_state, rows here survive process restarts and are
    visible to every user/session — needed for things like the check-in
    window override, which must be a single organiser-wide switch.
    """
    __tablename__ = "app_settings"

    key = Column(String(50), primary_key=True)
    value = Column(String(200), default="")
    updated_at = Column(DateTime, default=_utc_now)


# ── Database Engine & Session ─────────────────────────────────────────────────

def _normalize_postgres_url(db_url: str) -> str:
    """Normalize any PostgreSQL URL to use the installed driver.

    Supabase and other providers supply URLs in several forms (postgres://,
    postgresql://, postgresql+psycopg://, postgresql+psycopg2://, etc.).
    This strips any existing driver suffix and applies a driver that we
    know is available in the deployed environment.
    """
    # Strip the protocol prefix, keeping user/pass/host/db
    if db_url.startswith("postgres://"):
        body = db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        body = db_url[len("postgresql://"):]
    elif db_url.startswith("postgresql+"):
        # e.g. postgresql+psycopg:// or postgresql+psycopg2://
        body = db_url.split("://", 1)[1] if "://" in db_url else db_url.split("//", 1)[1]
    else:
        return db_url
    return f"postgresql+psycopg2://{body}"


def _get_engine_url_hash() -> str:
    """Return a stable hash of the configured DATABASE_URL for cache busting."""
    db_url = _get_secret("DATABASE_URL", "sqlite:///party_guests.db")
    db_url = _normalize_postgres_url(db_url)
    return hashlib.sha256(db_url.encode("utf-8")).hexdigest()[:16]


@st.cache_resource(show_spinner=False)
def _get_engine_cached(_db_url_hash: str = ""):
    """Create a cached SQLAlchemy engine keyed by the DATABASE_URL hash.

    Falls back to a local SQLite database if the configured DATABASE_URL
    cannot be reached (e.g., paused Supabase project or missing secret).
    """
    db_url = _get_secret("DATABASE_URL", "sqlite:///party_guests.db")
    db_url = _normalize_postgres_url(db_url)

    # Log safe diagnostics (driver only, never the password)
    print(f"DATABASE_URL driver prefix: {db_url.split('://')[0] if '://' in db_url else 'none'}")
    try:
        import importlib
        importlib.import_module("psycopg2")
        print("psycopg2 import: OK")
    except Exception as imp_err:
        print(f"psycopg2 import: FAILED - {imp_err}")

    # pool_size/max_overflow/pool_recycle are Postgres-pool-specific kwargs;
    # SQLite's pool (SingletonThreadPool/NullPool) rejects them, so only pass
    # them down the Postgres path.
    is_postgres = db_url.startswith("postgresql")
    engine_kwargs = {"pool_pre_ping": True, "echo": False}
    if is_postgres:
        engine_kwargs.update(pool_size=5, max_overflow=10, pool_recycle=1800)

    try:
        engine = create_engine(db_url, **engine_kwargs)
        # Validate the connection by listing table names
        inspector = inspect(engine)
        inspector.get_table_names()
        print("DATABASE_URL connection: OK")
        return engine
    except Exception as e:
        err_msg = str(e).lower()
        # Try the pure-Python pg8000 driver as a fallback if psycopg2 fails
        if "psycopg2" in err_msg and "pg8000" not in db_url:
            try:
                pg_url = db_url.replace("postgresql+psycopg2://", "postgresql+pg8000://", 1)
                print("psycopg2 failed, trying pg8000 driver")
                engine = create_engine(pg_url, **engine_kwargs)
                inspector = inspect(engine)
                inspector.get_table_names()
                print("DATABASE_URL connection via pg8000: OK")
                return engine
            except Exception as e2:
                print(f"pg8000 fallback also failed: {e2}")
        # Log the failure without exposing the full URL in the UI
        print(f"DATABASE_URL connection failed, falling back to SQLite: {e}")
        fallback_url = "sqlite:///party_guests.db"
        return create_engine(fallback_url, echo=False)


def get_engine():
    """Return the cached engine, automatically re-creating it if the DATABASE_URL secret changed."""
    return _get_engine_cached(_get_engine_url_hash())


def _using_fallback_db() -> bool:
    """Return True if the active engine is the SQLite fallback."""
    return get_engine().url.drivername.startswith("sqlite")


def db_degraded() -> bool:
    """True when a real DATABASE_URL was configured but we fell back to SQLite.

    This is the dangerous case, and it is NOT the same as simply running on
    SQLite. Locally (and in the test suite) DATABASE_URL is deliberately a
    sqlite:// URL, which is fine. But in production DATABASE_URL points at
    Supabase, and if that is unreachable when the app boots — a paused
    project, a network blip, or Postgres connection limits exhausted during a
    registration rush — _get_engine_cached() silently falls back to an
    ephemeral SQLite file inside the Streamlit container.

    Without this check the app would keep cheerfully accepting registrations
    and emailing QR codes into a database that disappears on the next
    restart. Callers use this to refuse writes instead, so a guest is told to
    come back rather than being quietly lost.
    """
    configured = _get_secret("DATABASE_URL", "")
    if not configured or configured.strip().startswith("sqlite"):
        return False  # intentionally local — dev machine or test suite
    return _using_fallback_db()


DB_DEGRADED_MESSAGE = (
    "We can't reach the guest database right now, so we've paused sign-ups for a moment "
    "to make sure nothing gets lost. Nothing you've done is affected. "
    "Please try again in a few minutes — and if it keeps happening, message the organiser."
)


@st.cache_resource(show_spinner=False)
def get_session_factory():
    """Create a cached session factory."""
    return sessionmaker(bind=get_engine())


def _ensure_unique_email_index(engine) -> None:
    """Best-effort creation of a UNIQUE index on guests(email).

    Only attempted when no duplicate emails already exist in the table, so
    this never breaks startup against an existing production table that may
    already contain duplicates. Any failure is caught and logged, never
    raised.
    """
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            dup_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT email FROM guests GROUP BY email HAVING COUNT(*) > 1"
                    ") AS dupes"
                )
            ).scalar()
            if dup_count:
                print(f"Skipping unique email index: {dup_count} duplicate email(s) present")
                return
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_guests_email_unique ON guests (email)")
            )
            conn.commit()
    except Exception as e:
        print(f"Unique email index creation skipped: {e}")


def _ensure_secondary_indexes(engine) -> None:
    """Create the non-unique indexes the hot queries rely on, if missing.

    Columns declared `index=True` on the models only get their index when
    SQLAlchemy CREATEs the table. On a database whose tables already existed
    before those declarations were added (i.e. production), create_all() is a
    no-op and the indexes are silently absent — which is exactly what a live
    inspection of the Supabase database showed: guests had only the two unique
    indexes, while the admin dashboard filters on checked_in and orders by
    created_at on every load.

    CREATE INDEX IF NOT EXISTS is supported by both PostgreSQL and SQLite, so
    this is idempotent and cheap. Failures are logged, never raised — this
    runs at startup against the live database.
    """
    from sqlalchemy import text

    indexes = [
        ("ix_guests_checked_in", "guests", "checked_in"),
        ("ix_guests_created_at", "guests", "created_at"),
        ("ix_page_visits_visited_at", "page_visits", "visited_at"),
        ("ix_submission_logs_created_at", "submission_logs", "created_at"),
        ("ix_checkin_logs_guest_id", "checkin_logs", "guest_id"),
    ]
    for name, table, column in indexes:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
                conn.commit()
        except Exception as e:
            print(f"Index {name} creation skipped: {e}")


def init_db():
    """Create tables if they don't exist and set up reporting views on Postgres."""
    engine = get_engine()
    inspector = inspect(engine)
    existing = inspector.get_table_names()

    # Create any missing tables (idempotent)
    Base.metadata.create_all(engine)

    # Migration for existing DBs that pre-date the new columns
    if "guests" in existing:
        cols = [c["name"] for c in inspector.get_columns("guests")]
        if "zelle_ref" not in cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE guests ADD COLUMN zelle_ref VARCHAR(100) DEFAULT ''"))
                conn.commit()
        if "phone" not in cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE guests ADD COLUMN phone VARCHAR(30) DEFAULT ''"))
                conn.commit()
        if "plus_one_name" not in cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE guests ADD COLUMN plus_one_name VARCHAR(100) DEFAULT ''"))
                conn.commit()
        if "veg_count" not in cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE guests ADD COLUMN veg_count INTEGER DEFAULT 0"))
                conn.commit()
        if "non_veg_count" not in cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE guests ADD COLUMN non_veg_count INTEGER DEFAULT 0"))
                conn.commit()

    # Migration for existing submission_logs tables that pre-date the meal
    # count columns — mirrors the guests-table blocks above.
    if "submission_logs" in existing:
        sub_cols = [c["name"] for c in inspector.get_columns("submission_logs")]
        if "veg_count" not in sub_cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE submission_logs ADD COLUMN veg_count INTEGER DEFAULT 0"))
                conn.commit()
        if "non_veg_count" not in sub_cols:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE submission_logs ADD COLUMN non_veg_count INTEGER DEFAULT 0"))
                conn.commit()

    # Widen plus_one_name to fit a full bulk guest-name list. The target width
    # is GUEST_NAMES_MAX_CHARS, derived from config.MAX_TICKETS_PER_REGISTRATION,
    # so raising the ticket cap widens the column on the next boot instead of
    # silently truncating the tail of a large booking's guest list.
    #
    # Idempotent: re-running ALTER COLUMN ... TYPE VARCHAR(n) on a column that
    # is already that wide is a harmless metadata-only no-op on PostgreSQL, and
    # widening never rewrites the table. SQLite doesn't enforce VARCHAR length
    # at all, so there's nothing to migrate there. Runs against the live
    # production table, so every failure is swallowed and logged rather than
    # raised — a column that stays wider than needed (because the cap was
    # lowered) is harmless, and the app must boot either way.
    if not _using_fallback_db():
        from sqlalchemy import text
        width = int(GUEST_NAMES_MAX_CHARS)
        for table, column in (("guests", "plus_one_name"), ("submission_logs", "plus_one_name")):
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR({width})"))
                    conn.commit()
            except Exception as e:
                print(f"Migration skipped: widen {table}.{column} to VARCHAR({width}): {e}")

    _ensure_secondary_indexes(engine)

    # Enforce email uniqueness at the DB level when it's safe to do so.
    _ensure_unique_email_index(engine)

    # Create reporting views on PostgreSQL/Supabase only
    if not _using_fallback_db():
        try:
            _create_postgres_views(engine)
        except Exception as e:
            print(f"Postgres view creation skipped: {e}")


@st.cache_resource(show_spinner=False)
def ensure_db_ready() -> None:
    """Run init_db() exactly once per process.

    streamlit_app.py calls this at module top level instead of init_db()
    directly. Streamlit re-executes the whole script on every user
    interaction, so calling the uncached init_db() there would run
    inspect().get_table_names(), create_all(), and several
    CREATE OR REPLACE VIEW statements against the remote database on every
    single click. @st.cache_resource makes sure the real work happens once
    per process. Tests call init_db() directly and are unaffected.
    """
    init_db()


def get_db() -> Session:
    """Get a new DB session."""
    factory = get_session_factory()
    return factory()


# ── App Settings (persistent, organiser-wide) ──────────────────────────────
# Backed by the app_settings table rather than st.session_state so an admin
# override (e.g. forcing check-in open/closed) survives restarts and applies
# to every user's session, not just the admin's own browser tab.

def get_setting(key: str, default: str = "") -> str:
    """Return a persisted app setting's value, or `default` if unset/on error."""
    session = get_db()
    try:
        row = session.query(AppSetting).filter_by(key=key).first()
        return row.value if row is not None else default
    except Exception as e:
        print(f"get_setting({key!r}) failed: {e}")
        return default
    finally:
        session.close()


def set_setting(key: str, value: str) -> None:
    """Create or update a persisted app setting. Safe to call frequently."""
    session = get_db()
    try:
        row = session.query(AppSetting).filter_by(key=key).first()
        if row is None:
            session.add(AppSetting(key=key, value=value, updated_at=_utc_now()))
        else:
            row.value = value
            row.updated_at = _utc_now()
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"set_setting({key!r}) failed: {e}")
    finally:
        session.close()


CHECKIN_MODE_AUTO = "auto"      # open once now >= config.checkin_opens_at_utc()
CHECKIN_MODE_OPEN = "open"      # always open (admin forced it, e.g. for a rehearsal)
CHECKIN_MODE_CLOSED = "closed"  # always closed

_CHECKIN_MODE_SETTING_KEY = "checkin_mode"
_VALID_CHECKIN_MODES = (CHECKIN_MODE_AUTO, CHECKIN_MODE_OPEN, CHECKIN_MODE_CLOSED)


def get_checkin_mode() -> str:
    """Return the persisted check-in mode, defaulting to 'auto' when unset or invalid.

    Always a fresh DB read (not cached) — the admin dashboard's Check-in
    Window control and several tests write app_settings directly and expect
    this to reflect it immediately. See _cached_checkin_mode() for the
    short-TTL cached read used by the hot scan path.
    """
    mode = get_setting(_CHECKIN_MODE_SETTING_KEY, CHECKIN_MODE_AUTO)
    return mode if mode in _VALID_CHECKIN_MODES else CHECKIN_MODE_AUTO


_CHECKIN_MODE_CACHE_TTL_SECONDS = 5


@st.cache_resource(show_spinner=False)
def _checkin_mode_cache_state() -> dict:
    """Process-global cache for the check-in mode, shared across sessions.

    {"value": str|None, "expires_at": float (time.monotonic()), "lock":
    threading.Lock()}. `value` is None whenever the cache is cold/invalidated.
    """
    return {"value": None, "expires_at": 0.0, "lock": threading.Lock()}


def _cached_checkin_mode() -> str:
    """Return get_checkin_mode(), cached for a few seconds (process-global).

    check_in_by_code() re-checks the check-in mode before every single
    lookup — under a door queue that's an app_settings SELECT per scan for
    no reason, since the mode only ever changes when an admin flips it.
    Cached here with a short TTL so repeated scans don't pay for it, while
    set_checkin_mode() invalidates this immediately so an admin's change
    still takes effect within, at most, _CHECKIN_MODE_CACHE_TTL_SECONDS.
    """
    state = _checkin_mode_cache_state()
    now = time.monotonic()
    with state["lock"]:
        if state["value"] is not None and now < state["expires_at"]:
            return state["value"]
    value = get_checkin_mode()
    with state["lock"]:
        state["value"] = value
        state["expires_at"] = time.monotonic() + _CHECKIN_MODE_CACHE_TTL_SECONDS
    return value


def set_checkin_mode(mode: str) -> None:
    """Persist the check-in mode.

    Raises ValueError if `mode` isn't one of CHECKIN_MODE_AUTO/OPEN/CLOSED.
    Invalidates _cached_checkin_mode()'s cache immediately so the change is
    visible to the next scan/status read, not up to
    _CHECKIN_MODE_CACHE_TTL_SECONDS later.
    """
    if mode not in _VALID_CHECKIN_MODES:
        raise ValueError(f"Invalid checkin mode: {mode!r} (expected one of {_VALID_CHECKIN_MODES})")
    set_setting(_CHECKIN_MODE_SETTING_KEY, mode)
    state = _checkin_mode_cache_state()
    with state["lock"]:
        state["value"] = None
        state["expires_at"] = 0.0


def checkin_status(use_cache: bool = False) -> dict:
    """Return the current check-in gate status.

    {"open": bool, "mode": str, "opens_at_utc": datetime, "opens_at_text": str,
     "message": str}

    - "auto"   -> open only once _utc_now() >= config.checkin_opens_at_utc().
    - "open"   -> always open (admin override for a rehearsal, early admits, etc).
    - "closed" -> always closed (admin override).

    `message` is a user-facing explanation for the Scanner page, populated
    whenever check-in is currently closed; empty string when open.

    use_cache=False (the default) reads the mode fresh via get_checkin_mode()
    every time — this is what page renders (the Scanner gate, the Admin
    banner) must use, so a mode change is reflected the instant it happens,
    not up to _CHECKIN_MODE_CACHE_TTL_SECONDS later. It is also what keeps
    this function safe to call from a different OS process than the one that
    wrote the change (e.g. the e2e test harness's DB-seeding process vs. the
    Streamlit server subprocess it drives) — _cached_checkin_mode()'s cache
    is process-global, not cross-process, so a stale cache in the
    *rendering* process would otherwise linger for up to the TTL after an
    out-of-band write.

    use_cache=True reads the (briefly cached) mode via _cached_checkin_mode()
    instead — check_in_by_code() opts into this because it is the function
    that runs on every single scan attempt in a door queue, so it is the one
    that actually benefits from not hitting app_settings every time. Either
    way, the "auto" mode's open/closed transition is computed fresh against
    _utc_now() on every call, so the event-time window itself is never stale.
    """
    mode = _cached_checkin_mode() if use_cache else get_checkin_mode()
    opens_at_utc = config.checkin_opens_at_utc()
    opens_at_text = config.checkin_opens_at_text()

    if mode == CHECKIN_MODE_OPEN:
        is_open = True
        message = ""
    elif mode == CHECKIN_MODE_CLOSED:
        is_open = False
        message = "Check-in is currently closed by the organiser."
    else:  # CHECKIN_MODE_AUTO
        is_open = _utc_now() >= opens_at_utc
        message = "" if is_open else f"Check-in opens {opens_at_text}."

    return {
        "open": is_open,
        "mode": mode,
        "opens_at_utc": opens_at_utc,
        "opens_at_text": opens_at_text,
        "message": message,
    }


# ── Capacity Guard ────────────────────────────────────────────────────────────
# Streamlit Community Cloud's free tier is a single Python process with
# ~1GB RAM and a shared vCPU. If a registration link goes out to ~700
# people and ~200 open it at once, the honest options are: let it fall
# over, or degrade politely. The owner's ask was explicit: never leave
# someone who already loaded the app stranded — slow it down for new
# arrivals instead. touch_session()/active_session_count() track how many
# browser sessions have been active in the last ACTIVE_WINDOW_SECONDS,
# process-global (shared across every session, like the visit buffer
# above) so the whole app agrees on one number.

ACTIVE_WINDOW_SECONDS = 60


@st.cache_resource(show_spinner=False)
def _active_sessions_state() -> dict:
    """Process-global registry of session heartbeats, shared across sessions.

    {"sessions": {session_id: float (time.monotonic() of last touch)},
     "lock": threading.Lock()}.
    """
    return {"sessions": {}, "lock": threading.Lock()}


def _prune_active_sessions_locked(state: dict, now: float) -> None:
    """Drop heartbeats older than ACTIVE_WINDOW_SECONDS. Caller must hold the lock."""
    cutoff = now - ACTIVE_WINDOW_SECONDS
    stale = [sid for sid, ts in state["sessions"].items() if ts < cutoff]
    for sid in stale:
        del state["sessions"][sid]


def _runtime_session_count():
    """True number of browser sessions connected to this server, or None.

    Streamlit's own runtime knows exactly which WebSocket sessions are live,
    which is far more accurate than counting recently-seen tokens: our
    visitor_token lives in st.session_state, and Streamlit creates a NEW
    session on every page load/refresh. So one guest who refreshes once, or
    opens the emailed "?page=My QR" link after browsing, would otherwise be
    counted as two or three concurrent visitors for the whole prune window —
    and the capacity guard would start turning real people away long before
    the app was actually busy.

    This is a private API, so it is fully guarded and pinned-version-only;
    callers fall back to the token heuristic when it isn't available.
    """
    try:
        from streamlit.runtime import get_instance

        return len(get_instance()._session_mgr.list_active_sessions())
    except Exception:
        return None


def touch_session(session_id: str) -> int:
    """Register `session_id` as active right now; return the active-session count.

    Called once per Streamlit script run (see streamlit_app.main()). Cheap
    and DB-free — this is an in-memory dict update, not a query, so it costs
    nothing extra during a burst. Prunes stale entries on every call so the
    registry can never grow unbounded across a long-running process.

    Prefers Streamlit's real connected-session count and falls back to the
    token registry (e.g. when running outside a Streamlit server, as the
    tests do).
    """
    state = _active_sessions_state()
    now = time.monotonic()
    with state["lock"]:
        state["sessions"][session_id] = now
        _prune_active_sessions_locked(state, now)
        fallback = len(state["sessions"])
    real = _runtime_session_count()
    return real if real is not None else fallback


def active_session_count() -> int:
    """Return the current active-session count without registering a touch.

    Used by the admin Overview so the organiser can watch live load without
    that read itself counting as a visitor session.
    """
    state = _active_sessions_state()
    now = time.monotonic()
    with state["lock"]:
        _prune_active_sessions_locked(state, now)
        fallback = len(state["sessions"])
    real = _runtime_session_count()
    return real if real is not None else fallback


def _named_guests_expr():
    """SQL expression: how many additional guests one row names.

    plus_one_name holds the names newline-joined (see guest_names_list), so
    the count is "newlines + 1", and "newlines" is the classic portable
    length-minus-length-without-the-separator trick. Both halves —
    length() and replace() — mean the same thing on SQLite and PostgreSQL,
    which keeps get_stats() a single aggregate SELECT instead of pulling
    every guest's names back into Python just to len() them.

    A blank/NULL column counts as 0, not 1.
    """
    names = func.coalesce(Guest.plus_one_name, "")
    return case(
        (names == "", 0),
        else_=func.length(names) - func.length(func.replace(names, "\n", "")) + 1,
    )


def _expected_revenue_cents(session) -> int:
    """Total the guest list should have brought in, in cents.

    Group discounts are priced per booking (see config.GROUP_DISCOUNT_TIERS),
    so this has to charge each booking at its own tier and sum the results —
    `total_tickets × base_price` would over-state the take on every group.

    Integer cents throughout: this figure is meant to be reconciled against a
    Zelle history line by line, so it must not accumulate float error across
    a couple of hundred bookings.
    """
    total_cents = 0
    for ticket_count, bookings in session.query(
        Guest.ticket_count, func.count(Guest.id)
    ).group_by(Guest.ticket_count):
        count = int(ticket_count or 0)
        total_cents += int(bookings) * count * config.ticket_price_cents_for(count)
    return total_cents


def get_stats() -> dict:
    """Return current event statistics.

    Computed via a SINGLE aggregate SELECT (COUNT/SUM/CASE) instead of seven
    separate round trips to the database — on a remote Postgres connection
    each round trip costs real latency, and this is read on nearly every
    page render. COALESCE guards every SUM so an empty `guests` table
    yields 0 (never NULL/None), and the derived percentages below use the
    same "if total else 0.0" guard as before so a fresh install never
    divides by zero. Works on both SQLite and PostgreSQL — case()/func.sum
    are portable SQLAlchemy constructs, no raw SQL.

    Head counts, all of which differ and all of which an organiser asks for:
    total_guests is bookings (rows), total_tickets is people paid for,
    named_guests is the additional people actually named on those bookings,
    and unnamed_tickets is the gap between the two — non-zero only for
    bookings made before guest names were required, since
    validate_registration() now refuses a mismatch.
    """
    session = get_db()
    try:
        row = session.query(
            func.count(Guest.id),
            func.coalesce(func.sum(case((Guest.checked_in == True, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Guest.band_given == True, 1), else_=0)), 0),
            func.coalesce(func.sum(Guest.ticket_count), 0),
            func.coalesce(
                func.sum(case((Guest.checked_in == True, Guest.ticket_count), else_=0)), 0
            ),
            func.coalesce(func.sum(case((Guest.plus_one_name != "", 1), else_=0)), 0),
            func.coalesce(func.sum(_named_guests_expr()), 0),
            func.coalesce(func.sum(Guest.veg_count), 0),
            func.coalesce(func.sum(Guest.non_veg_count), 0),
        ).one()

        total = int(row[0])
        checked_in = int(row[1])
        bands = int(row[2])
        tickets = int(row[3])
        admitted_tickets = int(row[4])
        plus_one_count = int(row[5])
        named_guests = int(row[6])
        veg_total = int(row[7])
        non_veg_total = int(row[8])
        # Clamped: a row hand-edited to name more people than it has tickets
        # would otherwise report a negative gap.
        unnamed_tickets = max(tickets - total - named_guests, 0)

        # Average tickets per guest
        avg_tickets = round(tickets / total, 2) if total else 0.0

        # Check-in percentage
        checkin_pct = round(checked_in / total * 100, 1) if total else 0.0

        # Estimated revenue. Not tickets × one price: group discounts price
        # each BOOKING by its own size (config.ticket_price_cents_for), so a
        # flat multiply would over-report what the organiser should actually
        # find in their Zelle history. Grouping by ticket_count keeps this to
        # one extra aggregate query — at most ~30 rows back, one per possible
        # booking size — rather than reading every guest row.
        revenue = round(_expected_revenue_cents(session) / 100, 2)

        return {
            "total_guests": total,
            "checked_in": checked_in,
            "bands_distributed": bands,
            "pending": total - checked_in,
            "total_tickets": tickets,
            "admitted_tickets": admitted_tickets,
            "plus_one_count": plus_one_count,
            "named_guests": named_guests,
            "unnamed_tickets": unnamed_tickets,
            "avg_tickets_per_guest": avg_tickets,
            "checkin_percentage": checkin_pct,
            "revenue": revenue,
            "veg_total": veg_total,
            "non_veg_total": non_veg_total,
        }
    finally:
        session.close()


# ── Ticket Capacity ───────────────────────────────────────────────────────────
# A hard cap on tickets sold across all guests (config.max_total_tickets()).
# Distinct from the Capacity Guard above: that one throttles how many people
# browse at once, this one is the venue's real limit on how many can come.

_TICKET_CAP_LOCK_KEY = 0x50415254  # "PART" — app-specific advisory-lock id


def tickets_sold(session=None) -> int:
    """Return the total number of tickets registered so far.

    Pass an open `session` to count inside a caller's transaction (that's
    what makes the check in register_guest() authoritative); omit it for a
    standalone read. Guests are never partially counted — a registration is
    one row carrying its whole ticket_count.
    """
    own_session = session is None
    session = session or get_db()
    try:
        return int(session.query(func.coalesce(func.sum(Guest.ticket_count), 0)).scalar() or 0)
    finally:
        if own_session:
            session.close()


def ticket_availability() -> dict:
    """Return the current ticket-capacity picture for the UI.

    {"cap": int, "sold": int, "remaining": int, "sold_out": bool,
    "unlimited": bool}. `remaining` is clamped at 0 so an over-sold table
    (cap lowered after the fact) never renders a negative count.

    Must never raise: this is read on the Home and Register render paths, so
    a DB blip falls back to "unlimited" (cap unknown → nothing shown, form
    stays open) rather than wrongly telling guests the party is sold out.
    register_guest() re-checks the real number inside its transaction, so
    failing open here cannot oversell anything.
    """
    cap = 0
    try:
        cap = int(config.max_total_tickets())
        if cap <= 0:
            return {"cap": 0, "sold": 0, "remaining": 0, "sold_out": False, "unlimited": True}
        sold = tickets_sold()
        return {
            "cap": cap,
            "sold": sold,
            "remaining": max(0, cap - sold),
            "sold_out": sold >= cap,
            "unlimited": False,
        }
    except Exception as e:
        print(f"utils.ticket_availability unavailable, treating as uncapped: {e}")
        return {"cap": cap, "sold": 0, "remaining": 0, "sold_out": False, "unlimited": True}


def _lock_ticket_capacity(session) -> None:
    """Serialize the capacity check + insert in register_guest().

    Two guests submitting at the same instant can both read "3 left" and
    both insert 3, overselling the venue — under READ COMMITTED neither
    transaction can see the other's uncommitted row. There is no row to lock
    instead (the check is an aggregate over the whole table, and
    SELECT ... FOR UPDATE is rejected with aggregate functions), so take a
    transaction-scoped Postgres advisory lock: it is released automatically
    on COMMIT or ROLLBACK, and only ever contends with other registrations.

    A no-op on SQLite, which serializes writers at the file level anyway.
    Best-effort by design — never raises, because failing to take the lock
    only widens the race window, and refusing a paid guest's registration
    over it would be the worse outcome.
    """
    try:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _TICKET_CAP_LOCK_KEY})
    except Exception as e:  # pragma: no cover - defensive
        print(f"utils._lock_ticket_capacity: advisory lock unavailable, continuing: {e}")


SOLD_OUT_MESSAGE = (
    "We're sold out — every ticket for the party has been claimed. "
    "Nothing was charged by this form, so if you've already sent a Zelle payment, "
    "message the organiser and they'll refund you or sort out a spot."
)


def _not_enough_tickets_message(requested: int, remaining: int) -> str:
    """Message for a registration asking for more tickets than are left."""
    plural = "s" if remaining != 1 else ""
    return (
        f"Only {remaining} ticket{plural} left — you asked for {requested}. "
        f"Lower your ticket count to {remaining} or fewer to finish registering, "
        "and message the organiser about any payment you've already sent."
    )


# ── Page Visit Tracking ─────────────────────────────────────────────────────────

_VISIT_BUFFER_FLUSH_THRESHOLD = 25   # flush once this many rows are buffered
_VISIT_BUFFER_FLUSH_INTERVAL_SECONDS = 30  # ...or this long since the last flush

# URL query param that lets a returning browser recover its visitor_token
# instead of streamlit_app.main() minting a fresh one on every reload. This
# is the primary recovery path — it rides the same st.query_params
# mechanism _sync_page_query_param() already uses for ?page=, which is
# proven to survive Streamlit Community Cloud's reverse proxy in
# production. VISITOR_COOKIE_NAME below is a secondary, best-effort attempt
# only — confirmed NOT to survive a plain refresh once actually deployed
# there, despite working in local testing.
VISITOR_QUERY_PARAM = "v"

# Cookie that lets a returning browser recover its visitor_token instead of
# streamlit_app.main() minting a fresh one — see visitor_cookie_js().
VISITOR_COOKIE_NAME = "pc_visitor_token"
VISITOR_COOKIE_MAX_AGE_SECONDS = 400 * 24 * 60 * 60  # ~13 months, the cap browsers enforce on JS-set cookies

# Named crawlers, link-unfurlers, and scripted HTTP clients — deliberately
# NOT a generic "bot" or "headless" match, both of which would also catch
# Playwright's own Chromium (UA contains "HeadlessChrome") and silently
# zero out every e2e test's recorded traffic.
_BOT_USER_AGENT_RE = re.compile(
    r"googlebot|bingbot|baiduspider|yandexbot|duckduckbot|applebot|"
    r"facebookexternalhit|facebot|linkedinbot|twitterbot|telegrambot|"
    r"whatsapp|slackbot|discordbot|redditbot|pinterest|skypeuripreview|"
    r"ahrefsbot|semrushbot|mj12bot|dotbot|petalbot|bytespider|gptbot|"
    r"claudebot|anthropic-ai|ccbot|ia_archiver|archive\.org_bot|"
    r"curl/|wget/|python-requests|go-http-client|postmanruntime|"
    r"node-fetch|axios/|scrapy|phantomjs",
    re.IGNORECASE,
)


def is_bot_user_agent(user_agent: str) -> bool:
    """True when `user_agent` identifies a crawler, link-unfurler, or
    scripted HTTP client rather than a person's browser — see
    _BOT_USER_AGENT_RE for why this is a narrow, named-bot allowlist
    rather than a broad "bot"/"headless" substring match.
    """
    return bool(user_agent) and bool(_BOT_USER_AGENT_RE.search(user_agent))


def visitor_cookie_js(token: str) -> str:
    """Return an HTML/JS snippet that persists `token` as a long-lived
    first-party cookie, reaching out of the component iframe into the
    parent document the same way phone_input_mask_js() does.

    Streamlit mints a brand-new session — and streamlit_app.main() would
    otherwise mint a brand-new random visitor_token right along with it —
    on every full page reload or dropped/reconnected WebSocket (a common
    mobile occurrence: screen lock, backgrounding, a network blip). That
    was counting the same person as an extra "unique visitor" every time.
    Setting this cookie lets the next session recover the same token via
    st.context.cookies instead of minting a new one.
    """
    import json as _json

    js_name = _json.dumps(VISITOR_COOKIE_NAME).replace("</", "<\\/")
    js_token = _json.dumps(token).replace("</", "<\\/")

    return f"""
    <script>
        (function () {{
            try {{
                var doc = window.parent.document;
                doc.cookie = {js_name} + "=" + {js_token} +
                    "; max-age={VISITOR_COOKIE_MAX_AGE_SECONDS}; path=/; SameSite=Lax";
            }} catch (e) {{}}
        }})();
    </script>
    """


@st.cache_resource(show_spinner=False)
def _visit_buffer_state() -> dict:
    """Process-global buffer for record_visit(), shared across every session
    in this worker process (that's the whole point of @st.cache_resource —
    unlike st.session_state, it is NOT per-browser-session).

    {"rows": [dict, ...], "lock": threading.Lock(), "last_flush": float
    (time.monotonic() of the last successful/attempted flush)}.
    """
    return {"rows": [], "lock": threading.Lock(), "last_flush": time.monotonic()}


def record_visit(visitor_token: str, page: str = "Home") -> None:
    """Record a page visit for traffic stats. Safe to call frequently.

    Does NOT hit the database on the render path. Under a burst (e.g. ~200
    people opening the registration link at once), that would be one
    blocking INSERT per page navigation per visitor. Instead this appends
    to a small in-memory buffer (process-global, shared across sessions —
    see _visit_buffer_state()) and returns immediately. The buffer is
    flushed as a single bulk insert, performed on a background daemon
    thread so a flush never blocks a render either, once it grows past
    _VISIT_BUFFER_FLUSH_THRESHOLD rows or _VISIT_BUFFER_FLUSH_INTERVAL_SECONDS
    have elapsed since the last flush — whichever comes first.

    Call flush_page_visits() to force a synchronous flush; the stats readers
    below do this first so callers (including tests) always see up-to-date
    numbers, never a stale pre-flush count.
    """
    state = _visit_buffer_state()
    should_flush = False
    with state["lock"]:
        state["rows"].append(
            {"visitor_token": visitor_token, "page": page, "visited_at": _utc_now()}
        )
        elapsed = time.monotonic() - state["last_flush"]
        if (
            len(state["rows"]) >= _VISIT_BUFFER_FLUSH_THRESHOLD
            or elapsed >= _VISIT_BUFFER_FLUSH_INTERVAL_SECONDS
        ):
            should_flush = True

    if should_flush:
        threading.Thread(target=_flush_page_visits_worker, daemon=True).start()


def _flush_page_visits_worker() -> None:
    """Background-thread entry point for a threshold-triggered flush.

    Wraps flush_page_visits() so an unexpected error inside the thread is
    logged instead of vanishing silently (an uncaught exception in a daemon
    thread doesn't crash the process, but Python does print an unhandled
    traceback to stderr by default — this keeps the failure message
    consistent with the rest of the app's "log, never raise into the UI"
    convention instead).
    """
    try:
        flush_page_visits()
    except Exception as e:
        print(f"record_visit: background flush failed: {e}")


def flush_page_visits() -> int:
    """Force a synchronous flush of buffered page visits to the database.

    Safe to call frequently and from any thread (the render path, a
    background flush thread, or a stats reader). Swaps the buffer out under
    lock first — so record_visit() calls that land *during* the flush go
    into a fresh buffer instead of being lost — then performs the insert as
    a single bulk statement outside the lock, so a slow DB never blocks
    concurrent record_visit() callers. Returns the number of rows flushed
    (0 if the buffer was empty, which is the common case and costs no DB
    round trip at all).

    Never raises into the caller: if the bulk insert fails, the rows are
    logged and put back at the front of the buffer (not silently dropped)
    so the next flush attempt retries them.
    """
    state = _visit_buffer_state()
    with state["lock"]:
        rows = state["rows"]
        state["rows"] = []
        state["last_flush"] = time.monotonic()

    if not rows:
        return 0

    session = get_db()
    try:
        session.execute(insert(PageVisit), rows)
        session.commit()
        return len(rows)
    except Exception as e:
        session.rollback()
        print(f"flush_page_visits: bulk insert of {len(rows)} row(s) failed, re-buffering: {e}")
        with state["lock"]:
            state["rows"] = rows + state["rows"]
        return 0
    finally:
        session.close()


def get_visit_stats() -> dict:
    """Return traffic stats: total visits and unique visitors.

    Flushes the page-visit buffer first (see record_visit()) so this always
    reflects every visit recorded so far, not a stale pre-flush count.
    Computed via a single SELECT with two aggregate columns.
    """
    flush_page_visits()
    session = get_db()
    try:
        row = session.query(
            func.count(PageVisit.id),
            func.count(func.distinct(PageVisit.visitor_token)),
        ).one()
        return {
            "total_visits": int(row[0]),
            "unique_visitors": int(row[1] or 0),
        }
    finally:
        session.close()


def get_site_stats() -> dict:
    """Return public site-usage stats for the home page (v2).

    Flushes the page-visit buffer first (see record_visit()) for the same
    reason as get_visit_stats(). Computed via a SINGLE SELECT built from six
    scalar subqueries (the same pattern as vw_site_activity_summary below)
    rather than six separate round trips — one statement dispatched to the
    database, regardless of how many subqueries it contains internally.
    """
    flush_page_visits()
    session = get_db()
    try:
        today = _utc_now().date()

        total_visits_sq = select(func.count(PageVisit.id)).scalar_subquery()
        unique_visitors_sq = select(
            func.count(func.distinct(PageVisit.visitor_token))
        ).scalar_subquery()
        today_visits_sq = (
            select(func.count(PageVisit.id))
            .where(func.date(PageVisit.visited_at) == today)
            .scalar_subquery()
        )
        today_unique_sq = (
            select(func.count(func.distinct(PageVisit.visitor_token)))
            .where(func.date(PageVisit.visited_at) == today)
            .scalar_subquery()
        )
        total_regs_sq = select(func.coalesce(func.sum(Guest.ticket_count), 0)).scalar_subquery()
        today_regs_sq = (
            select(func.coalesce(func.sum(Guest.ticket_count), 0))
            .where(func.date(Guest.created_at) == today)
            .scalar_subquery()
        )

        row = session.execute(
            select(
                total_visits_sq.label("total_visits"),
                unique_visitors_sq.label("unique_visitors"),
                today_visits_sq.label("today_visits"),
                today_unique_sq.label("today_unique"),
                total_regs_sq.label("total_regs"),
                today_regs_sq.label("today_regs"),
            )
        ).one()

        return {
            "total_visits": int(row.total_visits or 0),
            "unique_visitors": int(row.unique_visitors or 0),
            "today_visits": int(row.today_visits or 0),
            "today_unique": int(row.today_unique or 0),
            "total_regs": int(row.total_regs or 0),
            "today_regs": int(row.today_regs or 0),
        }
    finally:
        session.close()


def record_submission(
    name: str,
    email: str,
    phone: str,
    ticket_count: int,
    plus_one_name: str,
    zelle_ref: str,
    status: str = "attempted",
    errors: str = "",
    guest_id: int = None,
    veg_count: int = 0,
    non_veg_count: int = 0,
) -> None:
    """Persist a registration submission attempt to Supabase/Postgres.

    This creates an audit trail for every form submit, successful or not.
    Safe to call frequently — failures are caught and logged, not raised.
    """
    session = get_db()
    try:
        log = SubmissionLog(
            name=name[:100],
            email=email[:120].lower().strip(),
            phone=phone[:30],
            ticket_count=int(ticket_count) if ticket_count else 1,
            plus_one_name=plus_one_name[:GUEST_NAMES_MAX_CHARS],
            zelle_ref=zelle_ref[:100].upper(),
            status=status,
            errors=errors[:500],
            guest_id=guest_id,
            veg_count=veg_count,
            non_veg_count=non_veg_count,
        )
        session.add(log)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"SubmissionLog insert failed: {e}")
    finally:
        session.close()


def _reporting_view_sql() -> dict:
    """The SELECT body of every reporting view, keyed by view name.

    Split out from _create_postgres_views() so the view names live in one
    place: REPORTING_VIEWS documents the same keys for the admin UI and the
    backup manifest, and a test can assert the two never drift apart.
    """
    event_date = config.EVENT_DATE.strftime("%Y-%m-%d")
    return {
        "vw_registrations_summary": f"""
            SELECT
                COUNT(*) AS total_guests,
                COALESCE(SUM(ticket_count), 0) AS total_tickets,
                COALESCE(SUM(CASE WHEN checked_in THEN 1 ELSE 0 END), 0) AS checked_in,
                COALESCE(SUM(CASE WHEN band_given THEN 1 ELSE 0 END), 0) AS bands_given,
                COALESCE(SUM(CASE WHEN checked_in THEN ticket_count ELSE 0 END), 0) AS admitted_tickets,
                COUNT(CASE WHEN NOT checked_in THEN 1 END) AS pending
            FROM guests
        """,
        "vw_registrations_by_day": """
            SELECT
                created_at::date AS registration_date,
                COUNT(*) AS guest_count,
                COALESCE(SUM(ticket_count), 0) AS ticket_count
            FROM guests
            GROUP BY created_at::date
            ORDER BY registration_date DESC
        """,
        "vw_checkins_by_hour": f"""
            SELECT
                EXTRACT(HOUR FROM checkin_time)::int AS hour,
                COUNT(*) AS checkin_count
            FROM guests
            WHERE checked_in = true AND checkin_time::date = '{event_date}'::date
            GROUP BY EXTRACT(HOUR FROM checkin_time)::int
            ORDER BY hour
        """,
        "vw_site_activity_summary": """
            SELECT
                (SELECT COUNT(*) FROM page_visits) AS total_visits,
                (SELECT COUNT(DISTINCT visitor_token) FROM page_visits) AS unique_visitors,
                (SELECT COUNT(*) FROM page_visits WHERE visited_at::date = CURRENT_DATE) AS today_visits,
                (SELECT COUNT(DISTINCT visitor_token) FROM page_visits WHERE visited_at::date = CURRENT_DATE) AS today_unique
        """,
        "vw_submissions_summary": """
            SELECT
                status,
                COUNT(*) AS count,
                MAX(created_at) AS last_seen
            FROM submission_logs
            GROUP BY status
            ORDER BY count DESC
        """,
        "vw_submissions_recent": """
            SELECT
                id, name, email, status, errors, guest_id, created_at
            FROM submission_logs
            ORDER BY created_at DESC
            LIMIT 100
        """,
    }


# What each reporting view answers, in plain English — shown in the admin
# Danger Zone and written into every backup's README so an organiser knows
# what to query without opening this file. Keys must match _reporting_view_sql().
REPORTING_VIEWS = (
    ("vw_registrations_summary", "One row of totals: guests, tickets, checked in, bands given, still pending."),
    ("vw_registrations_by_day", "Registrations and tickets per calendar day, newest first."),
    ("vw_checkins_by_hour", "Check-in counts by hour of the event day."),
    ("vw_site_activity_summary", "Page visits and unique visitors, all-time and today."),
    ("vw_submissions_summary", "Registration attempts grouped by outcome (registered, duplicate_email, …)."),
    ("vw_submissions_recent", "The 100 most recent submission attempts with their error text."),
)


def _create_postgres_views(engine) -> None:
    """Create/replace helpful reporting views on PostgreSQL (Supabase).

    These views are skipped on SQLite because they use PostgreSQL-specific
    date/time syntax. They give organisers ready-made dashboards in Supabase.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        for view_name, sql in _reporting_view_sql().items():
            try:
                conn.execute(text(f"CREATE OR REPLACE VIEW {view_name} AS {sql}"))
            except Exception as e:
                print(f"View {view_name} creation failed: {e}")
        conn.commit()


# ── QR Code Generation ────────────────────────────────────────────────────────

def generate_qr_image(qr_data: str) -> bytes:
    """Generate a clean QR code PNG image with a generous white border.

    The image contains only the QR code (no text below) so email clients cannot
    clip or scale the code when displaying it inline. A large box size and high
    error correction make it easy to scan from phone screens and printouts.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=20,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    if img.mode != "RGB":
        img = img.convert("RGB")

    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return img_io.getvalue()


def generate_qr_code() -> str:
    """Generate a unique QR code string for a new guest."""
    rand = base64.urlsafe_b64encode(os.urandom(8)).decode()[:10]
    return f"{config.qr_prefix()}-{datetime.now().strftime('%Y%m%d')}-{rand}"


# ── Email ─────────────────────────────────────────────────────────────────────
# send_qr_email() (sync) and send_qr_email_async() (fire-and-forget, off the
# request thread) both build their message via _build_qr_email_message() and
# send it via _smtp_send() so the two paths cannot drift apart.

def _read_mail_secrets() -> dict:
    """Read every MAIL_* secret needed to send an email, in one place.

    Must only ever be called from the main/calling thread — st.secrets access
    is not something a background thread should do. send_qr_email_async()
    calls this before spawning its worker thread and hands the plain dict
    result to the worker, which never touches _get_secret()/st.* itself.
    """
    mail_username = _get_secret("MAIL_USERNAME", "")
    mail_password = _get_secret("MAIL_PASSWORD", "")
    mail_server = _get_secret("MAIL_SERVER", "smtp.gmail.com")
    mail_sender = _get_secret("MAIL_DEFAULT_SENDER", "party@example.com")
    # Tolerate a blank/garbage MAIL_PORT: int("") raises ValueError, and this
    # runs inside the registration request, so it would surface as a raw
    # traceback to a guest who just paid.
    try:
        mail_port = int(_get_secret("MAIL_PORT", "587") or 587)
    except (TypeError, ValueError):
        mail_port = 587
    return {
        "mail_username": mail_username,
        "mail_password": mail_password,
        "mail_server": mail_server,
        "mail_sender": mail_sender,
        "mail_port": mail_port,
    }


def _build_qr_email_message(
    mail_sender: str,
    guest_id,
    guest_name: str,
    guest_email: str,
    ticket_count,
    plus_one_name: str,
    qr_code: str,
    veg_count=0,
    non_veg_count=0,
) -> MIMEMultipart:
    """Build the multipart QR-code email (HTML + plain-text + inline image).

    Pure function: no I/O, no secrets, no Streamlit — safe to call from any
    thread. Shared by send_qr_email (sync) and send_qr_email_async
    (background thread) so the two message bodies cannot drift apart.
    """
    qr_image = generate_qr_image(qr_code)

    # Escape every interpolated value before it goes into the HTML body.
    safe_name = html.escape(guest_name or "")
    safe_qr_code = html.escape(qr_code or "")

    # plus_one_name holds every additional guest, newline-joined — rendering
    # it as one escaped blob would run all the names together on a single
    # line. Listed individually, with the count, so the booker can check the
    # party we have on file matches the party they're bringing.
    extra_names = guest_names_list(plus_one_name)

    event_year = config.EVENT_DATE.year
    event_title = f"{config.EVENT_NAME} {event_year}"

    msg = MIMEMultipart("related")
    msg["Subject"] = f"🎉 Your {event_title} QR Code!"
    msg["From"] = mail_sender
    msg["To"] = guest_email

    if extra_names:
        items = "".join(f"<li>{html.escape(n)}</li>" for n in extra_names)
        plus_one_line = (
            f"<p>👥 Additional guests ({len(extra_names)}):</p>"
            f"<ul style=\"margin-top: 0;\">{items}</ul>"
        )
        plus_one_text = (
            f"👥 Additional guests ({len(extra_names)}):\n"
            + "\n".join(f"  - {n}" for n in extra_names)
        )
    else:
        plus_one_line = ""
        plus_one_text = ""

    my_qr_url = f"{config.APP_URL}/?page=My%20QR&guest_id={guest_id}"
    safe_my_qr_url = html.escape(my_qr_url)

    meals_line = f"🍽️ Meals: {int(veg_count or 0)} veg, {int(non_veg_count or 0)} non-veg"

    # HTML body with inline QR image and a plain-text fallback
    html_body = f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #333;">
    <h2>Hi {safe_name}!</h2>
    <p>You're registered for <strong>{html.escape(event_title)} — {html.escape(config.EVENT_TAGLINE)}!</strong></p>
    <p>🎫 Tickets: {ticket_count}</p>
    <p>{html.escape(meals_line)}</p>
    {plus_one_line}
    <p>📅 Date: {html.escape(config.EVENT_DATE_TEXT)}<br>
       🕕 Time: {html.escape(config.EVENT_TIME_TEXT)}<br>
       📍 Venue: {html.escape(config.VENUE_NAME)}, {html.escape(config.VENUE_ADDRESS)}</p>
    <p>Your QR code is below. Please show it at the entrance for check-in.</p>
    <p style="text-align: center;"><img src="cid:party_qr" alt="Your QR Code" width="400" style="width: 100%; max-width: 420px; height: auto; border: 16px solid white; display: block; margin: 0 auto;"></p>
    <p style="font-size: 0.9em; color: #666;">
        If the QR code doesn't scan, show this code to the staff:<br>
        <code style="font-size: 1.1em; background: #f4f4f4; padding: 4px 8px; border-radius: 4px;">{safe_qr_code}</code>
    </p>
    <p><a href="{safe_my_qr_url}">Open your QR code on the website</a></p>
    <p>See you there!</p>
</body>
</html>
"""

    plain_body = f"""Hi {guest_name}!

You're registered for {event_title} — {config.EVENT_TAGLINE}!

🎫 Tickets: {ticket_count}
{meals_line}
{plus_one_text}
📅 Date: {config.EVENT_DATE_TEXT}
🕕 Time: {config.EVENT_TIME_TEXT}
📍 Venue: {config.VENUE_NAME}, {config.VENUE_ADDRESS}

Your QR code is attached (party_qr.png). Please show it at the entrance for check-in.

If the QR code doesn't scan, show this code to the staff:
{qr_code}

You can also view it here: {my_qr_url}

See you there!
"""

    msg_alternative = MIMEMultipart("alternative")
    msg_alternative.attach(MIMEText(plain_body, "plain"))
    msg_alternative.attach(MIMEText(html_body, "html"))
    msg.attach(msg_alternative)

    img_attachment = MIMEImage(qr_image, _subtype="png")
    img_attachment.add_header("Content-ID", "<party_qr>")
    img_attachment.add_header("Content-Disposition", "inline", filename="party_qr.png")
    msg.attach(img_attachment)

    return msg


def _smtp_send(mail_server: str, mail_port: int, mail_username: str, mail_password: str, msg: MIMEMultipart) -> bool:
    """Connect, authenticate, and send `msg`. Returns True on success.

    The actual blocking network I/O, factored out so both the synchronous
    and background-thread send paths share identical connect/TLS/login logic.
    """
    try:
        if mail_port == 465:
            # Implicit TLS
            with smtplib.SMTP_SSL(mail_server, mail_port, timeout=20) as server:
                server.login(mail_username, mail_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(mail_server, mail_port, timeout=20) as server:
                server.starttls()
                server.login(mail_username, mail_password)
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


def send_qr_email(guest) -> bool:
    """Send QR code via email using SMTP, synchronously. Returns True on success.

    Blocks the calling thread for the full connect+TLS+login+send (often
    1-3s against Gmail). Kept for the "Resend" buttons and the test suite,
    where a synchronous result is actually wanted. For the registration hot
    path, use send_qr_email_async() instead so a slow SMTP server doesn't
    hold a request thread.

    Accepts a Guest ORM instance or anything exposing the same attributes
    (e.g. SimpleNamespace(**guest_dict)).
    """
    secrets = _read_mail_secrets()
    if not secrets["mail_username"] or not secrets["mail_password"]:
        return False

    msg = _build_qr_email_message(
        secrets["mail_sender"],
        guest.id,
        guest.name,
        guest.email,
        guest.ticket_count,
        guest.plus_one_name,
        guest.qr_code,
        guest.veg_count,
        guest.non_veg_count,
    )
    return _smtp_send(secrets["mail_server"], secrets["mail_port"], secrets["mail_username"], secrets["mail_password"], msg)


def send_qr_email_async(guest: dict) -> None:
    """Send the QR-code email in a background thread; returns immediately.

    Registration must not block a server thread on SMTP, so this snapshots
    every secret it needs (via _read_mail_secrets(), which reads st.secrets)
    in the CALLING thread, then hands off to a daemon thread that builds the
    message and sends it. The worker thread never reads st.secrets or calls
    any st.* function — only the plain values captured here.

    If nothing is configured (blank MAIL_USERNAME/MAIL_PASSWORD), returns
    immediately without spawning a thread — there's nothing it could send.

    On failure, the worker records a SubmissionLog row with
    status="email_failed" (so organisers can see it in the admin dashboard)
    and prints the error. There is no return value/exception surfaced to the
    caller by design — the whole point is to not make registration wait.
    """
    secrets = _read_mail_secrets()
    if not secrets["mail_username"] or not secrets["mail_password"]:
        return

    guest_id = guest.get("id")
    guest_name = guest.get("name", "")
    guest_email = guest.get("email", "")
    ticket_count = guest.get("ticket_count", 1)
    plus_one_name = guest.get("plus_one_name", "")
    qr_code = guest.get("qr_code", "")
    phone = guest.get("phone", "")
    zelle_ref = guest.get("zelle_ref", "")
    veg_count = guest.get("veg_count", 0)
    non_veg_count = guest.get("non_veg_count", 0)

    def _worker():
        error_text = ""
        try:
            msg = _build_qr_email_message(
                secrets["mail_sender"], guest_id, guest_name, guest_email,
                ticket_count, plus_one_name, qr_code,
                veg_count, non_veg_count,
            )
            sent = _smtp_send(
                secrets["mail_server"], secrets["mail_port"],
                secrets["mail_username"], secrets["mail_password"], msg,
            )
            if not sent:
                error_text = "Async QR email send failed (see server log)"
        except Exception as e:
            print(f"send_qr_email_async worker failed: {e}")
            error_text = str(e)

        if error_text:
            # Outside the try/except above on purpose, but still guarded of
            # its own accord: this call is what makes a send failure visible
            # in the admin dashboard, so if IT throws too (e.g. a transient
            # DB blip), that must not vanish as an uncaught exception in a
            # daemon thread with nothing to show for it anywhere.
            try:
                record_submission(
                    name=guest_name,
                    email=guest_email,
                    phone=phone,
                    ticket_count=ticket_count,
                    plus_one_name=plus_one_name,
                    zelle_ref=zelle_ref,
                    status="email_failed",
                    errors=error_text,
                    guest_id=guest_id,
                )
            except Exception as e:
                print(f"send_qr_email_async: failed to record email_failed log: {e}")

    threading.Thread(target=_worker, daemon=True).start()


# ── Welcome Announcement ──────────────────────────────────────────────────────

def generate_welcome_announcement(name: str, ticket_count: int) -> str:
    """Generate welcome announcement text for speech synthesis."""
    if ticket_count == 1:
        return f"Welcome {name}! You have 1 ticket. Enjoy the party!"
    return f"Welcome {name}! You have {ticket_count} tickets. Enjoy the party!"


# ── Home Page Content: Photos & Sponsors ──────────────────────────────────────
# The organiser fills config.PHOTOS / config.SPONSORS in; these functions turn
# whatever is there into a list the theme builders can render without checking
# anything themselves. Both are defensive by design: this is hand-edited
# content, so a typo'd path or a half-filled entry must degrade to "that item
# isn't shown" rather than a broken image or a crashed Home page.

# Image formats a browser will display inline, mapped to their MIME type.
_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

# Refuse to inline anything larger than this. Every local image is base64'd
# into the page HTML, which Streamlit re-sends on every rerun — a couple of
# unresized phone photos would make the whole app feel broken.
MAX_INLINE_IMAGE_BYTES = 3 * 1024 * 1024

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


@lru_cache(maxsize=64)
def _read_asset_data_uri(full_path: str, mtime_ns: int, mime: str) -> str:
    """Base64-encode the file at `full_path` into a `data:` URI.

    Cached on (path, mtime) rather than path alone: a host that replaces
    the file on disk without restarting the process — e.g. a Streamlit
    Cloud redeploy that reruns the script in the same long-lived worker —
    would otherwise keep serving the old image's bytes forever, since the
    cache key never changed. `mtime_ns` makes a replaced file a cache miss.
    """
    with open(full_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _asset_data_uri(path: str) -> str:
    """Read a local image into a `data:` URI, or "" if it can't be used.

    Streamlit serves no arbitrary static files, so a local photo can only
    reach the browser inlined in the HTML. Relative paths resolve against
    the project directory, NOT the cwd: the app is deliberately run from a
    different working directory in development and testing (see AGENTS.md),
    so a cwd-relative lookup would silently find nothing there.
    """
    ext = os.path.splitext(path)[1].lower()
    mime = _IMAGE_MIME_TYPES.get(ext)
    if not mime:
        print(f"skipping image with unsupported extension: {path}")
        return ""

    full_path = path if os.path.isabs(path) else os.path.join(_PROJECT_DIR, path)
    try:
        stat = os.stat(full_path)
        if stat.st_size > MAX_INLINE_IMAGE_BYTES:
            print(
                f"skipping oversized image (>{MAX_INLINE_IMAGE_BYTES // (1024 * 1024)}MB), "
                f"please resize it first: {path}"
            )
            return ""
        return _read_asset_data_uri(full_path, stat.st_mtime_ns, mime)
    except OSError as e:
        print(f"skipping unreadable image {path}: {e}")
        return ""


# Any "scheme:" prefix, e.g. https:, javascript:, DATA:, vbscript:. Matched
# case-insensitively against the whole string so the allowlist below is the
# only way a URL scheme gets through.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def resolve_image_src(src: str) -> str:
    """Turn a configured image reference into something an <img> can load.

    Accepts a remote https URL (used as-is), an already-built image data
    URI, or a repo-relative/absolute local path (inlined via
    _asset_data_uri). Everything else returns "".

    Allowlist, not a blocklist: any other scheme is refused outright rather
    than enumerated. That covers plain `http:` (blocked as mixed content on
    the HTTPS deployment anyway) and, more importantly, `javascript:` and
    friends in whatever casing — this value goes straight into an `src`
    attribute, and the lists it comes from are hand-edited.
    """
    src = (src or "").strip()
    if not src:
        return ""
    lowered = src.lower()
    if lowered.startswith("https://") or lowered.startswith("data:image/"):
        return src
    if _URL_SCHEME_RE.match(src) or src.startswith("//"):
        print(f"skipping image with unsupported source: {src[:60]}")
        return ""
    return _asset_data_uri(src)


def event_flyer_src() -> str:
    """The event flyer image, ready for an <img src>, or "" if there isn't one.

    Optional by design: config.EVENT_FLYER names a path that may not exist
    yet, and every caller renders nothing for "". Dropping the artwork in at
    that path is the whole install step.
    """
    return resolve_image_src(getattr(config, "EVENT_FLYER", "") or "")


def gallery_photos() -> list:
    """config.PHOTOS, normalized and filtered down to photos that can render.

    Returns a list of {"src", "caption"} dicts. An entry whose image can't
    be resolved is dropped, so a mistyped filename costs that one photo
    rather than showing a broken tile to every guest.
    """
    photos = []
    for item in getattr(config, "PHOTOS", None) or []:
        if not isinstance(item, dict):
            continue
        src = resolve_image_src(item.get("src", ""))
        if not src:
            continue
        photos.append({"src": src, "caption": str(item.get("caption") or "").strip()})
    return photos


def _sponsor_tier_rank(tier: str) -> int:
    """Sort position for a tier name, per config.SPONSOR_TIERS.

    An unrecognised tier (a new one invented mid-season, or a typo) sorts to
    the end rather than being dropped — a sponsor who paid must never vanish
    from the page because their tier label doesn't match a list in the code.
    """
    tiers = [str(t).strip().lower() for t in (getattr(config, "SPONSOR_TIERS", None) or ())]
    try:
        return tiers.index((tier or "").strip().lower())
    except ValueError:
        return len(tiers)


def sponsor_list() -> list:
    """config.SPONSORS, normalized and ordered best tier first.

    Returns a list of {"name", "tier", "logo", "url", "blurb", "featured"}
    dicts. Only `name` is required — a sponsor with no logo yet still gets a
    card (with their name set in type), because the lineup is usually
    confirmed well before the artwork arrives.

    Ordering happens here rather than in the theme so that "which tier
    outranks which" stays a config question, not a rendering one. The sort is
    stable, so sponsors within a tier keep the order they were listed in —
    that order is usually deliberate, and shuffling co-equal sponsors between
    page loads is the kind of thing sponsors notice.

    `featured` marks the top tier, which the sponsor wall renders larger.
    """
    sponsors = []
    for item in getattr(config, "SPONSORS", None) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        url = str(item.get("url") or "").strip()
        sponsors.append({
            "name": name,
            "tier": str(item.get("tier") or "").strip(),
            "logo": resolve_image_src(item.get("logo", "")),
            # Same allowlist rule as images: only https links are ever
            # emitted into an href, so hand-edited config can't introduce a
            # javascript: link in any casing.
            "url": url if url.lower().startswith("https://") else "",
            "blurb": str(item.get("blurb") or "").strip(),
        })

    sponsors.sort(key=lambda s: _sponsor_tier_rank(s["tier"]))

    # "Featured" is whichever tier actually came out on top, not a hardcoded
    # name — so a lineup with no Top Sponsor still leads with its best tier
    # rather than rendering every card the same size.
    if sponsors:
        best = _sponsor_tier_rank(sponsors[0]["tier"])
        for sponsor in sponsors:
            sponsor["featured"] = _sponsor_tier_rank(sponsor["tier"]) == best
    return sponsors


# ── Formatting Helpers ────────────────────────────────────────────────────────

def format_dt(dt, fmt: str = "%I:%M %p", fallback: str = "—") -> str:
    """Format a datetime, tolerating None.

    checkin_time can be NULL while checked_in is True (e.g. rows edited
    outside the app), so callers must not call .strftime() on it directly.
    """
    if dt is None:
        return fallback
    try:
        return dt.strftime(fmt)
    except Exception:
        return fallback


# ── CSV Export ──────────────────────────────────────────────────────────────────

def _sanitize_csv_field(value: str) -> str:
    """Prevent CSV injection by escaping formula characters."""
    if not value:
        return ""
    # Prefix with apostrophe if value starts with formula characters
    if value.strip() and value.strip()[0] in ('=', '+', '-', '@', '|', '%'):
        return "'" + value
    return value


def generate_csv() -> str:
    """Generate CSV content of all guests. Returns CSV string."""
    session = get_db()
    try:
        guests = session.query(Guest).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Name", "Email", "Phone", "Tickets", "Additional Guests",
            "Additional Guest Names", "Zelle Ref", "Veg", "Non-Veg",
            "Checked In", "Band Given", "Check-in Time", "QR Code"
        ])
        for g in guests:
            writer.writerow([
                _sanitize_csv_field(g.name),
                _sanitize_csv_field(g.email),
                _sanitize_csv_field(g.phone),
                g.ticket_count,
                guest_name_count(g.plus_one_name),
                # Comma-joined, not raw: the names are stored newline-joined,
                # and a cell with embedded newlines makes one guest's row
                # span several lines in a spreadsheet. The archival export
                # (export_backup) still writes the column verbatim.
                _sanitize_csv_field(", ".join(guest_names_list(g.plus_one_name))),
                _sanitize_csv_field(g.zelle_ref),
                g.veg_count,
                g.non_veg_count,
                "Yes" if g.checked_in else "No",
                "Yes" if g.band_given else "No",
                format_dt(g.checkin_time, "%Y-%m-%d %H:%M:%S", ""),
                g.qr_code,
            ])
        return output.getvalue()
    finally:
        session.close()


# ── Admin Password ─────────────────────────────────────────────────────────────

def admin_password_is_configured() -> bool:
    """Return True if the ADMIN_PASSWORD secret has been set."""
    return bool(_get_secret("ADMIN_PASSWORD", ""))


def verify_admin_password(password: str) -> bool:
    """Verify admin password against secret using constant-time comparison.

    Fails CLOSED: if ADMIN_PASSWORD is not configured, no password is
    accepted (previously this returned True for any password, leaving the
    admin dashboard — guest PII and delete — wide open on any deploy that
    forgot to set the secret). Use admin_password_is_configured() to show a
    clear "not configured" message instead of a generic wrong-password error.
    """
    expected = _get_secret("ADMIN_PASSWORD", "")
    if not expected:
        return False
    # Encode to bytes first: compare_digest raises TypeError when given
    # non-ASCII str input.
    return compare_digest(str(password).encode("utf-8"), expected.encode("utf-8"))


# ── Audio Announcement (JavaScript) ─────────────────────────────────────────────

def audio_announcement_js(text: str) -> str:
    """Return HTML/JS snippet that speaks the given text using browser TTS.

    Uses proper HTML escaping to prevent XSS. Escapes </script> sequences
    so the embedded JS string cannot close the outer HTML script tag.
    """
    # Escape HTML entities first
    safe_text = html.escape(text)
    # Build JS string safely via JSON encoding
    import json as _json
    js_text = _json.dumps(safe_text)
    # Prevent </script> from closing the outer HTML script tag
    js_text = js_text.replace("</script>", "<\\/script>")
    js_text = js_text.replace("</SCRIPT>", "<\\/SCRIPT>")
    return f"""
    <script>
        (function() {{
            if ('speechSynthesis' in window) {{
                var u = new SpeechSynthesisUtterance({js_text});
                u.rate = 0.9;
                u.pitch = 1.0;
                window.speechSynthesis.speak(u);
            }}
        }})();
    </script>
    """


# ── Phone Input Mask (JavaScript) ───────────────────────────────────────────────

US_PHONE_PREFIX = "+1-"


def phone_input_mask_js(label: str, prefix: str = US_PHONE_PREFIX) -> str:
    """Return an HTML/JS snippet that live-formats a US phone st.text_input.

    Streamlit has no client-side input mask, so this reaches out of the
    component iframe into the parent document and formats the field whose
    aria-label is `label` (Streamlit renders a text_input's label as its
    aria-label) on every keystroke: digits are grouped as +1-XXX-XXX-XXXX,
    the +1 prefix is restored if deleted, and anything past 10 digits is
    dropped. The caret is kept next to the digit the guest just typed rather
    than being thrown to the end.

    A value the guest deliberately opened with a non-+1 country code (say
    "+44 20 7946 0958") is left exactly as typed — silently reshaping it
    into a plausible-looking US number would be far worse than letting
    validate_registration reject it as non-US.

    This is cosmetic only. sanitize_phone() on the server stays the
    authority, so a browser where this never runs validates identically —
    which is also why every DOM step is defensive: a Streamlit upgrade that
    renames something must degrade to "no live formatting", never to a
    broken page.
    """
    import json as _json

    js_label = _json.dumps(label).replace("</", "<\\/")
    js_prefix = _json.dumps(prefix).replace("</", "<\\/")

    return f"""
    <script>
        (function () {{
            var LABEL = {js_label};
            var PREFIX = {js_prefix};

            var doc, win;
            try {{
                win = window.parent;
                doc = win.document;
            }} catch (e) {{ return; }}
            if (!doc) {{ return; }}

            function isTarget(el) {{
                return el && el.tagName === "INPUT"
                    && el.getAttribute("aria-label") === LABEL;
            }}

            function digitsOf(s) {{ return (s || "").replace(/\\D/g, ""); }}

            // The value with a leading +1 country code (however it was typed
            // or pasted) removed.
            function bodyOf(s) {{
                s = s || "";
                var cc = s.match(/^\\+\\s*1[\\s\\-\\.\\(]*/);
                return cc ? s.slice(cc[0].length) : s;
            }}

            function nationalDigits(s) {{
                var d = digitsOf(bodyOf(s));
                if (d.length > 10 && d.charAt(0) === "1") {{ d = d.slice(1); }}
                return d.slice(0, 10);
            }}

            function format(d) {{
                var out = PREFIX;
                if (d.length) {{ out += d.slice(0, 3); }}
                if (d.length > 3) {{ out += "-" + d.slice(3, 6); }}
                if (d.length > 6) {{ out += "-" + d.slice(6, 10); }}
                return out;
            }}

            // React tracks its own copy of the input value, so assigning
            // el.value directly would be silently reverted on the next
            // render. Going through the prototype's native setter is what
            // makes React (and therefore Streamlit's widget state) see it.
            function setValue(el, value) {{
                var desc = Object.getOwnPropertyDescriptor(
                    win.HTMLInputElement.prototype, "value");
                if (desc && desc.set) {{ desc.set.call(el, value); }}
                else {{ el.value = value; }}
            }}

            function onInput(e) {{
                var el = e.target;
                if (!isTarget(el) || el.dataset.usPhoneMaskBusy === "1") {{ return; }}

                var raw = el.value || "";
                // A country code of the guest's own — "+44…", or "+44…"
                // typed after the restored prefix — means hands off, so the
                // server can reject it as non-US (see the docstring).
                if (bodyOf(raw).charAt(0) === "+") {{ return; }}

                var formatted = format(nationalDigits(raw));
                if (formatted === raw) {{ return; }}

                var caret = (el.selectionStart == null) ? raw.length : el.selectionStart;
                var typedBefore = nationalDigits(raw.slice(0, caret)).length;
                var idx = PREFIX.length, seen = 0;
                while (idx < formatted.length && seen < typedBefore) {{
                    if (/\\d/.test(formatted.charAt(idx))) {{ seen++; }}
                    idx++;
                }}

                el.dataset.usPhoneMaskBusy = "1";
                try {{
                    setValue(el, formatted);
                    var Ev = win.Event || Event;
                    el.dispatchEvent(new Ev("input", {{ bubbles: true }}));
                    if (el.setSelectionRange) {{ el.setSelectionRange(idx, idx); }}
                }} catch (err) {{
                }} finally {{
                    el.dataset.usPhoneMaskBusy = "";
                }}
            }}

            // Clicking into the "+1-" prefix and typing there would push the
            // country code into the number, so a collapsed caret is nudged
            // back behind it. A real selection (e.g. select-all before
            // pasting) is left alone.
            function onFocusOrClick(e) {{
                var el = e.target;
                if (!isTarget(el) || !el.setSelectionRange) {{ return; }}
                if (el.selectionStart !== el.selectionEnd) {{ return; }}
                if (el.selectionStart < PREFIX.length
                    && (el.value || "").indexOf(PREFIX) === 0) {{
                    try {{ el.setSelectionRange(PREFIX.length, PREFIX.length); }} catch (err) {{}}
                }}
            }}

            // Streamlit reruns re-create this iframe, so installation has to
            // be idempotent: drop the handlers a previous run left behind
            // (their JS context is gone) before registering these.
            try {{
                if (win.__usPhoneMaskInput) {{
                    doc.removeEventListener("input", win.__usPhoneMaskInput, true);
                    doc.removeEventListener("focusin", win.__usPhoneMaskCaret, true);
                    doc.removeEventListener("click", win.__usPhoneMaskCaret, true);
                }}
            }} catch (e) {{}}

            win.__usPhoneMaskInput = onInput;
            win.__usPhoneMaskCaret = onFocusOrClick;
            doc.addEventListener("input", onInput, true);
            doc.addEventListener("focusin", onFocusOrClick, true);
            doc.addEventListener("click", onFocusOrClick, true);
        }})();
    </script>
    """


# ── Input Validation ───────────────────────────────────────────────────────────

def sanitize_email(email: str) -> str:
    """Sanitize and validate email address."""
    email = (email or "").strip().lower()
    # Reject anything the guests.email column (VARCHAR(120)) cannot hold.
    # Without this, Postgres raises a DataError on insert and the guest sees a
    # generic "database problem" instead of a fixable validation message.
    if len(email) > 120:
        return ""
    # Basic email regex
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return ""
    return email


def sanitize_name(name: str) -> str:
    """Sanitize and validate name: letters and spaces only."""
    name = name.strip()
    # Remove excessive whitespace and control characters
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', name)
    # Allow letters and spaces only
    if not re.match(r"^[A-Za-z\s]+$", name):
        return ""
    # Must contain at least one letter and be reasonable length
    if not re.search(r'[A-Za-z]', name) or len(name) < 2 or len(name) > MAX_NAME_LENGTH:
        return ""
    return name[:MAX_NAME_LENGTH]


def sanitize_phone(phone: str) -> str:
    """Sanitize and validate US phone numbers.

    Accepts only digits and the formatting characters +, -, (, ), ., and space.
    A leading +1 country code is optional. The result is formatted as +1-XXX-XXX-XXXX.
    Returns an empty string if the input is blank/only-prefix or invalid.

    US-only, enforced two ways: an explicit "+" prefix must be the +1 country
    code (otherwise "+44 7946 0958" would strip down to 10 digits and be
    mis-stored as the US number +1-447-946-0958), and the area code must start
    with 2-9 as every real NANP area code does.
    """
    phone = phone.strip()
    if not phone or phone in ("+", "+1", "+1-"):
        return ""

    # Reject anything that isn't a digit or allowed US formatting character
    if re.search(r"[^0-9+\-\(\)\.\s]", phone):
        return ""

    digits = re.sub(r"\D", "", phone)

    # An explicit country code has to be +1 — see the docstring.
    if phone.startswith("+") and not (len(digits) == 11 and digits.startswith("1")):
        return ""

    # 11 digits starting with 1 -> drop the +1 country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] in "01":
        return ""

    return f"+1-{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def phone_digits(value: str) -> str:
    """Return just the digits of a phone number, minus any US country code.

    Used for substring search (admin guest list) so that typing "5551234567"
    or "555-1234" finds a guest stored as "+1-555-123-4567".
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


# MAX_GUEST_NAMES and GUEST_NAMES_MAX_CHARS live at the top of this module:
# the ORM models are sized from them, so they must exist before those class
# bodies are evaluated.


def _split_guest_names(text: str) -> list:
    """Split raw guest-names input into trimmed, non-empty entries.

    Newlines and commas both separate names — guests type the list either
    way (and often both ways in one box), so both are accepted. No
    validation happens here; see parse_guest_names().
    """
    raw = (text or "").strip()
    if not raw:
        return []
    return [p for p in (p.strip() for p in re.split(r"[\n,]+", raw)) if p]


def count_guest_name_entries(text: str) -> int:
    """How many names the guest has typed so far, valid or not.

    Used by the Register page's live "you've entered N so far" progress
    note, which must count what's in the box rather than what would pass
    validation — telling someone who typed three names that they've entered
    zero, because one of them has a typo in it, would be worse than useless.
    """
    return len(_split_guest_names(text))


def parse_guest_names(text: str, max_names: int = MAX_GUEST_NAMES) -> tuple:
    """Split a guest-names blob into individually-validated names.

    Accepts names separated by newlines and/or commas; each entry is run
    through sanitize_name(). Returns (names, reason):

    - (["Alice Smith", "Bob Jones"], "") on success
    - ([], "") for blank/whitespace-only input — "not provided", not a failure
    - ([], "invalid") if ANY entry isn't a usable name (all-or-nothing: a
      half-accepted list would silently drop somebody from the booking)
    - ([], "too_many") if there are more than `max_names` entries

    The reason is what lets validate_registration() tell a guest *which*
    thing went wrong; sanitize_guest_names() below is the string-only
    wrapper for callers that don't care.
    """
    parts = _split_guest_names(text)
    if not parts:
        return [], ""
    if len(parts) > max_names:
        return [], "too_many"

    cleaned = []
    for part in parts:
        name = sanitize_name(part)
        if not name:
            return [], "invalid"
        cleaned.append(name)

    return cleaned, ""


def sanitize_guest_names(text: str, max_names: int = MAX_GUEST_NAMES) -> str:
    """Sanitize a list of guest names (for bulk-ticket plus-ones).

    Thin wrapper over parse_guest_names(): returns the cleaned names
    newline-joined, or "" (signalling failure, consistent with the other
    sanitize_* functions) if any entry is invalid or there are more than
    `max_names` entries. Blank/whitespace-only input returns "" too, but
    that's the normal "not provided" case, not a failure.
    """
    names, _reason = parse_guest_names(text, max_names=max_names)
    return "\n".join(names)


def guest_names_list(value: str) -> list:
    """Split a stored plus_one_name value back into individual names.

    plus_one_name holds up to MAX_GUEST_NAMES newline-joined names, not one
    name — every reader (success screen, door card, admin table, email) needs
    to split it the same way, including tolerating the blank/None column
    default and any stray whitespace from a hand-edited row.
    """
    return [n.strip() for n in (value or "").split("\n") if n.strip()]


def guest_name_count(value: str) -> int:
    """How many additional guests are named in a stored plus_one_name value."""
    return len(guest_names_list(value))


def additional_guests_expected(ticket_count) -> int:
    """How many additional guest names a booking of `ticket_count` needs.

    One ticket is the person filling in the form, so a 4-ticket booking is
    the registrant plus 3 named guests. This is the single definition of
    that rule — validate_registration() enforces it, and the UI reads it to
    tell the guest up front how many names to type.
    """
    try:
        tickets = int(ticket_count)
    except (TypeError, ValueError):
        tickets = 1
    return max(tickets - 1, 0)


def party_size(guest: dict) -> int:
    """Total head count for a booking: the registrant plus their named guests.

    Reads the names rather than trusting ticket_count, because rows that
    predate mandatory guest names (and rows hand-edited in the database) can
    have fewer names than tickets. Never returns less than 1 — somebody
    registered.
    """
    named = guest_name_count(guest.get("plus_one_name"))
    try:
        tickets = int(guest.get("ticket_count") or 1)
    except (TypeError, ValueError):
        tickets = 1
    return max(tickets, named + 1, 1)


def sanitize_zelle_ref(ref: str) -> str:
    """Sanitize and validate Zelle transaction reference.

    Zelle confirmation numbers vary by bank (e.g., 8-12 alphanumeric characters).
    Accepts 8-30 characters of letters, digits, and hyphens to allow variation.
    Examples: ABC-12345678, ZELLE9876543210, 1234567890
    """
    ref = ref.strip().upper()
    ref = re.sub(r'[^A-Z0-9\-]', '', ref)
    if len(ref) < 8 or len(ref) > 30:
        return ""
    return ref


# ── Service Layer ──────────────────────────────────────────────────────────────
# Business logic pulled out of the UI so it is unit-testable and reusable.
# Every function here opens its own session, always closes it in `finally`,
# and returns plain dicts/primitives — never detached ORM objects.

def validate_registration(
    name: str,
    email: str,
    phone: str,
    plus_one_name: str,
    zelle_ref: str,
    agree_terms: bool,
    ticket_count=1,
    veg_count=0,
    non_veg_count=0,
) -> tuple:
    """Validate and sanitize registration form fields.

    Returns (cleaned, errors): two dicts keyed by "name", "email", "phone",
    "ticket_count", "plus_one_name", "zelle_ref", "terms", "food_count".
    `cleaned` holds the sanitized value for every field (empty string/False
    if invalid or not provided) plus "additional_guest_count", the number of
    guests actually named, and "veg_count"/"non_veg_count", the cleaned meal
    counts. `errors` holds a user-facing message only for fields that failed
    validation (fields that passed are simply absent from `errors`).

    Guest names are validated AGAINST the ticket count: a booking of N
    tickets is the registrant plus N-1 other people, so exactly N-1
    additional names are required (see additional_guests_expected). Names
    used to be free-form and optional, which meant a 6-ticket booking could
    arrive with nobody named — the organiser then had no idea who the other
    five people were, and the door had no list to check against. Requiring
    them here is the only point in the flow where the guest is still present
    to answer.

    Meal counts are validated the same way, under "food_count": veg_count +
    non_veg_count must equal ticket_count exactly, so the booking doubles as
    a per-person meal tally for catering and a mismatch (too few or too many
    meals for the tickets bought) is caught here rather than discovered at
    the buffet.

    This replaces the validation that used to be duplicated twice in
    streamlit_app.page_register (once inside the st.form block, once after
    it, with subtly different phone/plus-one handling) — the rules and the
    exact wording below match what page_register used to render via
    _field_error.
    """
    errors = {}

    name_clean = sanitize_name(name or "")
    if not name_clean:
        errors["name"] = "Please enter a valid full name using letters and spaces only."

    email_clean = sanitize_email(email or "")
    if not email_clean:
        errors["email"] = "Please enter a valid email address."

    # Phone is required (US numbers only). Email alone is too fragile as the
    # single way to find someone at the door: people register with one of
    # several addresses, mistype it, or can't get into that inbox on the night.
    # A phone number gives the organiser a second lookup key — see
    # find_guest_by_contact.
    phone_raw = (phone or "").strip()
    phone_touched = bool(phone_raw) and phone_raw not in ("+", "+1", "+1-")
    phone_clean = sanitize_phone(phone_raw) if phone_touched else ""
    if not phone_touched:
        errors["phone"] = "Phone number is required — enter a 10-digit US number."
    elif not phone_clean:
        errors["phone"] = "Please enter a valid 10-digit US phone number (only numbers after +1-)."

    # Ticket count decides how many names are required below, so it is
    # validated first. The Register page's number_input already constrains
    # this, but it is a client-side widget and this function is the server
    # -side authority — a garbage value must produce a fixable message, not
    # a traceback out of int().
    max_tickets = config.MAX_TICKETS_PER_REGISTRATION
    try:
        tickets_clean = int(ticket_count)
    except (TypeError, ValueError):
        tickets_clean = 0
    if tickets_clean < 1 or tickets_clean > max_tickets:
        errors["ticket_count"] = f"Please choose between 1 and {max_tickets} tickets."
        tickets_clean = min(max(tickets_clean, 1), max_tickets)

    # Meal counts double as a per-person catering tally, so they must add up
    # to exactly the number of tickets bought — not more, not fewer. Garbage
    # input coerces to 0, same style as ticket_count above: a fixable
    # message, not a traceback out of int().
    try:
        veg_clean = int(veg_count)
    except (TypeError, ValueError):
        veg_clean = 0
    try:
        non_veg_clean = int(non_veg_count)
    except (TypeError, ValueError):
        non_veg_clean = 0
    if veg_clean < 0 or non_veg_clean < 0:
        errors["food_count"] = "Meal counts can't be negative — enter 0 or more for each."
        veg_clean = max(veg_clean, 0)
        non_veg_clean = max(non_veg_clean, 0)

    food_total = veg_clean + non_veg_clean
    if "food_count" not in errors and food_total != tickets_clean:
        meals_word = "meal" if tickets_clean == 1 else "meals"
        if food_total < tickets_clean:
            missing = tickets_clean - food_total
            errors["food_count"] = (
                f"{tickets_clean} tickets needs {tickets_clean} {meals_word} total, but you "
                f"entered {food_total} ({veg_clean} veg + {non_veg_clean} non-veg). "
                f"Please add {missing} more {'meal' if missing == 1 else 'meals'}."
            )
        else:
            excess = food_total - tickets_clean
            errors["food_count"] = (
                f"{tickets_clean} tickets needs {tickets_clean} {meals_word} total, but you "
                f"entered {food_total} ({veg_clean} veg + {non_veg_clean} non-veg). "
                f"Please remove {excess} {'meal' if excess == 1 else 'meals'}."
            )

    names, names_reason = parse_guest_names(plus_one_name or "")
    expected = additional_guests_expected(tickets_clean)
    plus_one_clean = "\n".join(names)

    if names_reason == "invalid":
        plus_one_clean = ""
        errors["plus_one_name"] = "Guest names must use letters and spaces only, one per line."
    elif names_reason == "too_many":
        plus_one_clean = ""
        errors["plus_one_name"] = f"That's more than {MAX_GUEST_NAMES} names — please list at most {MAX_GUEST_NAMES}."
    elif len(names) != expected:
        # The count is the whole point of the field, so say exactly what was
        # counted and exactly what's needed — "invalid input" would leave the
        # guest guessing which of the two numbers to change.
        got = len(names)
        needed_word = "name" if expected == 1 else "names"
        if got == 0:
            errors["plus_one_name"] = (
                f"{tickets_clean} tickets covers you plus {expected} other "
                f"{'guest' if expected == 1 else 'guests'} — please enter their "
                f"{needed_word}, one per line."
            )
        elif got < expected:
            missing = expected - got
            errors["plus_one_name"] = (
                f"{tickets_clean} tickets needs {expected} additional guest {needed_word}, "
                f"but you listed {got}. Please add the {missing} missing "
                f"{'name' if missing == 1 else 'names'}, or lower the ticket count above."
            )
        else:
            # More names than tickets. Says "raise the ticket count" without
            # promising it's possible — the selector is capped by how many
            # tickets are actually left, so a guest at the cap can only take
            # the other branch (remove names).
            extra = got - expected
            covered = "only booked 1 ticket" if expected == 0 else f"booked {tickets_clean} tickets"
            errors["plus_one_name"] = (
                f"You listed {got} guest {'name' if got == 1 else 'names'} but {covered}. "
                "Everyone coming needs their own ticket — raise the ticket count above, "
                f"or remove {extra} {'name' if extra == 1 else 'names'}."
            )

    zelle_clean = sanitize_zelle_ref(zelle_ref or "")
    if not zelle_clean:
        errors["zelle_ref"] = "Zelle transaction reference is required (8-30 letters, digits, hyphens)."

    if not agree_terms:
        errors["terms"] = "Please check I/We Agree in the Terms & Conditions to continue."

    cleaned = {
        "name": name_clean,
        "email": email_clean,
        "phone": phone_clean,
        "ticket_count": tickets_clean,
        "plus_one_name": plus_one_clean,
        # How many people the booker added beyond themselves. Equal to
        # tickets_clean - 1 whenever `errors` is empty; kept as its own key so
        # the caller reports what was actually counted rather than re-deriving
        # it from a field that may have failed validation.
        "additional_guest_count": len(names) if not errors.get("plus_one_name") else 0,
        "zelle_ref": zelle_clean,
        "terms": bool(agree_terms),
        "veg_count": veg_clean,
        "non_veg_count": non_veg_clean,
    }
    return cleaned, errors


def register_guest(
    name: str,
    email: str,
    phone: str,
    ticket_count: int,
    plus_one_name: str,
    zelle_ref: str,
    veg_count: int = 0,
    non_veg_count: int = 0,
) -> dict:
    """Create a new guest registration.

    Assumes inputs are already validated/sanitized (see validate_registration).
    Does NOT send the QR email and does NOT record the submission log — the
    caller is responsible for both.

    Returns {"ok": True, "guest": {...}} on success, or
    {"ok": False, "reason": "duplicate_email"|"sold_out"|"not_enough_tickets"|
    "db_error"|"db_unavailable", "message": str}. The two capacity refusals
    also carry "remaining" (tickets still available) so the caller can show
    the guest how many are left.
    """
    # Refuse to write into the throwaway SQLite fallback: a registration
    # accepted there looks successful, emails a QR code, and then vanishes
    # when the container restarts. Far better to ask the guest to retry.
    if db_degraded():
        return {"ok": False, "reason": "db_unavailable", "message": DB_DEGRADED_MESSAGE}

    requested = int(ticket_count) if ticket_count else 1

    session = get_db()
    try:
        existing = session.query(Guest).filter_by(email=email).first()
        if existing:
            return {
                "ok": False,
                "reason": "duplicate_email",
                "message": "This email is already registered. Check your email or use the 'My QR' page.",
            }

        # Enforce the venue's hard ticket cap. This is the authoritative
        # check — the Register page's sold-out screen and clamped selector
        # are read from a cache and can be seconds stale, so the number that
        # actually decides is this one, read inside the same transaction as
        # the insert (and behind the advisory lock, so simultaneous submits
        # can't both spend the last seat).
        cap = config.max_total_tickets()
        if cap > 0:
            _lock_ticket_capacity(session)
            remaining = max(0, cap - tickets_sold(session))
            if remaining <= 0:
                return {"ok": False, "reason": "sold_out", "message": SOLD_OUT_MESSAGE, "remaining": 0}
            if requested > remaining:
                return {
                    "ok": False,
                    "reason": "not_enough_tickets",
                    "message": _not_enough_tickets_message(requested, remaining),
                    "remaining": remaining,
                }

        guest = Guest(
            name=name,
            email=email,
            phone=phone,
            ticket_count=requested,
            plus_one_name=plus_one_name,
            zelle_ref=zelle_ref,
            qr_code=generate_qr_code(),
            veg_count=veg_count,
            non_veg_count=non_veg_count,
        )
        session.add(guest)
        session.commit()
        return {"ok": True, "guest": guest.to_dict()}
    except IntegrityError:
        # Two concurrent submits with the same email both passed the
        # check above (TOCTOU) — the DB-level unique index closes the race.
        session.rollback()
        return {
            "ok": False,
            "reason": "duplicate_email",
            "message": "This email is already registered. Check your email or use the 'My QR' page.",
        }
    except Exception as e:
        session.rollback()
        return {"ok": False, "reason": "db_error", "message": f"Registration failed: {e}"}
    finally:
        session.close()


GUEST_NOT_FOUND_MESSAGE = (
    "No guest found. Check the spelling, or try their phone number or email instead."
)


def _resolve_guest(session, code: str):
    """Resolve a scanned/typed code to a Guest row, or None.

    Resolution order: qr_code, then email, then US phone number, then numeric
    id. Resolved via a single query (sqlalchemy.or_ over every condition)
    rather than sequential SELECTs; when more than one candidate row comes
    back the priority above is applied in Python, since the DB makes no
    ordering guarantee across an OR of different columns.

    Phone is matched on the normalized +1-XXX-XXX-XXXX form, so staff can
    type it however the guest reads it out. A code that isn't a valid US
    number simply contributes no phone condition — it must never fall
    through to matching the phone="" rows that predate phone being
    mandatory. Phone is not unique (a couple may share a number), so the
    most recent registration wins, consistent with get_guest_by_phone().
    """
    code = (code or "").strip()
    email_candidate = code.lower()
    phone_candidate = sanitize_phone(code)

    guest_id_candidate = None
    try:
        guest_id_candidate = int(code)
    except (ValueError, TypeError):
        guest_id_candidate = None

    conditions = [Guest.qr_code == code, Guest.email == email_candidate]
    if phone_candidate:
        conditions.append(Guest.phone == phone_candidate)
    if guest_id_candidate is not None:
        conditions.append(Guest.id == guest_id_candidate)

    candidates = session.query(Guest).filter(or_(*conditions)).all()

    guest = next((g for g in candidates if g.qr_code == code), None)
    if not guest:
        guest = next((g for g in candidates if g.email == email_candidate), None)
    if not guest and phone_candidate:
        phone_matches = [g for g in candidates if g.phone == phone_candidate]
        guest = max(phone_matches, key=lambda g: g.id) if phone_matches else None
    if not guest and guest_id_candidate is not None:
        guest = next((g for g in candidates if g.id == guest_id_candidate), None)
    return guest


def find_guest_by_code(code: str) -> dict:
    """Look up a guest by QR code, email, phone, or id WITHOUT checking them in.

    This is the first half of the door flow: staff search for whoever is in
    front of them — most often by phone, because guests routinely don't
    remember which of their email addresses the QR code went to — confirm
    the person from the details returned here, and only then call
    check_in_guest(). Nothing is written and the check-in window is not
    consulted, because looking someone up decides nothing on its own.

    Returns {"status": "found"|"not_found"|"db_unavailable", "guest": dict|
    None, "message": str}.
    """
    if db_degraded():
        return {"status": "db_unavailable", "guest": None, "message": DB_DEGRADED_MESSAGE}

    session = get_db()
    try:
        guest = _resolve_guest(session, code)
        if not guest:
            return {"status": "not_found", "guest": None, "message": GUEST_NOT_FOUND_MESSAGE}
        return {"status": "found", "guest": guest.to_dict(), "message": ""}
    finally:
        session.close()


def wristband_count(guest: dict) -> int:
    """How many wristbands this booking is owed — one per ticket.

    Named rather than inlined because "bands" and "tickets" are the same
    number for a reason (a booking of 4 tickets walks in as 4 people) and
    the door staff card states it explicitly; if that ever stops being
    one-to-one, this is the single place it changes.
    """
    try:
        return max(int(guest.get("ticket_count") or 1), 1)
    except (TypeError, ValueError):
        return 1


def check_in_by_code(code: str, bypass_window: bool = False) -> dict:
    """Resolve a scanned/typed code to a guest and check them in.

    See _resolve_guest() for how a code is matched (QR code, email, phone,
    or id).

    Enforces the check-in window (see checkin_status()) server-side: this is
    the real control, not just a UI convenience gate. If check-in is not
    currently open, returns {"status": "not_open", "guest": None, "message":
    ...} immediately and does NOT touch any row — no guest lookup, no writes.

    bypass_window: when True, skips the window check entirely. This exists
    so the admin dashboard's manual "check in" button keeps working
    regardless of the window — organisers must always be able to admit
    someone by hand (e.g. a guest who lost their phone, an early arrival
    helping set up). Only pass True from an already-authenticated admin
    action; the public Scanner page must always call this with the default
    (False) so the window is enforced for guests.

    Returns {"status": "success"|"already"|"not_found"|"not_open",
    "guest": dict|None, "message": str}. The "already" message is null-safe
    about checkin_time.
    """
    # A check-in recorded into the throwaway SQLite fallback would be lost on
    # the next restart — at the door that means re-admitting people who were
    # already scanned. Refuse rather than pretend.
    if db_degraded():
        return {"status": "db_unavailable", "guest": None, "message": DB_DEGRADED_MESSAGE}

    if not bypass_window:
        # use_cache=True: this runs on every single scan attempt in a door
        # queue, so it's the one call site that should benefit from
        # _cached_checkin_mode() rather than hitting app_settings every time
        # (see checkin_status()'s docstring for why every other caller reads
        # fresh instead).
        status = checkin_status(use_cache=True)
        if not status["open"]:
            return {"status": "not_open", "guest": None, "message": status["message"]}

    session = get_db()
    try:
        guest = _resolve_guest(session, code)

        if not guest:
            return {
                "status": "not_found",
                "guest": None,
                "message": "Invalid ticket. Please try again or check your email.",
            }

        if guest.checked_in:
            time_str = format_dt(guest.checkin_time, "%H:%M")
            return {
                "status": "already",
                "guest": guest.to_dict(),
                "message": f"{guest.name} already checked in at {time_str}",
            }

        guest.checked_in = True
        guest.checkin_time = _utc_now()
        log = CheckInLog(guest_id=guest.id, action="checkin", device_info="Streamlit Scanner")
        session.add(log)
        session.commit()

        return {
            "status": "success",
            "guest": guest.to_dict(),
            "message": f"Welcome {guest.name}!",
        }
    finally:
        session.close()


def check_in_guest(guest_id: int, bypass_window: bool = False) -> dict:
    """Check in one specific, already-identified guest.

    The second half of the door flow (see find_guest_by_code): staff have
    confirmed the person on screen is the person in front of them, so this
    takes the guest id rather than re-resolving a code. That matters — a
    phone number can belong to more than one booking, and re-running the
    search at confirm time could admit a different person than the one whose
    details staff just read back.

    Same contract as check_in_by_code(): {"status": "success"|"already"|
    "not_found"|"not_open"|"db_unavailable", "guest": dict|None,
    "message": str}.
    """
    if db_degraded():
        return {"status": "db_unavailable", "guest": None, "message": DB_DEGRADED_MESSAGE}

    if not bypass_window:
        status = checkin_status(use_cache=True)
        if not status["open"]:
            return {"status": "not_open", "guest": None, "message": status["message"]}

    session = get_db()
    try:
        guest = session.query(Guest).filter_by(id=guest_id).first()
        if not guest:
            return {"status": "not_found", "guest": None, "message": GUEST_NOT_FOUND_MESSAGE}

        if guest.checked_in:
            time_str = format_dt(guest.checkin_time, "%H:%M")
            return {
                "status": "already",
                "guest": guest.to_dict(),
                "message": f"{guest.name} already checked in at {time_str}",
            }

        guest.checked_in = True
        guest.checkin_time = _utc_now()
        log = CheckInLog(guest_id=guest.id, action="checkin", device_info="Streamlit Scanner")
        session.add(log)
        session.commit()

        return {
            "status": "success",
            "guest": guest.to_dict(),
            "message": f"Welcome {guest.name}!",
        }
    finally:
        session.close()


def mark_band_given(guest_id: int) -> dict:
    """Mark a guest's wristband as given.

    Returns {"ok": bool, "message": str}, distinguishing "not found" from
    "already given" (the old streamlit_app._mark_band_given silently did
    nothing — and showed no message — in both of those cases).
    """
    session = get_db()
    try:
        guest = session.query(Guest).filter_by(id=guest_id).first()
        if not guest:
            return {"ok": False, "message": "Guest not found."}
        if guest.band_given:
            return {"ok": False, "message": f"Band was already given to {guest.name}."}

        guest.band_given = True
        log = CheckInLog(guest_id=guest.id, action="band_given", device_info="Streamlit Scanner")
        session.add(log)
        session.commit()
        return {"ok": True, "message": f"Band marked as given for {guest.name}."}
    finally:
        session.close()


def delete_guest(guest_id: int) -> bool:
    """Delete a guest by id. Returns True if a guest was deleted, False if not found."""
    session = get_db()
    try:
        guest = session.query(Guest).filter_by(id=guest_id).first()
        if not guest:
            return False
        session.delete(guest)
        session.commit()
        return True
    finally:
        session.close()


def get_guest(guest_id: int) -> dict:
    """Return a single guest as a plain dict, or None if not found.

    Use this instead of scanning list_guests() — the My QR page and the
    registration success screen only ever need one row, and they re-run on
    every Streamlit interaction.
    """
    session = get_db()
    try:
        guest = session.query(Guest).filter_by(id=guest_id).first()
        return guest.to_dict() if guest else None
    except Exception:
        return None
    finally:
        session.close()


def get_guest_by_email(email: str) -> dict:
    """Return a single guest by email as a plain dict, or None if not found."""
    session = get_db()
    try:
        guest = session.query(Guest).filter_by(email=(email or "").strip().lower()).first()
        return guest.to_dict() if guest else None
    finally:
        session.close()


def get_guest_by_phone(phone: str) -> dict:
    """Return a single guest by US phone number as a plain dict, or None.

    The lookup key is the normalized +1-XXX-XXX-XXXX form, so a guest is found
    whether they type 5551234567, (555) 123-4567 or +1-555-123-4567. An
    unparseable number returns None instead of falling through to a blank
    lookup — rows registered before phone became mandatory have phone="" and
    must not all match each other.

    Phone is not unique (a couple may register separately from one number), so
    the most recent registration wins.
    """
    phone_clean = sanitize_phone(phone or "")
    if not phone_clean:
        return None

    session = get_db()
    try:
        guest = (
            session.query(Guest)
            .filter_by(phone=phone_clean)
            .order_by(Guest.id.desc())
            .first()
        )
        return guest.to_dict() if guest else None
    finally:
        session.close()


def find_guest_by_contact(query: str) -> tuple:
    """Look up one guest by either email address or US phone number.

    Returns (guest, error): the guest dict and None on a hit, or None and a
    user-facing message when the query is unusable or matched nothing. The
    field searched is decided by the shape of the input — an "@" means email,
    anything else is treated as a phone number.
    """
    q = (query or "").strip()
    if not q:
        return None, "Please enter your email address or phone number."

    if "@" in q:
        email_clean = sanitize_email(q)
        if not email_clean:
            return None, "Please enter a valid email address."
        guest = get_guest_by_email(email_clean)
    else:
        phone_clean = sanitize_phone(q)
        if not phone_clean:
            return None, "Please enter a valid email address or 10-digit US phone number."
        guest = get_guest_by_phone(phone_clean)

    if not guest:
        return None, "No guest found with that email or phone number. Please register first."
    return guest, None


def list_guests() -> list:
    """Return all guests, newest first, as plain dicts for the admin table."""
    session = get_db()
    try:
        guests = session.query(Guest).order_by(Guest.created_at.desc()).all()
        return [g.to_dict() for g in guests]
    finally:
        session.close()


def get_recent_checkins(limit: int = 10) -> list:
    """Return the most recent check-ins (newest first) as plain dicts."""
    session = get_db()
    try:
        recent = (
            session.query(Guest)
            .filter_by(checked_in=True)
            .order_by(Guest.checkin_time.desc())
            .limit(limit)
            .all()
        )
        return [g.to_dict() for g in recent]
    finally:
        session.close()


def get_registration_daily_counts() -> list:
    """Return [(date, count), ...] of registrations per day, oldest first.

    Used to drive the admin "registrations by day" bar chart.
    """
    session = get_db()
    try:
        guests = session.query(Guest).order_by(Guest.created_at).all()
        counts: dict = {}
        for g in guests:
            if not g.created_at:
                continue
            day = g.created_at.date()
            counts[day] = counts.get(day, 0) + (g.ticket_count or 0)
        return sorted(counts.items())
    finally:
        session.close()


def apply_guest_changes(updates: list) -> dict:
    """Apply a batch of admin spreadsheet edits (see the admin Guests tab) in
    one pass: check guests in, mark wristbands given, and delete guests.

    Each item in `updates` is a dict describing one guest row's desired end
    state: {"id": int, "checked_in": bool, "band_given": bool, "delete":
    bool}. This is the shape st.data_editor's edited dataframe gets mapped
    into by the caller.

    - "checked_in"/"band_given" are one-way: only a False -> True
      transition does anything (there is no "undo check-in"/"undo band"
      action here). Rows already in the desired state are a no-op and are
      not counted.
    - "delete" takes priority: a row marked for deletion is deleted and its
      checked_in/band_given flags are ignored (no point writing a check-in
      log for a guest that's about to disappear). The caller is responsible
      for getting explicit confirmation before any row reaches here with
      delete=True — this function performs the deletion immediately.
    - Every check-in goes through check_in_by_code(..., bypass_window=True),
      exactly like the old single-guest admin "Check In" button did —
      organisers must always be able to admit someone from this table
      regardless of whether the public check-in window is currently open.

    Returns {"checked_in": int, "band_given": int, "deleted": int}: counts
    of rows that actually changed, not the count of rows submitted.
    """
    checked_in_count = 0
    band_given_count = 0
    deleted_count = 0

    for u in updates or []:
        guest_id = u.get("id")
        if guest_id is None:
            continue

        if u.get("delete"):
            if delete_guest(guest_id):
                deleted_count += 1
            continue

        if u.get("checked_in"):
            result = check_in_by_code(str(guest_id), bypass_window=True)
            if result["status"] == "success":
                checked_in_count += 1

        if u.get("band_given"):
            result = mark_band_given(guest_id)
            if result["ok"]:
                band_given_count += 1

    return {
        "checked_in": checked_in_count,
        "band_given": band_given_count,
        "deleted": deleted_count,
    }


def get_event_day_hourly_checkins() -> list:
    """Return a list of 24 ints: check-in count per hour on the event day.

    Used to drive the admin "check-ins on event day" bar chart.
    """
    session = get_db()
    try:
        event_start = config.EVENT_DATE.replace(hour=0, minute=0, second=0, microsecond=0)
        event_end = event_start + timedelta(days=1)
        event_checkins = (
            session.query(Guest)
            .filter(
                Guest.checked_in == True,
                Guest.checkin_time >= event_start,
                Guest.checkin_time < event_end,
            )
            .all()
        )
        hourly = [0] * 24
        for g in event_checkins:
            if g.checkin_time:
                hourly[g.checkin_time.hour] += 1
        return hourly
    finally:
        session.close()


# ── Full Backup Export (Admin "Danger Zone") ─────────────────────────────────
#
# generate_csv() above is the *human* export: the guest list, prettified
# ("Yes"/"No", no ids). What follows is the *archival* export — every table
# reset_all_data() can wipe, every column, raw values — so a reset is
# recoverable and the data is still queryable after the database is empty.

# (table, model, columns to export, column to sort by, what the table holds).
# Order matches reset_all_data()'s blast radius; descriptions are surfaced in
# the admin UI and in each backup's README.
_BACKUP_SPECS = (
    (
        "guests",
        Guest,
        ("id", "name", "email", "phone", "ticket_count", "plus_one_name",
         "zelle_ref", "qr_code", "checked_in", "band_given", "checkin_time", "created_at",
         "veg_count", "non_veg_count"),
        "id",
        "One row per registration — contact details, tickets, QR code, check-in state.",
    ),
    (
        "checkin_logs",
        CheckInLog,
        ("id", "guest_id", "action", "timestamp", "device_info"),
        "id",
        "Audit trail of every check-in and band hand-out. guest_id → guests.id.",
    ),
    (
        "page_visits",
        PageVisit,
        ("id", "visitor_token", "page", "visited_at"),
        "id",
        "One row per page view, keyed by an anonymous per-browser visitor token.",
    ),
    (
        "submission_logs",
        SubmissionLog,
        ("id", "name", "email", "phone", "ticket_count", "plus_one_name",
         "zelle_ref", "status", "errors", "guest_id", "created_at",
         "veg_count", "non_veg_count"),
        "id",
        "Every registration attempt — successful or not — with its failure reason.",
    ),
    (
        "app_settings",
        AppSetting,
        ("key", "value", "updated_at"),
        "key",
        "Organiser-wide settings that outlive a restart (currently: checkin_mode).",
    ),
)

BACKUP_TABLES = tuple(spec[0] for spec in _BACKUP_SPECS)

# (table name, what it holds) — the public half of _BACKUP_SPECS, for the
# admin UI's "tables you can query" reference.
DATA_TABLES = tuple((spec[0], spec[4]) for spec in _BACKUP_SPECS)


def _csv_cell(value):
    """Render one column value for the archival CSV.

    Datetimes go out as ISO-8601 (they are stored naive UTC — see _utc_now),
    booleans as true/false, NULL as empty. Strings run through the same
    formula-injection guard as generate_csv(): a name like "=cmd()" must not
    execute when the organiser opens the backup in Excel.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, str):
        return _sanitize_csv_field(value)
    return value


def _rows_to_csv(columns, rows) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(getattr(row, col)) for col in columns])
    return output.getvalue()


def _backup_readme(generated_at: datetime, counts: dict) -> str:
    """The README bundled in the ZIP: what's inside, and how to query it later."""
    lines = [
        "Party Check-In — full data backup",
        f"Exported: {generated_at.isoformat(sep=' ', timespec='seconds')} UTC",
        "",
        "One CSV per table. The header row is the exact column name in the",
        "database, so these files can be loaded straight back into the same",
        "schema (or into any spreadsheet) after a Danger Zone reset.",
        "",
        "TABLES",
    ]
    for table, _model, columns, _order, description in _BACKUP_SPECS:
        lines.append(f"  {table}.csv — {counts.get(table, 0)} row(s)")
        lines.append(f"      {description}")
        lines.append(f"      columns: {', '.join(columns)}")
    lines += [
        "",
        "REPORTING VIEWS (PostgreSQL/Supabase only — created automatically at startup)",
    ]
    for view, description in REPORTING_VIEWS:
        lines.append(f"  {view} — {description}")
    lines += [
        "",
        "These views read from the tables above, so they are empty after a reset",
        "and refill on their own as new data arrives — nothing to recreate.",
        "",
        "Sample queries:",
        "  SELECT * FROM vw_registrations_summary;",
        "  SELECT * FROM guests WHERE checked_in = true ORDER BY checkin_time;",
        "  SELECT * FROM vw_submissions_summary;",
        "",
    ]
    return "\n".join(lines)


def export_backup() -> dict:
    """Export every resettable table to CSV and bundle it into a ZIP.

    All tables are read from ONE session so the CSVs are a coherent snapshot
    rather than five reads taken at five different moments. Buffered page
    visits (see record_visit()) are flushed to the database first — a backup
    taken just before a reset must not silently drop the rows that were still
    sitting in memory.

    Returns:
        {
          "generated_at": datetime (naive UTC),
          "stamp": "20260810_143000"        # for filenames
          "counts": {"guests": 5, ...},
          "files": {"guests.csv": "<csv text>", ..., "README.txt": "..."},
          "zip": bytes                       # every file above, deflated
        }
    """
    flush_page_visits()
    generated_at = _utc_now()
    session = get_db()
    try:
        files = {}
        counts = {}
        for table, model, columns, order_by, _description in _BACKUP_SPECS:
            rows = session.query(model).order_by(getattr(model, order_by)).all()
            counts[table] = len(rows)
            files[f"{table}.csv"] = _rows_to_csv(columns, rows)
    finally:
        session.close()

    files["README.txt"] = _backup_readme(generated_at, counts)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)

    return {
        "generated_at": generated_at,
        "stamp": generated_at.strftime("%Y%m%d_%H%M%S"),
        "counts": counts,
        "files": files,
        "zip": buffer.getvalue(),
    }


# ── Data Reset (Admin "Danger Zone") ─────────────────────────────────────────

def get_table_counts() -> dict:
    """Return current row counts for every table reset_all_data() can wipe.

    Used by the admin Danger Zone UI so the operator can see exactly what a
    reset is about to destroy before they confirm it. Flushes the buffered
    page-visit rows first (see record_visit()) so the page_visits count
    isn't missing whatever hasn't hit the DB yet.
    """
    flush_page_visits()
    session = get_db()
    try:
        return {
            "guests": session.query(Guest).count(),
            "checkin_logs": session.query(CheckInLog).count(),
            "page_visits": session.query(PageVisit).count(),
            "submission_logs": session.query(SubmissionLog).count(),
        }
    finally:
        session.close()


def reset_all_data(keep_settings: bool = True) -> dict:
    """Delete ALL rows from guests, checkin_logs, page_visits, submission_logs.

    Does NOT drop any table and does NOT touch the schema — this only empties
    tables that already exist. Everything happens in ONE transaction (a
    single session, committed once at the end): if anything fails partway
    through, the whole reset rolls back rather than leaving e.g. guests
    deleted with their checkin_logs orphaned. Children are deleted before
    parents — checkin_logs.guest_id references guests.id.

    Always resets the persisted check-in mode back to CHECKIN_MODE_AUTO —
    a clean slate should not leave check-in forced open/closed by a leftover
    testing override.

    keep_settings=False additionally clears app_settings entirely (including
    the checkin_mode row this function would otherwise write); with no rows
    left, get_checkin_mode() falls back to its own "auto" default, so the
    effective behavior is the same either way.

    Returns the per-table counts actually deleted, e.g.
    {"guests": 12, "checkin_logs": 9, "page_visits": 40, "submission_logs": 15}.
    Raises on failure (after rolling back) — callers must not report success
    without catching it.
    """
    # Flush any buffered page visits (see record_visit()) to the DB BEFORE
    # deleting, so they're included in the deleted count and, just as
    # importantly, so a stray background flush can't write them back into
    # page_visits moments after this "empties everything" reset ran.
    flush_page_visits()
    session = get_db()
    try:
        # Children before parents: checkin_logs.guest_id references guests.id.
        # Query.delete() returns the number of rows actually removed, so the
        # reported counts reflect this transaction's DELETEs exactly rather
        # than a separate COUNT(*) that could race with a concurrent write.
        checkin_logs_deleted = session.query(CheckInLog).delete(synchronize_session=False)
        guests_deleted = session.query(Guest).delete(synchronize_session=False)
        page_visits_deleted = session.query(PageVisit).delete(synchronize_session=False)
        submission_logs_deleted = session.query(SubmissionLog).delete(synchronize_session=False)

        if keep_settings:
            row = session.query(AppSetting).filter_by(key=_CHECKIN_MODE_SETTING_KEY).first()
            if row is None:
                session.add(
                    AppSetting(
                        key=_CHECKIN_MODE_SETTING_KEY,
                        value=CHECKIN_MODE_AUTO,
                        updated_at=_utc_now(),
                    )
                )
            else:
                row.value = CHECKIN_MODE_AUTO
                row.updated_at = _utc_now()
        else:
            session.query(AppSetting).delete(synchronize_session=False)

        session.commit()
        return {
            "guests": guests_deleted,
            "checkin_logs": checkin_logs_deleted,
            "page_visits": page_visits_deleted,
            "submission_logs": submission_logs_deleted,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
