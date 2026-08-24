"""
Party Check-In System — Configuration
Single source of truth for secret access and hardcoded event details.

Event date/venue/name strings and ticket-price/Zelle secret access used to be
duplicated across utils.py (email body, Postgres views) and streamlit_app.py
(hero banner, Terms & Conditions text, EVENT_DATE). This module centralizes
both so there is exactly one place to update them.
"""

import os
import re
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
EVENT_SUBTITLE = "Prasanga — Sri Devi Mahathme"
EVENT_TAGLINE = "Promoting Yakshagana Art in North America"
EVENT_DATE = datetime(2026, 10, 3)
EVENT_TIME_TEXT = "6:00 PM onwards"
EVENT_DATE_TEXT = "Saturday, October 3, 2026"
EVENT_DATE_SHORT = "Sat, Oct 3, 2026"

# Dress-up theme for the event. Drives the app's whole look (see theme.py) as
# well as the badge on the hero, so guests arriving from the flyer land
# somewhere that looks like the flyer.
EVENT_THEME = "Yakshagana"
EVENT_THEME_NOTE = "Traditional attire & face paint encouraged"

# Optional local-language tagline shown under the tagline on the hero.
EVENT_TAGLINE_LOCAL = "ಅದ್ಭುತ ದೇವಿ ಮಹಾತ್ಮೆ — ಯಕ್ಷಗಾನ ಪ್ರಸಂಗ"

# The specific performance being staged this evening, e.g. "Sri Devi
# Mahathme" — the last " — "-separated segment of EVENT_SUBTITLE.
# EVENT_SUBTITLE is flyer-style ("Prasanga — Sri Devi Mahathme": "Prasanga"
# is the generic Yakshagana word for "the story being performed", not part
# of the title itself), but a guest scanning open browser tabs is looking
# for the actual performance name, not that category prefix. Falls back to
# the whole of EVENT_SUBTITLE if it has no "—" to split on (e.g. the copy
# is ever simplified to just a bare title), so this is never blank while
# EVENT_SUBTITLE is set.
_performance_title = EVENT_SUBTITLE.rsplit("—", 1)[-1].strip() if EVENT_SUBTITLE else ""

# Browser tab title. Built here — not as an f-string in streamlit_app.py —
# so there is exactly one place that decides it, per this module's "single
# source of truth for event strings" job. It leads with the performance
# name, since that's what a guest hunting through open tabs is looking for,
# with EVENT_NAME (the organisation) as trailing context. Falls back to the
# old "<org> — Check-In" form if EVENT_SUBTITLE is ever blanked.
# streamlit_app.py's set_page_config() cannot reach this constant at all
# when config itself failed to import — it falls back to a bare "Check-In"
# string on its own in that case.
PAGE_TITLE = f"{_performance_title} — {EVENT_NAME}" if _performance_title else f"{EVENT_NAME} — Check-In"

VENUE_NAME = "Unity of Dallas"
VENUE_ADDRESS = "6525 Forest Lane, Dallas, TX 75230"

# Venue logistics shown in theme.venue_info_card() on the Register page.
# Kept here (not hand-typed in theme.py) so VENUE_NAME appears exactly once
# in the codebase and the parking line can never mention a different venue
# than the one guests are actually registering for.
VENUE_PARKING_TEXT = f"Free parking on the {VENUE_NAME} campus."
VENUE_DOORS_TEXT = f"The program begins at {EVENT_TIME_TEXT} — arrive early for parking and seating."
VENUE_HOUSE_RULE_TEXT = "The building must be cleared by 10:00 PM."

# Two facts a guest choosing seats must not miss — surfaced as their own
# chips next to the seat picker (see theme.seat_policy_chips()) rather than
# buried in a paragraph, per the same "one home for event copy" rule as the
# VENUE_* text above.
#
# FOOD_POLICY_TEXT lives here. KIDS_POLICY_TEXT is defined further down (see
# free_kid_seat_range_label(), near the seat-tier helpers) because it now
# NAMES the free-child seat range, which means it can't be built until
# SEAT_TIERS/seat_label() exist — the organiser's rule is no longer just
# "kids are free" (an open question this copy used to duck), it's "kids are
# free, but only in the cheapest tier; a front-row seat is bought like any
# other seat" — see is_free_kid_seat()/free_kid_seat_numbers() below.
FOOD_POLICY_TEXT = "Vegetarian food is available for purchase at the venue."

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
EVENT_FLYER = "assets/prasanga-flyer.webp"


# The gallery. Add real photos before the event. Each entry is either a
# public https URL or a path relative to this repo (e.g.
# "assets/photos/dance-floor.jpg"); utils.resolve_image_src() inlines local
# files as data URIs because Streamlit does not serve arbitrary files over
# HTTP. Anything it cannot resolve is dropped rather than rendered as a broken
# image.
#
# Order is display order, so the strongest real photo leads.
#
# Do NOT list EVENT_FLYER here. Home already renders it above this gallery
# via theme.flyer_card(), and every local image is base64-inlined into the
# page HTML — which Streamlit re-sends on every rerun. Listing the flyer in
# both places inlined the same image twice and pushed Home to ~2.5MB of HTML
# per interaction, most of it one duplicated poster.
PHOTOS = [
    {"src": "assets/photos/yakshagana-on-stage.webp",
     "caption": "Yakshagana on stage — dance, drama, and devotion"},
    {"src": "assets/photos/yakshagana-krishna.webp",
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
# the code says is what guests are charged. SEAT_TIERS below are absolute
# seat prices; only seat 1 falls back to this base price.
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


# ── Seat pricing ─────────────────────────────────────────────────────────────
# Cinema-style tiered seating: each numbered seat has its own price.
# Seat 1–25 cost $50, seats 26–75 cost $25, seats 76–100 cost $10.
# A booking of N consecutive seats pays the sum of seats 1..N.
#
#     seat 1–25   →  $50.00 each
#     seat 26–75  →  $25.00 each
#     seat 76–100 →  $10.00 each
#
# Boundaries are INCLUSIVE. The seat map on the Register page shows the
# tiers so guests know exactly what they are paying before they Zelle.
#
# These seats are REAL, individually-bookable inventory, not a display
# convenience: TOTAL_SEATS below is DERIVED from the highest seat number
# covered by the LAST tier here, and that derived number is the hard cap on
# how many tickets this app will ever sell (see max_total_tickets()). So
# this tuple is the one place that decides the size of the bookable block —
# extending the top tier's end (or adding a new tier past it) grows
# TOTAL_SEATS, the cap, and the seat map together.
#
# The venue (Unity of Dallas) actually seats roughly 850 people, but no
# public seating chart for its sanctuary publishes real rows/sections, so
# this table intentionally does NOT try to model the real room — it only
# claims the 100 seats the organiser has actually priced off the printed
# flyer ($50 / $25 / $10). Selling a bigger block is a pricing decision only
# the organiser can make (which band do the other ~750 seats belong to?),
# not something to guess at here. To open up more seats, the organiser must
# extend these tiers (or add a new one) to cover as many seats as they want
# to sell — TOTAL_SEATS and the cap follow automatically.
#
# seat_price_cents() falls back to the BASE price (TICKET_PRICE_CENTS —
# seat 1's price, the most expensive tier) for any seat number that isn't
# covered by a tier below. That fallback exists so a garbage/out-of-range
# lookup never raises, but it also means these tiers MUST cover every seat
# that actually exists (every seat in all_seat_numbers(), i.e. 1..
# TOTAL_SEATS) — otherwise a real seat past the last tier would silently be
# charged the PREMIUM rate instead of falling cheaper as expected.
# test_every_seat_is_covered_by_an_explicit_tier (test_config.py) enforces
# this; keep it passing when editing these tiers.
SEAT_TIERS = (
    (1, 25, 5000),    # seats 1–25: $50.00 each
    (26, 75, 2500),   # seats 26–75: $25.00 each
    (76, 100, 1000),  # seats 76–100: $10.00 each
)


def seat_price_cents(seat_number) -> int:
    """Price in cents for a single numbered seat.

    Must never raise: a garbage seat number falls back to the base price.
    """
    try:
        n = int(seat_number)
    except (TypeError, ValueError):
        return TICKET_PRICE_CENTS
    for start, end, price in SEAT_TIERS:
        if start <= n <= end:
            return price
    return TICKET_PRICE_CENTS


def ticket_price_cents_for(ticket_count) -> int:
    """Price of the highest-numbered seat in a booking of `ticket_count`.

    This is the marginal price: the price the next seat would add. Used for
    the live total and tier hints. Falls back to the base price on bad input.
    """
    try:
        count = max(1, int(ticket_count))
    except (TypeError, ValueError):
        return TICKET_PRICE_CENTS
    return seat_price_cents(count)


def ticket_price_dollars_for(ticket_count) -> float:
    """Price in dollars of the highest-numbered seat in the booking."""
    return ticket_price_cents_for(ticket_count) / 100


def booking_total_cents(ticket_count) -> int:
    """Total cost in cents for seats 1..`ticket_count`.

    This is the LEGACY/quantity-based pricing path, for bookings that carry
    no explicit seat numbers (a guest who picked a quantity rather than
    individual seats). A seat-picking booking must be priced with
    seats_total_cents() instead — it charges the sum of the SPECIFIC seats
    actually held, which need not be 1..N once seats can be picked
    individually rather than always starting at seat 1.

    Integer cents throughout — the amount a guest is told to Zelle must not
    drift by a rounding error.
    """
    try:
        count = max(0, int(ticket_count))
    except (TypeError, ValueError):
        count = 0
    return sum(seat_price_cents(i) for i in range(1, count + 1))


def booking_total_dollars(ticket_count) -> float:
    """Total cost in dollars for seats 1..`ticket_count`."""
    return booking_total_cents(ticket_count) / 100


def booking_savings_cents(ticket_count) -> int:
    """How much is saved vs paying the base price for every seat."""
    try:
        count = max(0, int(ticket_count))
    except (TypeError, ValueError):
        return 0
    base_total = count * TICKET_PRICE_CENTS
    return base_total - booking_total_cents(count)


def price_tiers() -> list:
    """The seat-price table, ready to display.

    Returns a list of {"min", "max", "price_cents"} dicts covering each
    contiguous seat tier, sorted low-to-high so the rendering order is stable
    even if SEAT_TIERS is ever edited out of order. The Register page renders
    this as the seat-map legend so guests see the price of each seat range.
    """
    return [
        {"min": start, "max": end, "price_cents": price}
        for start, end, price in sorted(SEAT_TIERS)
    ]


def _format_tier_dollars(cents: int) -> str:
    """Whole-dollar formatting for a tier price ("$50"), falling back to
    cents only if the price is not a round dollar amount."""
    dollars = cents / 100
    if dollars == int(dollars):
        return f"${dollars:,.0f}"
    return f"${dollars:,.2f}"


def _tier_range_words(tier: dict) -> str:
    """Plain-text seat-range label for one tier, e.g. "1–25" or "26+"."""
    low, high = tier["min"], tier["max"]
    if high is None:
        return f"{low}+"
    return f"{low}–{high}" if high > low else str(low)


def seat_pricing_summary() -> str:
    """One human-readable sentence describing every seat-price tier.

    Built from price_tiers() (which reads SEAT_TIERS) rather than being
    hand-written, so the Register page's slider help text can never drift
    from the prices guests are actually charged — see the $20/$30 stale-price
    lesson in AGENTS.md for why that guarantee matters.

    e.g. "Seats 1–25 are $50, 26–75 are $25, and 76–100 are $10."
    """
    tiers = price_tiers()
    if not tiers:
        return ""

    clauses = [
        f"{_tier_range_words(tier)} are {_format_tier_dollars(tier['price_cents'])}"
        for tier in tiers
    ]
    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = f"{clauses[0]} and {clauses[1]}"
    else:
        joined = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
    return f"Seats {joined}."


def next_price_tier(ticket_count):
    """The next cheaper seat tier a booking could reach, or None.

    Used to tell someone booking 25 seats that a 26th seat would cost less.
    Returns None when already on the best tier.
    """
    try:
        count = int(ticket_count)
    except (TypeError, ValueError):
        return None

    current_price = seat_price_cents(count)
    for tier in price_tiers():
        if tier["min"] > count and tier["price_cents"] < current_price:
            if tier["min"] > MAX_TICKETS_PER_REGISTRATION:
                return None
            return tier
    return None


# ── Seat inventory ───────────────────────────────────────────────────────────
# Seats are REAL, individually-bookable inventory, cinema style: a guest
# picks specific seat numbers rather than just a quantity, so there must be
# exactly one place that says how many numbered seats actually exist.

# Derived from SEAT_TIERS rather than hardcoded, so raising/lowering the top
# tier's boundary automatically raises/lowers the real seat count everywhere
# that reads TOTAL_SEATS instead of the two having to be kept in sync by hand.
TOTAL_SEATS = max((end for _start, end, _price in SEAT_TIERS), default=0)


def all_seat_numbers() -> list:
    """Return every seat number that exists, in order: [1..TOTAL_SEATS]."""
    return list(range(1, TOTAL_SEATS + 1))


# ── Seat labels (display only) ────────────────────────────────────────────────
# Real auditorium seats are row-lettered (A1, A2, ... B1, ...) — that is what
# a guest expects to be told at the door, not a bare integer 1..100. But no
# public seating chart for the Unity of Dallas sanctuary (~850 seats) shows
# its actual rows/sections, so this does not try to model the real room.
# Instead the map is a CONFIGURABLE rectangle: SEAT_COLS seats per row, with
# as many rows as TOTAL_SEATS needs. This whole section is a DISPLAY layer
# only — the integer seat number remains the stored identity everywhere else
# (Guest.seat_numbers, the DB, logs, the backup export). Nothing here changes
# what gets written to the database.
SEAT_COLS = 10


def seat_row_label(row_index) -> str:
    """0-based seat-map row index -> row letter: 0 -> "A", 25 -> "Z",
    26 -> "AA", 27 -> "AB", ... — the same base-26 scheme spreadsheets use
    for column headers, so the map keeps working if the block is ever made
    larger than 26 rows.

    Must never raise: a negative or non-numeric index clamps to row 0
    ("A") rather than raising, since this only ever feeds a label a human
    reads.
    """
    try:
        n = int(row_index)
    except (TypeError, ValueError):
        n = 0
    n = max(0, n) + 1  # 1-indexed algorithm: A=1, Z=26, AA=27, ...
    letters = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _row_index_for_label(letters: str):
    """Inverse of seat_row_label(): "A" -> 0, "Z" -> 25, "AA" -> 26.

    Returns None for anything that isn't purely A-Z letters (case
    insensitive) — never raises.
    """
    if not letters:
        return None
    n = 0
    for ch in letters.upper():
        if not ("A" <= ch <= "Z"):
            return None
        n = n * 26 + (ord(ch) - 64)
    return n - 1


# Precomputed row letters for the CURRENT seat grid — a convenience list for
# callers that just want "every row letter in order" (e.g. theme.seat_map()'s
# row gutter). seat_label()/seat_from_label() below call seat_row_label()/
# _row_index_for_label() directly rather than indexing into this tuple, so
# they stay correct even if SEAT_COLS or TOTAL_SEATS is patched (e.g. in a
# test) without this tuple being recomputed.
SEAT_ROWS = (TOTAL_SEATS + SEAT_COLS - 1) // SEAT_COLS if SEAT_COLS > 0 else 0
SEAT_ROW_LETTERS = tuple(seat_row_label(i) for i in range(SEAT_ROWS))

_SEAT_LABEL_RE = re.compile(r"^\s*([A-Za-z]+)\s*(\d+)\s*$")


def seat_label(seat_number) -> str:
    """Venue-style seat label for a stored integer seat number.

    e.g. seat_label(1) -> "A1", seat_label(11) -> "B1" (row boundary),
    seat_label(17) -> "B7". Rows are SEAT_COLS seats wide (default 10);
    row letters come from seat_row_label() above.

    This is a DISPLAY-ONLY conversion — the integer remains the stored
    identity (Guest.seat_numbers, the DB). Must never raise: a garbage or
    non-positive input falls back to the plain string form of whatever was
    passed in, so a caller showing this to a human never breaks over a bad
    seat value.
    """
    try:
        n = int(seat_number)
    except (TypeError, ValueError):
        return str(seat_number)
    cols = SEAT_COLS
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        cols = 10
    if n < 1 or cols < 1:
        return str(seat_number)
    row_index, col = divmod(n - 1, cols)
    return f"{seat_row_label(row_index)}{col + 1}"


def seat_from_label(label):
    """Inverse of seat_label(): "B7" -> 17 (for the default SEAT_COLS=10).

    Returns None — never raises — for anything that doesn't parse as
    <letters><digits>, a column outside 1..SEAT_COLS, a row-letter sequence
    that doesn't map to a real row index, or a seat number outside
    1..TOTAL_SEATS.
    """
    try:
        text = str(label).strip()
    except Exception:
        return None
    if not text:
        return None
    match = _SEAT_LABEL_RE.match(text)
    if not match:
        return None
    letters, digits = match.group(1), match.group(2)
    cols = SEAT_COLS
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        cols = 10
    try:
        col = int(digits)
    except (TypeError, ValueError):
        return None
    if cols < 1 or col < 1 or col > cols:
        return None
    row_index = _row_index_for_label(letters)
    if row_index is None or row_index < 0:
        return None
    seat_number = row_index * cols + col
    if seat_number < 1 or seat_number > TOTAL_SEATS:
        return None
    return seat_number


def format_seat_labels(seats) -> str:
    """Comma-joined human seat labels for a list of seat numbers, e.g.
    [17, 3, 4] -> "A3, A4, B7".

    Sorted ascending by the underlying seat NUMBER (not lexicographically by
    label — "A2" would otherwise sort after "A10") and de-duplicated. This
    is the human-facing counterpart to utils.format_seat_numbers() (the
    stored/DB integer form) — every place a guest or door staff reads a seat
    list should go through this rather than hand-rolling the join again.
    Must never raise: a non-iterable input returns "", a non-integer entry
    is silently skipped.
    """
    try:
        candidates = list(seats or [])
    except TypeError:
        return ""
    cleaned = set()
    for s in candidates:
        try:
            cleaned.add(int(s))
        except (TypeError, ValueError):
            continue
    return ", ".join(seat_label(n) for n in sorted(cleaned))


# ── Free kid seats ───────────────────────────────────────────────────────────
# The organiser's rule, verbatim: "kids tickets will be free but only allow
# to select $10 seats only for free.. if they want to sit in front rows then
# they can purchase if needed." So a child under 12 may take a seat for FREE,
# but only from the CHEAPEST SEAT_TIERS entry; a front-row seat for a child
# is simply a normal PAID seat — there is no separate discounted price.
#
# Derived from SEAT_TIERS (never hardcoded as "76-100") so the free-eligible
# range tracks the pricing table if it is ever edited.

def _free_kid_tier():
    """The lowest-priced SEAT_TIERS entry, or None if SEAT_TIERS is empty.

    Recomputed from the CURRENT module-level SEAT_TIERS on every call (unlike
    the FREE_KID_TIER constant below, a one-time snapshot taken at import —
    same relationship TOTAL_SEATS has to a SEAT_TIERS patched later in a
    test). The public functions below all call this, not the snapshot, so a
    live-patched SEAT_TIERS is honoured immediately.
    """
    if not SEAT_TIERS:
        return None
    return min(SEAT_TIERS, key=lambda tier: tier[2])


# Snapshot of the cheapest seat tier at import time, for convenient direct
# access/display. See _free_kid_tier()'s docstring for why the functions
# below recompute rather than read this.
FREE_KID_TIER = _free_kid_tier()


def free_kid_seat_numbers() -> list:
    """Every seat number a FREE child seat may occupy: every seat in the
    cheapest SEAT_TIERS entry. Empty list if SEAT_TIERS is empty."""
    tier = _free_kid_tier()
    if tier is None:
        return []
    start, end, _price = tier
    return list(range(start, end + 1))


def is_free_kid_seat(seat_number) -> bool:
    """True if `seat_number` is one of the free-kid-eligible cheap seats.

    Must never raise: a garbage/non-numeric input returns False, matching
    seat_price_cents()'s defensive style.
    """
    try:
        n = int(seat_number)
    except (TypeError, ValueError):
        return False
    tier = _free_kid_tier()
    if tier is None:
        return False
    start, end, _price = tier
    return start <= n <= end


def free_kid_seat_range_label() -> str:
    """Human, venue-style label for the free-kid-eligible seat range, e.g.
    "H6–J10" (config.seat_label() form) — for UI copy (KIDS_POLICY_TEXT, the
    kid-seat validation error) rather than exposing raw seat-number bounds.
    Empty string if SEAT_TIERS is empty.
    """
    seats = free_kid_seat_numbers()
    if not seats:
        return ""
    return f"{seat_label(seats[0])}–{seat_label(seats[-1])}"


# The organiser's rule in one chip-sized sentence: WHERE a free child seat
# may be taken (named explicitly, not just "the cheapest tier"), and that a
# front-row seat is bought like any other seat. See the FOOD_POLICY_TEXT
# comment above for why this lives here rather than next to it.
KIDS_POLICY_TEXT = (
    f"Kids under 12 ride free — but only in seats {free_kid_seat_range_label()}, "
    "our cheapest tier. A front-row seat for a child is a regular paid seat."
)


def seats_total_cents(seats) -> int:
    """Total price in cents for a specific, possibly non-contiguous set of
    seat numbers, e.g. [1, 30, 80] -> seat_price_cents(1) + seat_price_cents(30)
    + seat_price_cents(80).

    This is what a seat-PICKING booking is actually charged — unlike
    booking_total_cents(), the seats need not be contiguous or start at 1,
    since a guest can now choose any set of open seats (including only the
    cheap ones, e.g. [90, 91, 92]).

    Must never raise: a non-integer or out-of-range entry is silently
    dropped rather than raising or falling back to the base price, on the
    assumption that the seats reaching here were already validated by
    utils.parse_seat_selection() — pricing garbage input would be worse than
    ignoring it. De-duplicates before summing so a seat listed twice is only
    charged once. Integer cents throughout.
    """
    cleaned = set()
    try:
        candidates = list(seats)
    except TypeError:
        return 0
    for seat in candidates:
        try:
            n = int(seat)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= TOTAL_SEATS:
            cleaned.add(n)
    return sum(seat_price_cents(n) for n in cleaned)


def seat_tier_index(seat_number) -> int:
    """Which SEAT_TIERS entry a seat number falls in, or -1 if none.

    Exists so the seat-map's tier -> colour mapping lives here instead of
    being re-derived from SEAT_TIERS's ranges in the UI layer, where it could
    silently drift out of step with a future change to the tiers.
    """
    try:
        n = int(seat_number)
    except (TypeError, ValueError):
        return -1
    for index, (start, end, _price) in enumerate(SEAT_TIERS):
        if start <= n <= end:
            return index
    return -1


# ── Ticket capacity ──────────────────────────────────────────────────────────
# The venue holds a fixed number of people, so unlike the concurrency guard
# below (which only throttles simultaneous *browsing*), this is a real, hard
# cap on how many tickets can ever be sold.

def max_total_tickets() -> int:
    """Hard cap on tickets sold across ALL guests.

    Once this many tickets are registered the Register page shows a sold-out
    screen instead of the form, and utils.register_guest() refuses to write
    past it. Tunable via the MAX_TOTAL_TICKETS secret so the organiser can
    raise or lower the cap without a redeploy.

    The effective cap can never exceed TOTAL_SEATS: seats are now real,
    individually-numbered inventory (see SEAT_TIERS), so there are only
    TOTAL_SEATS physical seats to sell no matter what the secret says — a
    secret above TOTAL_SEATS is clamped down to it. The secret's old
    "0 (or negative) disables the cap entirely" meaning is retired for the
    same reason: with real seat inventory there is no such thing as
    unlimited, since you cannot sell a seat that does not exist. A secret of
    0 or below is therefore also treated as "capped at TOTAL_SEATS" rather
    than uncapped.
    """
    raw = get_secret_int("MAX_TOTAL_TICKETS", 225)
    if raw <= 0:
        return TOTAL_SEATS
    return min(raw, TOTAL_SEATS)


# Most tickets one guest may claim in a single registration. The Register page
# also clamps its selector to whatever is actually left, so the effective
# maximum is min(this, tickets remaining).
#
# The top seat tier ends at 100 (see SEAT_TIERS), so the cap must be at least
# that high or the cheapest seats become unbuyable. Set to 100 to match the
# seat map.
#
# Raising this raises utils.MAX_GUEST_NAMES (this minus one), so a 100-ticket
# booking must name its other 99 guests. utils.GUEST_NAMES_MAX_CHARS — the
# size of the Register form's name box AND of the plus_one_name column — is
# derived from that, so the storage grows with the cap instead of silently
# truncating the tail of a big booking's guest list.
MAX_TICKETS_PER_REGISTRATION = 100


# Most FREE child seats one registration may claim. Reuses
# MAX_TICKETS_PER_REGISTRATION rather than introducing a second constant: a
# kid seat is real seat inventory exactly like a paid one (see
# is_free_kid_seat()), so the same "how many seats can one registration
# claim" ceiling that already governs seat_numbers applies here too — there
# is no reason one registration should be allowed a different number of kid
# seats than paid ones. The actual backstop against one registration
# draining the whole free tier is the tier's own size
# (len(free_kid_seat_numbers()), currently 25) plus live seat availability,
# not a second arbitrary number to keep in sync with this one.
MAX_KIDS_PER_REGISTRATION = MAX_TICKETS_PER_REGISTRATION


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

EVENT_TIMEZONE = "America/Chicago"
EVENT_START_LOCAL = datetime(2026, 10, 3, 18, 0)  # 6:00 PM onwards, matches the printed flyer
CHECKIN_LEAD_HOURS = 2

# Used only if the system tz database is unavailable (see _event_start_local_aware).
# America/Chicago is UTC-5 (CDT) for an October event.
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
