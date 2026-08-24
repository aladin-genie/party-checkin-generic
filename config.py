"""
Party Check-In System — Configuration
Single source of truth for secret access and hardcoded event details.

Event date/venue/name strings and ticket-price/Zelle secret access used to be
duplicated across utils.py (email body, Postgres views) and streamlit_app.py
(hero banner, Terms & Conditions text, EVENT_DATE). This module centralizes
both so there is exactly one place to update them.
"""

import os
from datetime import datetime, timedelta, timezone

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit should always be installed
    st = None

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - zoneinfo is stdlib on 3.9+, but the tz
    # database itself can be missing on some minimal deploy images.
    ZoneInfo = None


def get_secret(key: str, default: str = "") -> str:
    """Read a secret: st.secrets first, then env var, then default.

    Must never raise. st.secrets raises StreamlitSecretsFileNotFoundError when
    no secrets file exists at all (e.g. a fresh deploy that hasn't set any
    secrets yet), so every path here is wrapped in try/except.
    """
    try:
        if st is not None:
            return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        pass
    return os.getenv(key, default)


def get_secret_int(key: str, default: int) -> int:
    """Like get_secret, but coerces to int and tolerates bad/missing values."""
    try:
        return int(get_secret(key, str(default)))
    except Exception:
        return default


# ── Event Details ────────────────────────────────────────────────────────────

EVENT_NAME = "DFW Yakshagana Havyasis"
EVENT_TAGLINE = "Promoting Yakshagana Art in North America"
EVENT_DATE = datetime(2027, 1, 1)
EVENT_TIME_TEXT = "TBD"
EVENT_DATE_TEXT = "Friday, January 1, 2027"
EVENT_DATE_SHORT = "Fri, Jan 1, 2027"

# Dress-up theme for the event. Drives the app's whole look (see theme.py) as
# well as the badge on the hero, so guests arriving from the flyer land
# somewhere that looks like the flyer.
EVENT_THEME = "Yakshagana"
EVENT_THEME_NOTE = "Traditional attire & face paint encouraged"

# Optional local-language tagline shown under the tagline on the hero.
EVENT_TAGLINE_LOCAL = "ಯಕ್ಷಗಾನ — ಕರ್ನಾಟಕದ ಗೌರವ"

VENUE_NAME = "DFW Metroplex Venue TBD"
VENUE_ADDRESS = "DFW Metroplex, TX (address TBD)"

APP_VERSION = "1.0-generic"

# Public URL of the deployed app, used to build links in outgoing email.
_DEFAULT_APP_URL = "https://party-checkin-generic.streamlit.app"
APP_URL = get_secret("APP_URL", _DEFAULT_APP_URL).rstrip("/")

# ── Landing page ─────────────────────────────────────────────────────────────
# The bare app URL is the link the organiser sends out, so it opens on the
# thing that link is *for*: registration. Home is where a guest is sent after
# they submit — the hub for stats, photos, sponsors, and everything else — so
# it is deliberately the destination, not the doorstep. An explicit
# `?page=Home` (or the sidebar) still reaches Home directly.
LANDING_PAGE = "Register"


# ── Home page content: photos & sponsors ─────────────────────────────────────
# Both lists are still being finalised, so they ship empty and the Home page
# renders a "coming soon" placeholder for each. Filling them in is a pure
# data edit — no code or layout changes needed.
#
# `src`/`logo` may be either a public https URL or a path relative to this
# repo (e.g. "assets/photos/dance-floor.jpg"); utils.resolve_image_src()
# inlines local files as data URIs, because Streamlit does not serve
# arbitrary files over HTTP. Anything it cannot resolve is dropped rather
# than rendered as a broken image.

# The printed event flyer, shown on Home and behind an expander on Register.
# Optional: utils.resolve_image_src() returns "" for anything it can't
# resolve, so blanking this (or deleting the file) makes both call sites
# render nothing rather than break.
EVENT_FLYER = "assets/flyer.png"


# The gallery. Add real photos before the event. Each entry is either a
# public https URL or a path relative to this repo (e.g.
# "assets/photos/dance-floor.jpg"); utils.resolve_image_src() inlines local
# files as data URIs because Streamlit does not serve arbitrary files over
# HTTP. Anything it cannot resolve is dropped rather than rendered as a broken
# image.
#
# Order is display order, so the strongest real photo leads.
PHOTOS = [
    {"src": "assets/photos/yakshagana-on-stage.jpg",
     "caption": "Yakshagana on stage — dance, drama, and devotion"},
    {"src": "assets/photos/yakshagana-krishna.jpg",
     "caption": "The vibrant art of Yakshagana from Karnataka"},
]

# Tier display order, best first. A sponsor whose `tier` isn't listed here is
# still shown — it just sorts to the end under its own heading, so a new tier
# invented mid-season can't make a sponsor vanish. The FIRST tier is rendered
# larger than the rest (see theme.sponsor_wall).
SPONSOR_TIERS = ("Top Sponsor", "Gold", "Silver", "Community")

# `tier` should be one of SPONSOR_TIERS. `url` (https only), `logo` and
# `blurb` are all optional — a sponsor with just a name still gets a card,
# since the lineup is usually confirmed before the artwork arrives.
SPONSORS = []


# Ticket price in cents. Deliberately a plain constant rather than a secret,
# like EVENT_DATE and VENUE_NAME above: the price is an event detail, not a
# deployment credential.
#
# It used to read a TICKET_PRICE_CENTS secret. That is a trap, because
# get_secret() gives st.secrets precedence over the code default — so a stale
# value left in the Streamlit Cloud dashboard silently overrides whatever
# price is shipped in code. The $20 -> $30 rise deployed correctly and the
# live site kept charging $20, with nothing in the repo to explain why.
# Changing the price is now a one-line edit here plus a redeploy, and what
# the code says is what guests are charged. GROUP_DISCOUNT_TIERS below are
# discounts *off* this number, so moving it moves every tier with it.
TICKET_PRICE_CENTS = 5000


def ticket_price_cents() -> int:
    """Return the base (individual) ticket price in cents.

    This is the full price one person pays. Larger bookings pay less per
    ticket — see ticket_price_cents_for(), which is what the Register page
    and every total actually use.
    """
    return TICKET_PRICE_CENTS


def ticket_price_dollars() -> float:
    """Return the base (individual) ticket price in dollars."""
    return ticket_price_cents() / 100


# ── Group discounts ──────────────────────────────────────────────────────────
# A bigger booking pays less per ticket. Each tier is
# (minimum tickets in ONE registration, discount per ticket in cents), and a
# booking is charged at the last tier whose minimum it reaches. At the
# $50.00 base that gives the requested pricing:
#
#     1–25 tickets   →  $50.00 each
#     26–75 tickets  →  $25.00 each
#     76+ tickets    →  $10.00 each
#
# Note the boundaries are INCLUSIVE of the lower bound: a booking of exactly
# 26 pays $25, and exactly 76 pays $10. Guests price their group off the
# displayed table, so the app has to agree with it at the boundary or someone
# Zelles the wrong amount.
#
# Stored as money OFF the base rather than as absolute prices so that raising
# TICKET_PRICE_CENTS moves every tier with it — otherwise a price rise would
# silently turn the "discounts" into surcharges.
#
# The discount is per registration, not per person across registrations: 76
# tickets bought in one booking get the 76+ rate; separate smaller bookings
# are charged at their own tier. That is the only rule the app can actually
# enforce, since separate registrations are separate people paying separately.
GROUP_DISCOUNT_TIERS = (
    (26, 2500),   # 26+ tickets: $25.00 off each → $25/ticket
    (76, 4000),   # 76+ tickets: $40.00 off each → $10/ticket
)


def ticket_price_cents_for(ticket_count) -> int:
    """Per-ticket price in cents for a booking of `ticket_count` tickets.

    Must never raise: this feeds the price shown on the form, and a garbage
    ticket count (the selector is a client-side widget) has to fall back to
    the full base price rather than take the page down. Falling back *up* to
    the base price is the safe direction — it can never invent a discount
    nobody is entitled to.
    """
    base = ticket_price_cents()
    try:
        count = int(ticket_count)
    except (TypeError, ValueError):
        return base

    discount = 0
    # Sorted rather than trusting the literal above to stay in order — a tier
    # appended out of sequence would otherwise silently win over a larger one.
    for minimum, off in sorted(GROUP_DISCOUNT_TIERS):
        if count >= minimum:
            discount = off
    # A misconfigured tier must not produce a free (or negative) ticket.
    return max(base - discount, 0)


def ticket_price_dollars_for(ticket_count) -> float:
    """Per-ticket price in dollars for a booking of `ticket_count` tickets."""
    return ticket_price_cents_for(ticket_count) / 100


def booking_total_cents(ticket_count) -> int:
    """What a booking of `ticket_count` tickets costs in total, in cents.

    Integer cents throughout — the amount a guest is told to Zelle must not
    drift by a rounding error, and float dollars can't represent every price
    exactly.
    """
    try:
        count = max(0, int(ticket_count))
    except (TypeError, ValueError):
        count = 0
    return count * ticket_price_cents_for(count)


def booking_total_dollars(ticket_count) -> float:
    """What a booking of `ticket_count` tickets costs in total, in dollars."""
    return booking_total_cents(ticket_count) / 100


def booking_savings_cents(ticket_count) -> int:
    """How much a booking saves against paying the base price per ticket.

    0 for any booking that isn't big enough for a discount.
    """
    try:
        count = max(0, int(ticket_count))
    except (TypeError, ValueError):
        return 0
    return count * (ticket_price_cents() - ticket_price_cents_for(count))


def price_tiers() -> list:
    """The whole price table, ready to display.

    Returns a list of {"min", "max", "price_cents"} dicts covering every
    booking size from 1 upward, with `max` = None on the open-ended top
    tier. Derived from GROUP_DISCOUNT_TIERS rather than written out
    separately, so what the Register page shows a guest can't drift from
    what ticket_price_cents_for() actually charges them.
    """
    minimums = sorted({int(m) for m, _off in GROUP_DISCOUNT_TIERS if int(m) > 1})
    boundaries = [1] + minimums

    tiers = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else None
        tiers.append({
            "min": start,
            "max": end,
            "price_cents": ticket_price_cents_for(start),
        })
    return tiers


def next_price_tier(ticket_count):
    """The next cheaper tier a booking could reach, or None.

    Used to tell someone booking 10 tickets that an 11th would drop the
    price of every ticket. Returns None when the booking is already on the
    best tier, or when reaching the next one would exceed
    MAX_TICKETS_PER_REGISTRATION (there's no point advertising a price the
    form won't let them buy).
    """
    try:
        count = int(ticket_count)
    except (TypeError, ValueError):
        return None

    current_price = ticket_price_cents_for(count)
    for tier in price_tiers():
        if tier["min"] > count and tier["price_cents"] < current_price:
            if tier["min"] > MAX_TICKETS_PER_REGISTRATION:
                return None
            return tier
    return None


# ── Ticket capacity ──────────────────────────────────────────────────────────
# The venue holds a fixed number of people, so unlike the concurrency guard
# below (which only throttles simultaneous *browsing*), this is a real, hard
# cap on how many tickets can ever be sold.

def max_total_tickets() -> int:
    """Hard cap on tickets sold across ALL guests.

    Once this many tickets are registered the Register page shows a sold-out
    screen instead of the form, and utils.register_guest() refuses to write
    past it. Tunable via the MAX_TOTAL_TICKETS secret so the organiser can
    raise or lower the cap without a redeploy; 0 (or negative) disables the
    cap entirely and restores unlimited registration.
    """
    return get_secret_int("MAX_TOTAL_TICKETS", 225)


# Most tickets one guest may claim in a single registration. The Register page
# also clamps its selector to whatever is actually left, so the effective
# maximum is min(this, tickets remaining).
#
# The top tier starts at 76 tickets (see GROUP_DISCOUNT_TIERS), so the cap
# must be at least that high or the tier becomes unbuyable —
# config.next_price_tier() refuses to advertise a tier past this cap for the
# same reason, and test_top_discount_tier_is_actually_bookable fails if it
# ever slips below.
#
# Set to 100 to leave headroom above the 76+ tier.
#
# Raising this raises utils.MAX_GUEST_NAMES (this minus one), so a 100-ticket
# booking must name its other 99 guests. utils.GUEST_NAMES_MAX_CHARS — the
# size of the Register form's name box AND of the plus_one_name column — is
# derived from that, so the storage grows with the cap instead of silently
# truncating the tail of a big booking's guest list.
MAX_TICKETS_PER_REGISTRATION = 100


_DEFAULT_ZELLE = "dfwygana@gmail.com"
_PLACEHOLDER_ZELLE = "your-zelle-phone@email.com or +1-234-567-8900"


def max_concurrent_users() -> int:
    """Hard concurrency limit for the capacity guard.

    Above this many active sessions (see utils.active_session_count()), a
    new visitor sees the friendly "we're at capacity" screen instead of the
    app. Tunable via the MAX_CONCURRENT_USERS secret so it can be adjusted
    without a redeploy.
    """
    return get_secret_int("MAX_CONCURRENT_USERS", 60)


def busy_warn_users() -> int:
    """Soft concurrency limit for the capacity guard.

    Above this many active sessions (but at/below max_concurrent_users()), a
    visitor is still let through but sees a small "busier than usual"
    banner. Tunable via the BUSY_WARN_USERS secret.
    """
    return get_secret_int("BUSY_WARN_USERS", 40)


def zelle_info() -> str:
    """Return the Zelle payment info to display, with placeholder fallback.

    Falls back to the default organiser Zelle handle when the secret is
    unset, blank, still set to the example placeholder value, or contains
    the "organizer will share" stand-in text.
    """
    value = get_secret("ZELLE_INFO", _DEFAULT_ZELLE).strip()
    if not value or value == _PLACEHOLDER_ZELLE or "organizer will share" in value.lower():
        return _DEFAULT_ZELLE
    return value


def days_until_event() -> int:
    """Return the number of whole days from now until the event. 0 if past."""
    delta = EVENT_DATE - datetime.now()
    return max(0, delta.days)


def qr_prefix() -> str:
    """Return the QR-code prefix derived from the event year, e.g. 'PARTY2026'."""
    return f"PARTY{EVENT_DATE.year}"


# ── Check-in window ──────────────────────────────────────────────────────────
# Guests must not be able to check in weeks before the party. Check-in opens
# CHECKIN_LEAD_HOURS before the event start by default (see utils.checkin_status
# for the persistent admin override that can force it open/closed).

EVENT_TIMEZONE = "America/Chicago"  # TODO: update to venue timezone
EVENT_START_LOCAL = datetime(2027, 1, 1, 17, 30)  # TODO: update to event start time
CHECKIN_LEAD_HOURS = 2

# Used only if the system tz database is unavailable (see _event_start_local_aware).
# America/Chicago is UTC-5 (CDT) for the whole lead-up to an October event.
_FALLBACK_UTC_OFFSET_HOURS = 5


def _event_start_local_aware() -> datetime:
    """Return EVENT_START_LOCAL as a timezone-aware datetime in EVENT_TIMEZONE.

    Raises if zoneinfo/the tz database is unavailable. Callers must catch and
    fall back — this helper itself is allowed to raise so both public
    functions below can share one fallback story.
    """
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo module unavailable")
    return EVENT_START_LOCAL.replace(tzinfo=ZoneInfo(EVENT_TIMEZONE))


def event_start_utc() -> datetime:
    """Return the event start time as a naive UTC datetime.

    Builds an aware local datetime in EVENT_TIMEZONE and converts to UTC
    (rather than hand-rolling a fixed offset) so this stays correct even if
    the event date is ever moved across a DST boundary. The result is naive
    (tzinfo dropped) to match _utc_now() in utils.py, which is how the DB
    stores timestamps.

    Must never raise: falls back to treating EVENT_START_LOCAL as already
    being UTC-5 if the tz database is unavailable.
    """
    try:
        aware = _event_start_local_aware()
        return aware.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception as e:
        print(f"config.event_start_utc: zoneinfo unavailable, falling back to UTC-{_FALLBACK_UTC_OFFSET_HOURS}: {e}")
        return EVENT_START_LOCAL + timedelta(hours=_FALLBACK_UTC_OFFSET_HOURS)


def checkin_opens_at_utc() -> datetime:
    """Return the naive UTC datetime at which check-in opens (auto mode)."""
    return event_start_utc() - timedelta(hours=CHECKIN_LEAD_HOURS)


def checkin_opens_at_text() -> str:
    """Return a human-readable LOCAL check-in-opens time for the UI.

    e.g. "Fri, Oct 9, 2026 at 3:30 PM CDT". Falls back to the same rendering
    without a timezone abbreviation if the tz database is unavailable. Never
    raises.
    """
    try:
        opens_local = _event_start_local_aware() - timedelta(hours=CHECKIN_LEAD_HOURS)
        tzname = opens_local.tzname() or ""
    except Exception as e:
        print(f"config.checkin_opens_at_text: zoneinfo unavailable, falling back: {e}")
        opens_local = EVENT_START_LOCAL - timedelta(hours=CHECKIN_LEAD_HOURS)
        tzname = ""

    hour12 = opens_local.strftime("%I").lstrip("0") or "12"
    text = (
        f"{opens_local.strftime('%a, %b')} {opens_local.day}, {opens_local.year} "
        f"at {hour12}:{opens_local.strftime('%M %p')}"
    )
    return f"{text} {tzname}".strip()
