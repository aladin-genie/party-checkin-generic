"""
Party Check-In System — Streamlit App (Mobile-First, v3.0)
Entry point for Streamlit Community Cloud (free hosting).
"""

import time
import traceback
from types import SimpleNamespace

import streamlit as st

startup_error = None
try:
    import base64
    import os
    from datetime import datetime

    import pandas as pd

    import utils
    import config
    import theme
except Exception:
    startup_error = traceback.format_exc()

# ── Page Config ──────────────────────────────────────────────────────────────
# The tab title leads with the performance name (config.PAGE_TITLE, built in
# config.py — see its comment there), not just the org name. Guarded so a
# config import failure (startup_error set above) can't crash this line by
# reaching for a name on a module that never finished importing.
st.set_page_config(
    page_title="Check-In" if startup_error else config.PAGE_TITLE,
    page_icon="🎭",
    layout="centered",  # centered is better for mobile
    initial_sidebar_state="collapsed",  # collapsed by default for mobile
)

if startup_error:
    st.error("🚨 The app failed to start. Please share this error with the developer:")
    st.code(startup_error)
    st.stop()

# CSS first, before anything that might need to render styled HTML below —
# including the outage banner just past the DB-init guard, which would
# otherwise paint as an unstyled raw <div> if it had to fire before any
# stylesheet existed. Cheap and has no DB dependency, so there's no reason
# it should wait behind ensure_db_ready().
theme.inject_css()

# ── Initialize DB ─────────────────────────────────────────────────────────────
# init_db() (via ensure_db_ready(), cached so this only really runs once per
# process) can raise if the configured database is unreachable at boot —
# this used to st.error() + st.code(a raw traceback) + st.stop(), which is
# exactly the kind of crash-page this whole file now exists to avoid. A
# guest opening the link mid-outage doesn't need a stack trace; they need
# the same calm banner every other page shows. The full traceback still
# goes to the server log (print, not st.code) so the organiser can debug it
# from Manage app → Logs. Nothing DB-backed can render this run, so this
# stops the script here rather than falling through to a page that would
# immediately try to read guests anyway.
try:
    utils.ensure_db_ready()
except Exception:
    print(f"utils.ensure_db_ready() failed at boot:\n{traceback.format_exc()}")
    st.markdown(theme.brand_bar(), unsafe_allow_html=True)
    st.markdown(theme.db_unavailable_banner(), unsafe_allow_html=True)
    st.stop()

PAGES = ["Home", "Register", "My QR", "Scanner", "Admin"]

# ── Session State Defaults ───────────────────────────────────────────────────
def _ensure_state(key, default):
    if key not in st.session_state:
        st.session_state[key] = default


_ensure_state("registered_guest_id", None)
# Set on a successful submit; tells page_home() to lead with the guest's
# confirmation card, since registration redirects there rather than
# confirming in place (see _finish_registration).
_ensure_state("just_registered", False)
# Set once page_my_qr()'s email/phone lookup finds a guest, so the guest
# card (and its Resend/Download buttons) survives the rerun a later button
# click on that same card triggers — st.form_submit_button only reports
# True on the one rerun immediately after the form submit itself, so
# without this the lookup result would vanish the instant any button
# inside the card (e.g. "Resend QR Email") was clicked, silently dropping
# that click before it ever reached utils.send_qr_email().
_ensure_state("my_qr_found_guest_id", None)
_ensure_state("confirmation_celebrated", False)
_ensure_state("scanner_result", None)
# The guest a door search pulled up, awaiting staff confirmation. Holding a
# guest here means "found, but nobody has been checked in yet".
_ensure_state("scanner_lookup", None)
_ensure_state("admin_authenticated", False)
_ensure_state("admin_fail_count", 0)
_ensure_state("admin_lockout_until", 0.0)
_ensure_state("reg_errors", {})
_ensure_state("admin_pending_changes", None)
_ensure_state("flash", None)

# ── Constants ──────────────────────────────────────────────────────────────────
# The BASE (individual) price. What a given booking actually pays per ticket
# depends on its size — see config.ticket_price_cents_for() and the group
# discount tiers — so this is only ever the "1 ticket" reference point, never
# the number a group is quoted.
TICKET_PRICE = config.ticket_price_dollars()
ZELLE_INFO = config.zelle_info()


# ── Cached data reads ────────────────────────────────────────────────────────
# Streamlit reruns the whole script on every interaction; without this, every
# click would fire several queries against the remote Postgres DB. Mutations
# clear only the specific cache(s) their write affects (see PART 7) rather
# than st.cache_data.clear(), which would wipe every cached value for every
# user in the whole app.
#
# The four wrappers below also each carry their own try/except returning a
# neutral value. utils.get_stats()/get_site_stats()/
# get_registration_daily_counts()/get_event_day_hourly_checkins() already
# degrade to their documented empty shape internally on a DB failure (never
# raise) — this is deliberate belt-and-suspenders on top of that, since
# these are @st.cache_data functions Streamlit itself wraps: a page must
# never crash here regardless of which layer an unexpected failure surfaces
# at. Display-only; whether a page is ALLOWED to show these numbers as real
# is decided by utils.db_health() at the page level (see main()), not here.
@st.cache_data(ttl=10, show_spinner=False)
def _cached_stats():
    try:
        return utils.get_stats()
    except Exception as e:
        print(f"_cached_stats failed, returning zeros: {e}")
        return {
            "total_guests": 0, "checked_in": 0, "bands_distributed": 0, "pending": 0,
            "total_tickets": 0, "admitted_tickets": 0, "plus_one_count": 0,
            "named_guests": 0, "unnamed_tickets": 0, "avg_tickets_per_guest": 0.0,
            "checkin_percentage": 0.0, "revenue": 0.0,
        }


@st.cache_data(ttl=10, show_spinner=False)
def _cached_site_stats():
    try:
        return utils.get_site_stats()
    except Exception as e:
        print(f"_cached_site_stats failed, returning zeros: {e}")
        return {
            "total_visits": 0, "unique_visitors": 0, "today_visits": 0,
            "today_unique": 0, "total_regs": 0, "today_regs": 0,
        }


@st.cache_data(ttl=10, show_spinner=False)
def _cached_availability():
    """Ticket-capacity picture for the UI (see utils.ticket_availability()).

    Display only, and up to 10s stale — the number that actually decides
    whether a registration is accepted is re-read inside the transaction by
    utils.register_guest(), so a guest who submits just as the last ticket
    goes is refused there rather than oversold.
    """
    return utils.ticket_availability()


@st.cache_data(ttl=10, show_spinner=False)
def _cached_seat_availability():
    """Seat-inventory picture for the UI (see utils.seat_availability()).

    Display only, and up to 10s stale — the number that actually decides
    whether a registration is accepted is re-read inside the transaction by
    utils.register_guest(), so a guest who submits just as a seat goes is
    refused there rather than double-booked.
    """
    return utils.seat_availability()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_registration_daily_counts():
    try:
        return utils.get_registration_daily_counts()
    except Exception as e:
        print(f"_cached_registration_daily_counts failed, returning an empty list: {e}")
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _cached_event_day_hourly_checkins():
    try:
        return utils.get_event_day_hourly_checkins()
    except Exception as e:
        print(f"_cached_event_day_hourly_checkins failed, returning zeros: {e}")
        return [0] * 24


@st.cache_data(ttl=3600, show_spinner=False, max_entries=500)
def _cached_qr_image(qr_code: str) -> bytes:
    """Cached QR PNG rendering (27ms of pure CPU per call, uncached).

    st.cache_data is process-global, so once any guest's QR has been
    rendered once, every later viewer of the SAME code (a re-render, a
    second device, the download button right after the image) costs
    nothing — no re-encoding on a shared vCPU under a viewing burst.
    utils.generate_qr_image() itself stays uncached and unchanged: the
    email-sending path calls it directly from a background thread, where
    Streamlit's cache isn't relevant and a per-guest one-time cost is fine.
    """
    return utils.generate_qr_image(qr_code)


def _db_ok() -> bool:
    """Is the guest database reachable? True when we can't tell.

    Wrapped in getattr rather than calling utils.db_health() directly, for
    the reason AGENTS.md spells out: Streamlit Cloud can execute a freshly
    deployed streamlit_app.py against a `utils` module still cached in the
    running process from BEFORE that deploy. The new page code then calls an
    attribute the old module doesn't have and every single page load dies
    with AttributeError — a total outage caused by a health check whose only
    job was to prevent an outage. That is exactly what happened on the deploy
    that introduced db_health(), and it is why _safe_active_count() below
    guards touch_session/active_session_count the same way.

    Fails OPEN (returns True) on any problem: if the probe itself is
    unavailable we must keep serving the app and let the individual service
    calls degrade on their own, never blanket-block every page.
    """
    try:
        probe = getattr(utils, "db_health", None)
        if probe is None:
            return True
        return bool(probe().get("ok", True))
    except Exception as e:  # pragma: no cover - defensive
        print(f"db health probe unavailable, assuming reachable: {e}")
        return True


def _db_health_detail() -> str:
    """Short error string from the health probe, or "" if unavailable."""
    try:
        probe = getattr(utils, "db_health", None)
        return str(probe().get("error", "")) if probe else ""
    except Exception:
        return ""


def _safe_active_count(register: bool = True) -> int:
    """Active-session count, or 0 if it can't be determined.

    The capacity guard is an optional protection, so every path into it is
    guarded: if it raises for any reason the app must keep serving guests
    rather than 500-ing. Returning 0 means "load unknown", which leaves
    everyone ungated — failing open is correct here, because the failure
    mode of gating wrongly (turning away real guests) is worse than the
    failure mode of not gating (a slow page).
    """
    try:
        if register:
            token = st.session_state.get("visitor_token")
            if token and hasattr(utils, "touch_session"):
                return int(utils.touch_session(token))
        if hasattr(utils, "active_session_count"):
            return int(utils.active_session_count())
    except Exception as e:  # pragma: no cover - defensive
        print(f"capacity guard unavailable, continuing ungated: {e}")
    return 0


def _fmt_checkin_iso(iso_str, fmt="%I:%M %p"):
    """Format an ISO-string checkin_time (as returned by Guest.to_dict()) as
    LOCAL event time.

    utils.format_event_local_dt() expects a real datetime, not the ISO
    string that dict payloads carry, so this parses it back first (the
    string is naive UTC, same as the stored column — see _utc_now()).
    Tolerates None/garbage.
    """
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
    except Exception:
        return "—"
    return utils.format_event_local_dt(dt, fmt)


# ── Flash messages ────────────────────────────────────────────────────────────
# st.success/st.warning/st.error/st.info render into the CURRENT script frame.
# Several actions in this app do a mutation and then call st.rerun() right
# away so the page reflects the new state — but that discards the current
# frame before the browser ever paints it, so a message shown immediately
# before st.rerun() is never actually seen (see PART 6). Any such call site
# should stash its message with _set_flash() instead and let the top of the
# *next* run display it via _render_flash().
def _set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = {"kind": kind, "message": message}


def _render_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        renderer = {
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "info": st.info,
        }.get(flash["kind"], st.info)
        renderer(flash["message"])


def _render_bar_chart(df):
    """st.bar_chart, falling back to a plain table if chart rendering fails.

    Some environments ship an altair build that's incompatible with the
    running Python's `typing.TypedDict` (unrelated to this app's code) and
    raise on any st.bar_chart call. Never let that take down the whole
    page — degrade to a table instead.

    Charts are drawn in the theme's gold rather than Streamlit's default blue,
    which clashes badly with the dark/gold palette, and are given a fixed
    height so a 24-bar check-in chart doesn't swallow the whole viewport.
    """
    try:
        st.bar_chart(df, color=theme.CHART_COLOR, height=260, use_container_width=True)
    except TypeError:
        # Older/newer Streamlit signatures may not accept color/height.
        try:
            st.bar_chart(df, use_container_width=True)
        except Exception:
            st.dataframe(df, use_container_width=True)
    except Exception:
        st.dataframe(df, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# HOME PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def page_home():
    # Registration is the landing page (config.LANDING_PAGE), and submitting
    # it redirects here — so the confirmation travels with the guest and is
    # the first thing on the page, above even the hero. Without that, a
    # submit would look like it did nothing but move them somewhere else.
    if st.session_state.get("just_registered"):
        _render_registration_confirmation()

    st.markdown(theme.hero(), unsafe_allow_html=True)

    # Warn if running on fallback SQLite (e.g., Cloud secret missing or DB unreachable)
    try:
        if utils._using_fallback_db():
            st.warning(
                "Running on a temporary local database. Guest data will not persist across restarts. "
                "Please set the DATABASE_URL secret in Streamlit Cloud to connect to Supabase.",
                icon="🗄️",
            )
    except Exception:
        pass

    # ── The flyer ───────────────────────────────────────────────────────────
    # The centrepiece of Home, not an afterthought between the hero and the
    # photo grid: a taller height cap, a gold-glow frame to match, and a
    # caption tying it back to the event. Still renders nothing until the
    # artwork exists at config.EVENT_FLYER (flyer_card() drops the caption
    # right along with everything else for a blank src).
    st.markdown(
        theme.flyer_card(
            utils.event_flyer_src(),
            caption=f"{config.EVENT_SUBTITLE} · {config.EVENT_DATE_SHORT}",
        ),
        unsafe_allow_html=True,
    )

    # ── Photos & sponsors ───────────────────────────────────────────────────
    # Ahead of Community Buzz on purpose: a guest arriving here straight off
    # the registration form came to see the event, not the analytics.
    _home_photos_section()
    _home_sponsors_section()

    # ── Community Buzz ──────────────────────────────────────────────────────
    # Public, aggregate-only site activity — no guest names/emails/phones/
    # Zelle refs ever appear here. Moved from the admin dashboard: the owner
    # doesn't consider it sensitive and would rather show it off than bury it.
    st.markdown(
        theme.section_header(
            "🔔 Community Buzz", "A live pulse of interest in the evening so far — nothing guest-specific."
        ),
        unsafe_allow_html=True,
    )

    if not _db_ok():
        # Every number in this section is a live DB read. Showing them as
        # zeros here (the shape they'd degrade to) would read exactly like
        # "nobody's registered" — false, and the opposite of reassuring
        # during an outage. The top-of-page banner (see main()) already
        # explains what's going on; skip the section entirely rather than
        # dress up "we don't know" as "The buzz starts here".
        st.markdown(
            theme.empty_state(
                "🔌", "Stats temporarily unavailable",
                "We can't reach the guest database right now, so live numbers are paused. "
                "Check back in a few minutes.",
            ),
            unsafe_allow_html=True,
        )
    else:
        site_stats = _cached_site_stats()
        if site_stats["total_visits"] == 0 and site_stats["total_regs"] == 0:
            st.markdown(
                theme.empty_state(
                    "🌱", "The buzz starts here",
                    "Nobody's visited yet — traffic and registration numbers will start moving "
                    "the moment the first guest opens this site.",
                ),
                unsafe_allow_html=True,
            )
        else:
            # Just one number of pure site traffic (Registered Guests) used to
            # sit awkwardly alone in a 4-up grid after the three raw-traffic
            # tiles (Unique Visitors / Page Views / Visitors Today) were dropped
            # as not guest-relevant. Paired here with seats remaining — the
            # other number that actually matters to a guest deciding whether to
            # register — both given "hero" emphasis so they read as a
            # deliberate two-up row rather than one stranded tile plus empty
            # space. Mirrors the admin dashboard's own hero-tile pairing
            # (Checked In / Total Guests).
            seat_avail = _cached_seat_availability()
            # A DB blip must not paint "0 of N" here — that reads exactly like
            # the event being full. Show a dash instead when we genuinely don't
            # know (see utils.seat_availability()'s unavailable flag).
            if seat_avail["unavailable"]:
                seats_value, seats_caption = "—", "temporarily unavailable"
            else:
                seats_value = seat_avail["remaining"]
                seats_caption = f"of {seat_avail['total']} total"
            st.markdown(
                theme.stat_tiles(
                    [
                        {
                            "label": "Registered Guests", "value": site_stats["total_regs"],
                            "caption": f"+{site_stats['today_regs']} today", "icon": "📝",
                            "accent": "gold", "emphasis": "hero",
                        },
                        {
                            "label": "Seats Remaining", "value": seats_value,
                            "caption": seats_caption, "icon": "💺",
                            "accent": "turquoise", "emphasis": "hero",
                        },
                    ]
                ),
                unsafe_allow_html=True,
            )

        daily_counts = _cached_registration_daily_counts()
        if daily_counts:
            reg_df = pd.DataFrame(
                {"Registrations": [c for _, c in daily_counts]},
                index=[d.strftime("%b %d") for d, _ in daily_counts],
            )
            st.caption("📈 Registrations by day — how quickly folks have been signing up.")
            _render_bar_chart(reg_df)
        else:
            st.info("No registrations yet — be the first to sign up!")

        hourly = _cached_event_day_hourly_checkins()
        if any(hourly):
            checkin_df = pd.DataFrame(
                {"Check-ins": hourly},
                index=[f"{h:02d}:00" for h in range(24)],
            )
            st.caption(f"🚪 Check-ins by hour on {config.EVENT_DATE_SHORT} — the flow through the door.")
            _render_bar_chart(checkin_df)
        else:
            st.info(f"Check-ins will show up here live once doors open on {config.EVENT_DATE_SHORT}.")

    st.markdown(theme.section_header("Get Started"), unsafe_allow_html=True)

    # Navigation cards
    nav_items = [
        ("📝", "Register Guest", "Pay via Zelle, get your QR code by email", "nav_register", "Register"),
        ("📱", "My QR Code", "Look up your ticket QR code by email or phone", "nav_my_qr", "My QR"),
        ("📷", "Self Check-In", "Scan your QR code at the entrance", "nav_scanner", "Scanner"),
        ("📊", "Admin Dashboard", "Manage guests and download reports", "nav_admin", "Admin"),
    ]
    for icon, title, desc, key, page in nav_items:
        with st.container(border=True):
            st.markdown(theme.nav_card(icon, title, desc), unsafe_allow_html=True)
            if st.button(f"{icon} {title} →", key=key, use_container_width=True):
                st.session_state["page"] = page
                _sync_page_query_param(page)
                st.rerun()

    st.markdown(theme.footer(), unsafe_allow_html=True)


def _home_photos_section() -> None:
    """The Home page photo gallery, or a placeholder while it's still empty.

    Photos are configured in config.PHOTOS and are expected to stay empty
    for a while, so the empty state has to read as "not yet", not "broken".
    """
    st.markdown(
        theme.section_header("📸 Photos", "Moments from the stage and the years before it."),
        unsafe_allow_html=True,
    )
    photos = utils.gallery_photos()
    if photos:
        st.markdown(theme.photo_gallery(photos), unsafe_allow_html=True)
    else:
        st.markdown(
            theme.empty_state(
                "📷", "Photos are on the way",
                "We're still picking the best shots from previous years. Check back soon — "
                "and the night itself will fill this up too.",
            ),
            unsafe_allow_html=True,
        )


def _home_sponsors_section() -> None:
    """The Home page sponsor wall, or a placeholder while it's still empty.

    Same shape as _home_photos_section(): reads config.SPONSORS, and says
    "being finalised" rather than showing nothing, since an empty section
    on a page a sponsor might be sent to looks worse than an honest one.
    """
    st.markdown(
        theme.section_header("🤝 Our Sponsors", "The people helping make this night happen."),
        unsafe_allow_html=True,
    )
    sponsors = utils.sponsor_list()
    if sponsors:
        st.markdown(theme.sponsor_wall(sponsors), unsafe_allow_html=True)
    else:
        st.markdown(
            theme.empty_state(
                "🤝", "Sponsor lineup coming soon",
                "We're still confirming this year's sponsors. Want to support this evening? "
                "Get in touch with the organisers.",
            ),
            unsafe_allow_html=True,
        )


def _render_registration_confirmation() -> None:
    """The post-registration confirmation, rendered at the top of Home.

    The guest is redirected here by page_register() on a successful submit
    (see _finish_registration), so this is where they learn it worked. It
    stays put for the rest of the session until they dismiss it or register
    someone else, so navigating away and back doesn't lose their receipt.
    """
    guest_id = st.session_state.get("registered_guest_id")
    guest = utils.get_guest(guest_id) if guest_id else None
    if not guest:
        # The row is gone — an admin deleted it, or the data was reset.
        # Drop the banner rather than confirm a booking that no longer
        # exists; the rest of Home renders normally underneath.
        _clear_registration_confirmation()
        return

    # Once per registration, not once per rerun: any button press on Home
    # re-runs the whole script, and re-firing the animation on every click
    # is grating rather than celebratory.
    if not st.session_state.get("confirmation_celebrated"):
        st.balloons()
        st.session_state["confirmation_celebrated"] = True

    st.markdown(theme.stepper(3), unsafe_allow_html=True)
    st.markdown(
        theme.registration_confirmation(
            guest["name"],
            guest["email"],
            guest["ticket_count"],
            utils.guest_names_list(guest.get("plus_one_name")),
            guest.get("seats", []),
            kid_seat_numbers=guest.get("kid_seats", []),
        ),
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📧 Resend QR Email", key="confirm_resend", use_container_width=True):
            with st.spinner("Emailing your QR code…"):
                sent = utils.send_qr_email(SimpleNamespace(**guest))
            if sent:
                st.success("QR code emailed again!")
            else:
                st.warning(
                    "We couldn't send the email right now (SMTP may be disabled in this environment). "
                    "Please try again later or contact the organizer."
                )
    with col2:
        if st.button("🔄 Register Someone Else", key="confirm_register_another", use_container_width=True):
            _clear_registration_confirmation()
            st.session_state["reset_register_form"] = True
            st.session_state["page"] = "Register"
            _sync_page_query_param("Register")
            st.rerun()


def _clear_registration_confirmation() -> None:
    """Forget the just-registered guest so Home stops showing their receipt."""
    st.session_state["just_registered"] = False
    st.session_state["confirmation_celebrated"] = False
    st.session_state["registered_guest_id"] = None


def _sync_page_query_param(page: str) -> None:
    """Keep ?page= in step with a programmatic navigation.

    Best-effort: st.query_params is unavailable in some embedding contexts,
    and a URL that lags the real page is cosmetic — never a reason to break
    the navigation itself.
    """
    try:
        st.query_params["page"] = page
    except Exception:
        pass


def _home_button(key="home_button"):
    """Render a Home button that returns to the Home page."""
    if st.button("🏠 Home", key=key, use_container_width=True):
        st.session_state["page"] = "Home"
        _sync_page_query_param("Home")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTER PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def page_register():
    # Reset form fields at the very top, before any widgets are instantiated,
    # so stale values don't appear when re-entering the page or clicking "Register Another".
    if st.session_state.get("reset_register_form"):
        for _key in ("reg_name", "reg_email", "reg_phone", "reg_plus_one", "reg_zelle", "ticket_count",
                     "selected_seats", "selected_kid_seats"):
            st.session_state.pop(_key, None)
        st.session_state["reg_agree"] = False
        st.session_state["reg_errors"] = {}
        st.session_state["reset_register_form"] = False

    # Seed the phone field with the country code the mask maintains, so the
    # guest sees the shape they're expected to fill in. Must happen before the
    # widget below is instantiated. validate_registration() treats a bare
    # "+1-" as "not filled in" rather than as an invalid number.
    st.session_state.setdefault("reg_phone", utils.US_PHONE_PREFIX)

    header_col1, header_col2 = st.columns([4, 1])
    with header_col1:
        st.title("📝 Register Guest")
    with header_col2:
        _home_button(key="home_register")

    # ── Seat inventory ──────────────────────────────────────────────────────
    # Checked before anything else on the page: there's no point walking a
    # guest through Zelle instructions for a party that's full. Seats are the
    # real, individually-numbered inventory now (see config.SEAT_TIERS), so
    # this is the authoritative "is there anything left to sell" read.
    seat_avail = _cached_seat_availability()
    if seat_avail["unavailable"]:
        # The DB read behind seat inventory failed — we genuinely don't know
        # which seats are free. Must be checked BEFORE sold_out: on this
        # failure seat_avail["sold_out"] is deliberately False (see
        # utils.seat_availability()), but there's still nothing safe to sell
        # here, so don't fall through to the seat picker/form either.
        st.markdown(theme.stepper(1), unsafe_allow_html=True)
        st.markdown(theme.seats_unavailable_notice(), unsafe_allow_html=True)
        _home_button(key="home_seats_unavailable")
        return
    if seat_avail["sold_out"]:
        st.markdown(theme.stepper(1), unsafe_allow_html=True)
        st.markdown(theme.sold_out_notice(utils.SOLD_OUT_MESSAGE), unsafe_allow_html=True)
        _home_button(key="home_sold_out")
        return

    # Step 1, not step 2: this is where the flow begins now that Register is
    # the landing page, and paying via Zelle — the card directly below — is
    # the first thing a guest actually does. Marking step 1 as already
    # complete on arrival told a first-time visitor they had missed
    # something.
    st.markdown(theme.stepper(1), unsafe_allow_html=True)
    # Date, venue, and the dress theme, restated here because Register is the
    # landing page — a guest arriving from the flyer may never see Home's hero.
    st.markdown(theme.event_strip(), unsafe_allow_html=True)

    # The event flyer, collapsed so it doesn't push the form below the fold.
    flyer_src = utils.event_flyer_src()
    if flyer_src:
        with st.expander("📜 View event flyer", expanded=False):
            st.markdown(theme.flyer_card(flyer_src), unsafe_allow_html=True)

    # ── Seat selection ──────────────────────────────────────────────────────
    # A value sitting in session_state that is no longer in `options` makes
    # st.multiselect raise. Seats can be sold by another guest while this
    # page is open, so any seat that's since gone must be pruned OUT of the
    # guest's selection before the widget below is instantiated — the same
    # defensive pattern the old ticket_count slider used for clamping.
    available_seats = seat_avail["available"]
    still_available = set(available_seats)
    previously_selected = list(st.session_state.get("selected_seats", []))
    pruned = sorted(s for s in previously_selected if s not in still_available)
    if pruned:
        st.session_state["selected_seats"] = [s for s in previously_selected if s in still_available]
        # Label, not the raw stored integer: the guest picked "B3" and the
        # seat map says "B3", so telling them "Seat 13 was just booked" reads
        # as a different seat entirely.
        pruned_label = config.format_seat_labels(pruned)
        st.warning(
            f"Seat{'s' if len(pruned) != 1 else ''} {pruned_label} "
            f"{'were' if len(pruned) != 1 else 'was'} just booked by someone else and "
            "removed from your selection — please pick again."
        )

    max_tickets = config.MAX_TICKETS_PER_REGISTRATION
    # Defensive clamp, mirroring the prune above: nothing in this file should
    # be able to push more than max_tickets seats into session_state, but if
    # it ever did, trim rather than let the widget raise.
    current_selection = list(st.session_state.get("selected_seats", []))
    if len(current_selection) > max_tickets:
        st.session_state["selected_seats"] = current_selection[:max_tickets]
    st.session_state.setdefault("selected_seats", [])

    # Read once, early, so both the paid- and kid-seat error rendering below
    # (each next to its own picker) can use it without re-reading session
    # state or duplicating the fetch.
    reg_errors = st.session_state.get("reg_errors", {})

    # ── Zelle Payment Info Card ────────────────────────────────────────────
    # Has to render BEFORE the seat picker (that's where Step 1 belongs on
    # the page), so it reads session_state for the current pick instead of
    # the widget's return value further down — same seats, just available
    # earlier in the script.
    selected_so_far = st.session_state.get("selected_seats", [])
    st.markdown(
        theme.payment_card(
            ZELLE_INFO,
            config.price_tiers(),
            len(selected_so_far),
            total_cents=config.seats_total_cents(selected_so_far),
        ),
        unsafe_allow_html=True,
    )

    st.markdown(theme.section_header("Select Seats"), unsafe_allow_html=True)
    # Two facts a guest choosing seats must not miss (kids free, food at the
    # venue) — their own scannable chips right at the top of the seat
    # selection area, not just buried in payment_card()'s prose above.
    st.markdown(theme.seat_policy_chips(), unsafe_allow_html=True)
    st.markdown(theme.venue_info_card(), unsafe_allow_html=True)

    # Convenience fillers — picking dozens of seats one at a time is
    # miserable. Each mutates selected_seats directly and reruns so the
    # multiselect below reflects the new pick immediately.
    def _seats_by_position(n):
        return sorted(available_seats)[:n]

    def _seats_by_price(n):
        return sorted(available_seats, key=lambda s: (config.seat_price_cents(s), s))[:n]

    fill_cols = st.columns(5)
    with fill_cols[0]:
        if st.button("Best available ×2", use_container_width=True, key="fill_best_2"):
            st.session_state["selected_seats"] = _seats_by_position(min(2, max_tickets))
            st.rerun()
    with fill_cols[1]:
        if st.button("Best available ×4", use_container_width=True, key="fill_best_4"):
            st.session_state["selected_seats"] = _seats_by_position(min(4, max_tickets))
            st.rerun()
    with fill_cols[2]:
        if st.button("Cheapest ×2", use_container_width=True, key="fill_cheap_2"):
            st.session_state["selected_seats"] = _seats_by_price(min(2, max_tickets))
            st.rerun()
    with fill_cols[3]:
        if st.button("Cheapest ×4", use_container_width=True, key="fill_cheap_4"):
            st.session_state["selected_seats"] = _seats_by_price(min(4, max_tickets))
            st.rerun()
    with fill_cols[4]:
        if st.button("Clear", use_container_width=True, key="fill_clear"):
            st.session_state["selected_seats"] = []
            st.rerun()

    # `options` is the available seats plus whatever the guest already has
    # selected, so their own picks can never vanish from the list even if
    # this ever runs a beat behind the prune above.
    option_seats = sorted(still_available | set(st.session_state.get("selected_seats", [])))

    def _seat_option_label(seat):
        return f"{config.seat_label(seat)} · ${config.seat_price_cents(seat) / 100:,.0f}"

    selected_seats = st.multiselect(
        "Select Seats *",
        options=option_seats,
        format_func=_seat_option_label,
        key="selected_seats",
        max_selections=max_tickets,
        help=f"Pick your seats (up to {max_tickets}) — one per person age 12+. "
             f"{config.seat_pricing_summary()} Kids under 12 are free. "
             "The total updates automatically as you pick.",
    )
    if "seat_numbers" in reg_errors:
        st.markdown(theme.field_error(reg_errors["seat_numbers"]), unsafe_allow_html=True)

    # ── Free child seat selection ───────────────────────────────────────────
    # Same stale-value hazard as the paid picker above — a seat can be sold
    # to someone else, or picked as a paid seat on this very booking, while
    # this page is open — so anything no longer eligible must be pruned OUT
    # of session_state["selected_kid_seats"] BEFORE the widget below is
    # instantiated, or Streamlit raises. Copies the paid-seat prune pattern
    # above exactly.
    kid_eligible = set(config.free_kid_seat_numbers()) & still_available
    kid_available = kid_eligible - set(selected_seats)

    previously_selected_kids = list(st.session_state.get("selected_kid_seats", []))
    pruned_kids = sorted(s for s in previously_selected_kids if s not in kid_available)
    if pruned_kids:
        st.session_state["selected_kid_seats"] = [
            s for s in previously_selected_kids if s in kid_available
        ]
        pruned_kids_label = config.format_seat_labels(pruned_kids)
        st.warning(
            f"Free child seat{'s' if len(pruned_kids) != 1 else ''} {pruned_kids_label} "
            f"{'are' if len(pruned_kids) != 1 else 'is'} no longer available — removed from "
            "your selection, please pick again."
        )

    max_kids = config.MAX_KIDS_PER_REGISTRATION
    current_kid_selection = list(st.session_state.get("selected_kid_seats", []))
    if len(current_kid_selection) > max_kids:
        st.session_state["selected_kid_seats"] = current_kid_selection[:max_kids]
    st.session_state.setdefault("selected_kid_seats", [])

    # `options` mirrors option_seats above: available free-tier seats plus
    # whatever the guest already has picked, so their own pick can never
    # vanish even if this ever runs a beat behind the prune above.
    kid_option_seats = sorted(kid_available | set(st.session_state.get("selected_kid_seats", [])))

    def _kid_seat_option_label(seat):
        return f"{config.seat_label(seat)} · Free"

    selected_kid_seats = st.multiselect(
        f"Free Child Seats — under 12, {config.free_kid_seat_range_label()} only",
        options=kid_option_seats,
        format_func=_kid_seat_option_label,
        key="selected_kid_seats",
        max_selections=max_kids,
        help=config.KIDS_POLICY_TEXT,
    )
    if "kid_seat_numbers" in reg_errors:
        st.markdown(theme.field_error(reg_errors["kid_seat_numbers"]), unsafe_allow_html=True)

    # Cinema-style visual map so guests see exactly which seats cost what,
    # which are already taken, and which ones are theirs (paid or kid).
    st.markdown(
        theme.seat_map(selected_seats, seat_avail["taken"], kid_selected=selected_kid_seats),
        unsafe_allow_html=True,
    )
    st.markdown(theme.seat_breakdown(selected_seats), unsafe_allow_html=True)

    ticket_count = len(selected_seats)
    total_cents = config.seats_total_cents(selected_seats)

    # The exact amount the guest is about to Zelle — kid seats are always
    # $0 and never enter total_cents (see config.seats_total_cents, which is
    # PAID-seats only).
    st.markdown(
        theme.total_card(ticket_count, total_cents, kid_seats=selected_kid_seats),
        unsafe_allow_html=True,
    )

    if ticket_count == 0:
        if selected_kid_seats:
            st.info(
                "👆 A child can't book alone — pick at least one paid seat above to go with "
                "the free child seat you selected."
            )
        else:
            st.info("👆 Pick at least one seat to continue — a booking needs at least one seat.")

    # How many other people this booking has to name, stated before the field
    # rather than after a rejected submit. Lives outside the form alongside
    # the selector, so changing the ticket count updates it immediately —
    # utils.validate_registration enforces exactly this count.
    names_required = utils.additional_guests_expected(ticket_count)
    st.markdown(
        theme.guest_names_requirement(
            ticket_count,
            utils.count_guest_name_entries(st.session_state.get("reg_plus_one", "")),
        ),
        unsafe_allow_html=True,
    )

    # ── Registration Details ───────────────────────────────────────────────
    st.markdown(theme.section_header("Step 2: Fill Your Details"), unsafe_allow_html=True)

    if reg_errors:
        st.markdown(theme.validation_banner(len(reg_errors)), unsafe_allow_html=True)

    # Use a form for personal details so typing in these fields doesn't trigger a
    # Streamlit rerun on every keystroke. The ticket selector stays outside the
    # form so its total updates live.
    with st.form("registration_form"):
        name = st.text_input(
            "Full Name *",
            key="reg_name",
            placeholder="Enter your full name (letters only)",
            max_chars=utils.MAX_NAME_LENGTH,
            help="Use letters and spaces only. Example: John Smith or Mary Jane",
        )
        if "name" in reg_errors:
            st.markdown(theme.field_error(reg_errors["name"]), unsafe_allow_html=True)

        email = st.text_input(
            "Email Address *",
            key="reg_email",
            placeholder="your@email.com",
            max_chars=120,
        )
        if "email" in reg_errors:
            st.markdown(theme.field_error(reg_errors["email"]), unsafe_allow_html=True)

        phone = st.text_input(
            "Phone Number *",
            key="reg_phone",
            placeholder="+1-XXX-XXX-XXXX",
            max_chars=20,
            help="US numbers only. Just type the 10 digits — the +1-XXX-XXX-XXXX formatting is applied as you go. "
                 "We use this to find your ticket at the door if there's any trouble with your email.",
        )
        if "phone" in reg_errors:
            st.markdown(theme.field_error(reg_errors["phone"]), unsafe_allow_html=True)

        # Label and help both restate the required count, because this is
        # the one field whose correctness depends on a control that sits
        # outside the form (the ticket selector above). Changing that
        # selector reruns the script, so this label re-renders with it.
        if names_required:
            names_label = (
                f"Additional Guest Names — {names_required} "
                f"{'name' if names_required == 1 else 'names'} required *"
            )
            names_help = (
                f"One name per line (or comma-separated). You booked {ticket_count} tickets, "
                f"so we need the {names_required} other "
                f"{'guest' if names_required == 1 else 'guests'} by name — letters and spaces only."
            )
        else:
            names_label = "Additional Guest Names — not needed for 1 ticket"
            names_help = (
                "Only for bookings of 2 or more. Everyone attending needs their own ticket, "
                "so add a ticket above for each extra person and their name here."
            )

        plus_one_name = st.text_area(
            names_label,
            key="reg_plus_one",
            placeholder="Jane Doe\nJohn Doe\nMary Smith",
            help=names_help,
            height=120,
            # Sized to hold a full-capacity booking's guest list — every name
            # at its maximum length. A fixed 1000 silently cut the tail off a
            # large group once the ticket cap was raised.
            max_chars=utils.GUEST_NAMES_MAX_CHARS,
        )
        if "plus_one_name" in reg_errors:
            st.markdown(theme.field_error(reg_errors["plus_one_name"]), unsafe_allow_html=True)

        zelle_ref = st.text_input(
            "Zelle Transaction Reference *",
            key="reg_zelle",
            placeholder="e.g. ZELLE12345678",
            max_chars=30,
            help="8-30 letters, digits, or hyphens. Examples: ZELLE12345678, TXN-ABCD1234, 1234567890",
        )
        if "zelle_ref" in reg_errors:
            st.markdown(theme.field_error(reg_errors["zelle_ref"]), unsafe_allow_html=True)

        # ── Terms & Conditions ──────────────────────────────────────────────
        # Auto-expand when the previous submit failed on this field — otherwise
        # a user who submits without ticking "I/We Agree" sees the form get
        # rejected with no visible reason, since the error renders inside this
        # (default-collapsed) expander.
        with st.expander(
            "📜 Terms & Conditions — Participation Waiver",
            expanded=("terms" in reg_errors),
        ):
            st.markdown(theme.terms_and_conditions_html(), unsafe_allow_html=True)
            agree_terms = st.checkbox("I/We Agree", key="reg_agree")
            if "terms" in reg_errors:
                st.markdown(theme.field_error(reg_errors["terms"]), unsafe_allow_html=True)

        submitted = st.form_submit_button(
            "🎟️ Get My QR Code", type="primary", use_container_width=True,
            disabled=(ticket_count == 0),
        )

    # Live +1-XXX-XXX-XXXX formatting for the phone field above. Cosmetic
    # only — validate_registration/sanitize_phone still decide what is
    # accepted, so nothing breaks if this never runs (see the docstring).
    st.components.v1.html(utils.phone_input_mask_js("Phone Number *"), height=0)

    st.markdown(
        "<small style='opacity:0.6'>* Required fields. By registering, you agree to the Terms & Conditions. "
        "Your QR code will be emailed to you.</small>",
        unsafe_allow_html=True,
    )

    if submitted:
        cleaned, errors = utils.validate_registration(
            name, email, phone, plus_one_name, zelle_ref, agree_terms,
            ticket_count=ticket_count,
            seat_numbers=selected_seats,
            kid_seat_numbers=selected_kid_seats,
        )

        if errors:
            st.session_state["reg_errors"] = errors
            utils.record_submission(
                name=cleaned["name"] or name,
                email=cleaned["email"] or email,
                phone=cleaned["phone"] or phone,
                ticket_count=ticket_count,
                plus_one_name=cleaned["plus_one_name"] or plus_one_name,
                zelle_ref=cleaned["zelle_ref"] or zelle_ref,
                status="validation_error",
                errors="; ".join(errors.values()),
                seat_numbers=cleaned["seat_numbers_str"],
                kid_seat_numbers=cleaned["kid_seat_numbers_str"],
            )
            st.rerun()

        st.session_state["reg_errors"] = {}
        result = utils.register_guest(
            cleaned["name"],
            cleaned["email"],
            cleaned["phone"],
            cleaned["ticket_count"],
            cleaned["plus_one_name"],
            cleaned["zelle_ref"],
            seat_numbers=cleaned["seat_numbers"],
            kid_seat_numbers=cleaned["kid_seat_numbers"],
        )

        if result["ok"]:
            guest = result["guest"]
            # Fire-and-forget: a guest who just paid shouldn't stare at a
            # spinner for a full SMTP round-trip. The confirmation card on
            # Home reflects this honestly — it says the email is "on its
            # way", not that it was delivered (see PART 1).
            utils.send_qr_email_async(guest)
            utils.record_submission(
                name=cleaned["name"],
                email=cleaned["email"],
                phone=cleaned["phone"],
                ticket_count=ticket_count,
                plus_one_name=cleaned["plus_one_name"],
                zelle_ref=cleaned["zelle_ref"],
                status="registered",
                guest_id=guest["id"],
                seat_numbers=cleaned["seat_numbers_str"],
                kid_seat_numbers=cleaned["kid_seat_numbers_str"],
            )
            _cached_stats.clear()
            _cached_site_stats.clear()
            _cached_registration_daily_counts.clear()
            _cached_availability.clear()
            _cached_seat_availability.clear()
            _finish_registration(guest["id"])
        else:
            reason = result["reason"]
            utils.record_submission(
                name=cleaned["name"],
                email=cleaned["email"],
                phone=cleaned["phone"],
                ticket_count=ticket_count,
                plus_one_name=cleaned["plus_one_name"],
                zelle_ref=cleaned["zelle_ref"],
                status=reason,
                errors=result["message"],
                seat_numbers=cleaned["seat_numbers_str"],
                kid_seat_numbers=cleaned["kid_seat_numbers_str"],
            )
            if reason == "duplicate_email":
                st.session_state["reg_errors"] = {"email": result["message"]}
                st.rerun()
            elif reason == "seats_taken":
                # Someone else's submit landed first and claimed one or more
                # of these exact seats between this page's cached read and
                # register_guest()'s in-transaction re-check — the one race
                # that actually matters here. Refresh the cache, drop only
                # the conflicting seats (keep the rest of the pick and every
                # other field the guest already filled in), and let them
                # re-pick rather than losing the whole form. "taken" covers
                # BOTH paid and kid seats (see utils.register_guest), so both
                # selections must be pruned or the kid picker could keep a
                # seat that was just sold out from under it.
                _cached_seat_availability.clear()
                conflict = set(result.get("taken") or [])
                st.session_state["selected_seats"] = [
                    s for s in st.session_state.get("selected_seats", []) if s not in conflict
                ]
                st.session_state["selected_kid_seats"] = [
                    s for s in st.session_state.get("selected_kid_seats", []) if s not in conflict
                ]
                _set_flash("error", result["message"])
                st.rerun()
            elif reason in ("sold_out", "not_enough_tickets"):
                # The last tickets went while this form was open. Refresh the
                # cached count so the rerun shows the true remainder (or the
                # sold-out screen), and carry the explanation across it —
                # st.error here would be discarded by the rerun.
                _cached_availability.clear()
                _cached_seat_availability.clear()
                _set_flash("error", result["message"])
                st.rerun()
            elif reason == "db_unavailable":
                # The guest database is unreachable and we refused to write
                # into the throwaway fallback, so nothing was saved. Say so
                # plainly — do not imply the registration went through.
                st.error(result["message"])
            else:
                st.error(
                    "⚠️ We couldn't save your registration due to a database problem. "
                    "Please try again in a moment, or contact the organizer if it keeps happening."
                )


def _finish_registration(guest_id: int):
    """Hand a just-registered guest over to the Home page.

    Register is the landing page, so it is the first (and for most guests
    the only) screen they see. Once they've submitted, the useful thing to
    show them is everything else — photos, sponsors, ticket count, the
    party stats — rather than a dead-end confirmation screen on the form
    they've finished with. So the confirmation itself moves to the top of
    Home (_render_registration_confirmation) and this sends them there.

    Nothing is rendered here: the st.rerun() below discards the current
    frame, so any message written now would never be painted (see PART 6).
    """
    st.session_state["registered_guest_id"] = guest_id
    st.session_state["just_registered"] = True
    st.session_state["confirmation_celebrated"] = False
    # Clear the form behind them, so "Register Someone Else" lands on a
    # blank step 1 rather than the previous guest's details.
    st.session_state["reset_register_form"] = True
    st.session_state["page"] = "Home"
    _sync_page_query_param("Home")
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# MY QR PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def page_my_qr():
    header_col1, header_col2 = st.columns([4, 1])
    with header_col1:
        st.title("📱 My QR Code")
        st.caption("Look up your party QR code")
    with header_col2:
        _home_button(key="home_my_qr")

    if not _db_ok():
        # Neither path below can succeed without the database: the guest_id
        # shortcut would otherwise call utils.get_guest() (which degrades to
        # None on failure) and show a flatly false "Guest not found.", and
        # the lookup form would tell a real, already-paid guest "No guest
        # found ... please register first" — see utils.find_guest_by_contact()'s
        # docstring for why that's the one thing this page must never say
        # during an outage. Skip both; the banner up top already explains why.
        st.info(
            "Ticket lookups are paused until the database connection is restored. "
            "Please try again in a few minutes — your QR code was also emailed to you "
            "when you registered, so check your inbox (and spam folder) in the meantime."
        )
        return

    # Try query params or session state
    guest_id = None
    try:
        qp = st.query_params
        if "guest_id" in qp:
            guest_id = int(qp["guest_id"])
    except Exception:
        pass
    if not guest_id and st.session_state.get("registered_guest_id"):
        guest_id = st.session_state["registered_guest_id"]
    if not guest_id and st.session_state.get("my_qr_found_guest_id"):
        guest_id = st.session_state["my_qr_found_guest_id"]

    if guest_id:
        guest = utils.get_guest(guest_id)
        if guest:
            _display_guest_qr(guest)
            return
        else:
            st.error("Guest not found.")

    # Email/phone lookup. This lives in a form so the typed value is committed
    # atomically with the button press — outside a form, Streamlit treats the
    # text edit and the click as two separate reruns, and a user who types and
    # immediately clicks can submit an empty value. A form also lets them just
    # press Enter.
    with st.form("qr_lookup_form"):
        lookup_contact = st.text_input(
            "Enter your email or phone number",
            placeholder="your@email.com or 555-123-4567",
            help="Either the email address or the US phone number you registered with.",
        )
        lookup_submitted = st.form_submit_button(
            "🔍 Find My QR", type="primary", use_container_width=True
        )

    found = False
    if lookup_submitted and lookup_contact:
        guest, lookup_error = utils.find_guest_by_contact(lookup_contact)
        if guest:
            st.session_state["my_qr_found_guest_id"] = guest["id"]
            _display_guest_qr(guest)
            found = True
        else:
            st.error(lookup_error)

    if not found:
        with st.container(border=True):
            st.markdown(
                theme.nav_card(
                    "💡",
                    "What is this page?",
                    "Enter the email address or phone number you registered with above to pull "
                    "up your ticket QR code. Your QR code was also emailed to you when you "
                    "registered — check your inbox (and spam folder) for it.",
                ),
                unsafe_allow_html=True,
            )
            if st.button(
                "📝 Haven't registered yet? Go to Register",
                key="my_qr_go_register",
                use_container_width=True,
            ):
                st.session_state["page"] = "Register"
                _sync_page_query_param("Register")
                st.rerun()


def _display_guest_qr(guest: dict):
    """Render a guest's QR code card."""
    st.markdown(f"### {guest['name']}")
    tickets = guest["ticket_count"]
    st.caption(f"{tickets} Ticket{'s' if tickets != 1 else ''}")

    qr_bytes = _cached_qr_image(guest["qr_code"])

    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.image(qr_bytes, use_container_width=True)

    st.markdown(
        "<p style='text-align:center; opacity:0.7;'>Show this QR code at the entrance for check-in</p>",
        unsafe_allow_html=True,
    )

    st.download_button(
        label="💾 Download QR Code",
        data=qr_bytes,
        file_name=f"party_qr_{guest['name'].replace(' ', '_')}.png",
        mime="image/png",
        use_container_width=True,
    )

    if st.button("📧 Resend QR Email", use_container_width=True):
        with st.spinner("Emailing your QR code…"):
            sent = utils.send_qr_email(SimpleNamespace(**guest))
        if sent:
            st.success("QR code emailed!")
        else:
            st.warning(
                "We couldn't send the email right now (SMTP may be disabled in this environment). "
                "Please try again later or contact the organizer."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER PAGE
# ═══════════════════════════════════════════════════════════════════════════════
def page_scanner():
    header_col1, header_col2 = st.columns([4, 1])
    with header_col1:
        st.title("📷 Self Check-In")
        st.caption("Scan your QR code at the entrance")
    with header_col2:
        _home_button(key="home_scanner")

    if not _db_ok():
        # Skip everything below, not just the camera/manual-entry inputs:
        # the stat tiles read from _cached_stats(), which degrades to zeros
        # on failure — rendering "No guests yet" during an outage would be a
        # flat lie on the exact page door staff are staring at. No lookup
        # could succeed anyway (utils.checkin_status() would itself fail
        # closed), so there's nothing safe left on this page to show besides
        # the top-of-page banner (see main()).
        st.info(
            "Check-in is paused until the database connection is restored. "
            "Please try again in a few minutes."
        )
        return

    stats = _cached_stats()
    if stats["total_guests"] == 0:
        st.markdown(
            theme.empty_state(
                "🎟️", "No guests yet",
                "Once people register, this will show who's checked in and how many "
                "are still on their way.",
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            theme.stat_tiles(
                [
                    {"label": "Checked In", "value": stats["checked_in"], "icon": "✅", "accent": "ok", "emphasis": "hero"},
                    {"label": "Total Guests", "value": stats["total_guests"], "icon": "👥", "accent": "gold", "emphasis": "hero"},
                ]
            ),
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Check-in window gate (see PART 3) ──────────────────────────────────
    # The public Scanner must never render the camera/manual-entry inputs
    # while check-in is closed — there's nothing useful a guest could do with
    # them, and utils.check_in_by_code() would just reject the attempt
    # anyway. The server-side window check in utils.check_in_by_code() is
    # the real control; this is just so guests aren't shown dead inputs.
    status = utils.checkin_status()
    if not status["open"]:
        st.markdown(
            theme.closed_notice(status["message"] or f"Opens {status['opens_at_text']}."),
            unsafe_allow_html=True,
        )
        return

    # ── Camera Scan ──────────────────────────────────────────────────────────
    st.subheader("📸 Camera Scan")
    st.write("Hold your QR code up to the camera and click 'Take Photo'")

    camera_image = st.camera_input("Capture QR code")

    if camera_image is not None:
        try:
            import cv2
            import numpy as np
            from PIL import Image

            pil_img = Image.open(camera_image)
            cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(cv_img)

            if data:
                st.success(f"QR Code detected: `{data[:50]}`")
                # Same rule as manual entry: pull the person up first and let
                # staff confirm them, rather than checking in whoever the
                # code happened to resolve to.
                if st.button("🔍 Look Up This Ticket", type="primary", use_container_width=True):
                    _lookup_guest(data)
            else:
                st.warning("No QR code detected in the photo. Try again or use manual entry below.")
        except Exception as e:
            st.error(f"Camera scan unavailable: {e}")
            st.info("Please use the manual entry option below.")

    st.divider()

    # ── Manual Lookup ────────────────────────────────────────────────────────
    st.subheader("⌨️ Find a Guest")
    st.write("Search by phone number, email, ticket ID, or QR code if the camera scan fails")
    # Wrapped in a form so the typed code is committed atomically with the
    # button press. Outside a form, Streamlit handles the text edit and the
    # click as two separate reruns, so someone who types a code and clicks
    # straight away can submit an empty value — a nasty failure mode on a
    # door queue. The form also lets staff just hit Enter after scanning.
    with st.form("manual_checkin_form"):
        manual_code = st.text_input(
            "Phone / Email / Ticket ID / QR Code",
            placeholder="e.g. 555-123-4567",
            max_chars=200,
            help="Phone works in any format. Nobody is checked in until you confirm "
                 "their details on the next screen.",
        )
        manual_submitted = st.form_submit_button(
            "🔍 Find Guest", type="primary", use_container_width=True
        )

    if manual_submitted:
        if manual_code.strip():
            _lookup_guest(manual_code.strip())
        else:
            st.error("Please enter a phone number, email, ticket ID, or QR code.")

    # ── Display Result ─────────────────────────────────────────────────────
    # A pending lookup (nobody checked in yet) takes precedence over the
    # result of the last completed check-in.
    if st.session_state.get("scanner_lookup"):
        _show_guest_confirmation(st.session_state["scanner_lookup"])
    elif st.session_state.get("scanner_result"):
        result = st.session_state["scanner_result"]
        _show_scanner_result(result)


def _lookup_guest(code: str):
    """Find the guest behind a scanned/typed code — without checking anyone in.

    Staff search by phone far more often than by anything else, because
    guests don't remember which email address their QR code went to, and a
    phone number is not proof of identity on its own: it can belong to more
    than one booking, and it can be mistyped. So a match only ever puts the
    guest's details on screen (see _show_guest_confirmation); the check-in
    itself needs a second, deliberate press.
    """
    result = utils.find_guest_by_code(code)

    if result["status"] == "found":
        st.session_state["scanner_lookup"] = result["guest"]
        st.session_state["scanner_result"] = None
    else:
        st.session_state["scanner_lookup"] = None
        st.session_state["scanner_result"] = {
            "type": "error",
            "message": result["message"],
        }
    st.rerun()


def _show_guest_confirmation(guest: dict):
    """Show who was found and let staff confirm before checking them in."""
    bands = utils.wristband_count(guest)
    already = bool(guest.get("checked_in"))

    if already:
        checked_at = _fmt_checkin_iso(guest.get("checkin_time"))
        status_label = f"⚠ Already checked in at {checked_at}"
    else:
        status_label = "Not checked in yet — confirm the details below"

    st.markdown(
        theme.guest_identity_card(
            guest, bands, status_label, status="already" if already else "found"
        ),
        unsafe_allow_html=True,
    )

    band_label = f"✓ Mark {bands} Wristband{'s' if bands != 1 else ''} Given"

    if already:
        st.warning(
            f"{guest['name']} has already been checked in. Only hand over wristbands "
            "if they haven't collected them yet."
        )
        # Bands are offered here only because this guest is already through
        # the door — someone admitted from the admin grid, or back at the
        # desk for the wristbands they didn't take the first time.
        if guest.get("band_given"):
            st.caption("✓ Wristbands already handed over.")
        elif st.button(band_label, use_container_width=True):
            _mark_band_given(guest["id"])
    else:
        st.info(
            f"Confirm this is the right person, then check them in and hand over "
            f"{bands} wristband{'s' if bands != 1 else ''}."
        )
        # Deliberately no band button until the check-in is recorded:
        # otherwise wristbands can walk out of the door against a booking
        # that was never marked as arrived.
        if st.button("✅ Confirm & Check In", type="primary", use_container_width=True):
            _process_checkin_confirmed(guest["id"])

    if st.button("🔍 Search for Someone Else", use_container_width=True):
        st.session_state["scanner_lookup"] = None
        st.rerun()


def _process_checkin_confirmed(guest_id: int):
    """Check in the guest staff just confirmed on screen.

    Keyed by id, not by the code that was searched: re-resolving a phone
    number at confirm time could land on a different booking than the one
    whose details staff just read back to the guest.

    utils.check_in_guest() intentionally raises rather than swallowing a
    write failure (see its docstring) — it's a write path, and the caller
    must not be handed a false "success". page_scanner() already keeps
    this button off-screen whenever utils.db_health() reports the database
    down, but that check happens once per render; the database can still
    die in the narrow window between that check and this click. Catching it
    here turns that race into the same calm "couldn't reach the database"
    result _apply_checkin_result() already renders for db_unavailable,
    instead of an uncaught exception taking down the whole page.
    """
    st.session_state["scanner_lookup"] = None
    try:
        result = utils.check_in_guest(guest_id)
    except Exception as e:
        print(f"check_in_guest({guest_id!r}) failed: {e}")
        result = {"status": "db_unavailable", "guest": None, "message": utils.DB_DEGRADED_MESSAGE}
    _apply_checkin_result(result)


def _apply_checkin_result(result: dict):
    """Turn a check-in service result into scanner UI state, then rerun."""

    if result["status"] == "db_unavailable":
        # The guest database is unreachable. Nothing was recorded, so staff
        # must not be shown a green "welcome" they'd act on.
        st.session_state["scanner_result"] = {
            "type": "error",
            "message": result["message"],
        }
        st.rerun()
        return

    if result["status"] == "not_open":
        # Defensive: the Scanner page already hides these inputs while
        # closed, but the window can close between page-load and button
        # click (e.g. an admin flips the mode mid-scan). check_in_by_code()
        # returns guest=None here, so this must be handled before the
        # "success" fallthrough below, which assumes a guest dict.
        st.session_state["scanner_result"] = {
            "type": "error",
            "message": result["message"] or "Check-in isn't open yet.",
        }
        st.rerun()
        return

    if result["status"] == "not_found":
        st.session_state["scanner_result"] = {
            "type": "error",
            "message": result["message"],
        }
        st.rerun()
        return

    if result["status"] == "already":
        st.session_state["scanner_result"] = {
            "type": "warning",
            "guest": result["guest"],
            "message": result["message"],
        }
        st.rerun()
        return

    # success
    guest = result["guest"]
    _cached_stats.clear()
    _cached_event_day_hourly_checkins.clear()
    announcement = utils.generate_welcome_announcement(guest["name"], guest["ticket_count"])
    st.session_state["scanner_result"] = {
        "type": "success",
        "guest": guest,
        "message": result["message"],
        "announcement": announcement,
        "guest_id": guest["id"],
    }
    st.rerun()


def _show_scanner_result(result):
    """Display the scanner result UI and play audio."""
    result_type = result.get("type")

    if result_type == "success":
        guest = result["guest"]
        bands = utils.wristband_count(guest)
        st.balloons()
        st.markdown(
            theme.guest_result_card(guest["name"], guest["ticket_count"], "success", result["message"]),
            unsafe_allow_html=True,
        )
        st.info(f"🎗️ Hand over **{bands}** wristband{'s' if bands != 1 else ''} — one per ticket.")

        if st.button(f"✓ Mark {bands} Wristband{'s' if bands != 1 else ''} Given",
                     type="primary", use_container_width=True):
            _mark_band_given(result["guest_id"])

        announcement = result.get("announcement", "")
        if announcement:
            st.components.v1.html(utils.audio_announcement_js(announcement), height=0)
            st.info(f"🔊 {announcement}")

        if st.button("🔄 Scan Next Guest", use_container_width=True):
            st.session_state["scanner_result"] = None
            st.rerun()

    elif result_type == "warning":
        guest = result["guest"]
        st.markdown(
            theme.guest_result_card(guest["name"], guest["ticket_count"], "already", result["message"]),
            unsafe_allow_html=True,
        )

        if st.button("🔄 Scan Next Guest", use_container_width=True):
            st.session_state["scanner_result"] = None
            st.rerun()

    elif result_type == "error":
        st.markdown(
            theme.guest_result_card("Unknown", None, "error", result["message"]),
            unsafe_allow_html=True,
        )

        if st.button("🔄 Try Again", use_container_width=True):
            st.session_state["scanner_result"] = None
            st.rerun()


def _mark_band_given(guest_id: int):
    """Thin wrapper over utils.mark_band_given that updates UI state.

    Stashes the result via _set_flash() instead of calling st.success()
    directly — a st.rerun() follows immediately below, which used to discard
    the message before staff ever saw it (see PART 6).

    utils.mark_band_given() is a write path and doesn't swallow a DB
    failure (see _process_checkin_confirmed()'s docstring for why that's
    correct and why this try/except exists anyway: the database can die in
    the narrow window between page_scanner()'s once-per-render health check
    and this click).
    """
    try:
        result = utils.mark_band_given(guest_id)
    except Exception as e:
        print(f"mark_band_given({guest_id!r}) failed: {e}")
        st.error(
            "Couldn't mark the wristband as given — the database is temporarily "
            "unreachable. Please try again in a moment."
        )
        return
    _cached_stats.clear()
    if result["ok"]:
        _set_flash("success", result["message"])
        st.components.v1.html(utils.audio_announcement_js("Band marked as given"), height=0)
        # If staff are still on this guest's confirmation card, keep them
        # there with a refreshed copy — the stashed dict's band_given is now
        # stale, and re-rendering it would invite handing out a second set.
        lookup = st.session_state.get("scanner_lookup")
        if lookup and lookup.get("id") == guest_id:
            st.session_state["scanner_lookup"] = utils.get_guest(guest_id) or lookup
        else:
            st.session_state["scanner_result"] = None
        st.rerun()
    else:
        st.warning(result["message"])


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════
ADMIN_MAX_ATTEMPTS = 5
ADMIN_LOCKOUT_SECONDS = 60


def page_admin():
    header_col1, header_col2 = st.columns([4, 1])
    with header_col1:
        st.title("📊 Admin Dashboard")
        st.caption("Manage guests and monitor check-ins")
    with header_col2:
        _home_button(key="home_admin")

    if not utils.admin_password_is_configured():
        st.error(
            "🚫 Admin password is not set — configure the ADMIN_PASSWORD secret to enable the dashboard."
        )
        return

    # ── Auth ─────────────────────────────────────────────────────────────────
    if not st.session_state.get("admin_authenticated"):
        lockout_until = st.session_state.get("admin_lockout_until", 0.0)
        now = time.time()

        if lockout_until and now < lockout_until:
            remaining = int(lockout_until - now) + 1
            st.error(f"🔒 Too many attempts. Try again in {remaining}s.")
            return

        if lockout_until and now >= lockout_until:
            st.session_state["admin_lockout_until"] = 0.0
            st.session_state["admin_fail_count"] = 0

        with st.form("admin_login"):
            st.info("Enter admin password to access the dashboard")
            password = st.text_input("Admin Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if utils.verify_admin_password(password):
                st.session_state["admin_authenticated"] = True
                st.session_state["admin_fail_count"] = 0
                st.session_state["admin_lockout_until"] = 0.0
                st.rerun()
            else:
                fail_count = st.session_state.get("admin_fail_count", 0) + 1
                st.session_state["admin_fail_count"] = fail_count
                if fail_count >= ADMIN_MAX_ATTEMPTS:
                    st.session_state["admin_lockout_until"] = time.time() + ADMIN_LOCKOUT_SECONDS
                    st.error(f"🔒 Too many attempts. Try again in {ADMIN_LOCKOUT_SECONDS}s.")
                else:
                    st.error(f"Incorrect password. ({fail_count}/{ADMIN_MAX_ATTEMPTS} attempts)")
        return

    if st.button("🔒 Logout", type="secondary"):
        st.session_state["admin_authenticated"] = False
        st.rerun()

    if not _db_ok():
        # Password check above only reads a secret (verify_admin_password),
        # so login itself must keep working during an outage — an admin
        # locked out of their own dashboard is the last thing this needs.
        # But every tab below (guest table, check-in log, stats) and the
        # Danger Zone (which reads live table counts before allowing a
        # delete) are all DB-backed; skip the whole dashboard body rather
        # than let any of them explode or show stale/zeroed numbers as real.
        st.info(
            "Guest management is paused until the database connection is restored. "
            "Try refreshing in a few minutes."
        )
        return

    tab_overview, tab_guests, tab_checkins = st.tabs(["Overview", "Guests", "Check-ins"])

    with tab_overview:
        _admin_overview_tab()
    with tab_guests:
        _admin_guests_tab()
    with tab_checkins:
        _admin_checkins_tab()

    _admin_danger_zone()


RESET_CONFIRM_PHRASE = "RESET"


def _admin_danger_zone():
    """The destructive "wipe everything" control.

    Collapsed by default (st.expander) so it can't be triggered by accident,
    and gated behind a typed confirmation phrase — a single click is never
    enough. Lives at the very bottom of the Admin page, below all three tabs.
    """
    with st.expander("⚠️ Danger Zone", expanded=False):
        st.markdown(
            '<div class="danger-zone-warning">'
            "🚨 <strong>This permanently deletes every guest, check-in log, page-visit "
            "record, and submission log — for everyone, with no undo.</strong> The check-in "
            "window is also reset back to Auto. Take a backup first — the section directly "
            "below downloads every table as CSV, and it is the only way back."
            "</div>",
            unsafe_allow_html=True,
        )

        _admin_backup_section()

        counts = utils.get_table_counts()
        st.markdown(
            theme.section_header("About to delete", "Live counts — refreshed every time you open this section."),
            unsafe_allow_html=True,
        )
        st.markdown(
            theme.stat_tiles(
                [
                    {"label": "Guests", "value": counts["guests"], "icon": "👤", "accent": "err"},
                    {"label": "Check-in Logs", "value": counts["checkin_logs"], "icon": "🧾", "accent": "err"},
                    {"label": "Page Visits", "value": counts["page_visits"], "icon": "👣", "accent": "err"},
                    {"label": "Submissions", "value": counts["submission_logs"], "icon": "📝", "accent": "err"},
                ]
            ),
            unsafe_allow_html=True,
        )

        if sum(counts.values()) == 0:
            st.info("Nothing to reset — every table is already empty.")

        if "admin_backup" not in st.session_state and sum(counts.values()) > 0:
            st.warning("No backup prepared in this session. Take one above first — this cannot be undone.")

        st.markdown(f"Type **{RESET_CONFIRM_PHRASE}** below to enable the delete button.")
        confirm_text = st.text_input(
            "Confirmation phrase",
            key="admin_reset_confirm_text",
            placeholder=f"Type {RESET_CONFIRM_PHRASE} to confirm",
            label_visibility="collapsed",
        )
        confirmed = confirm_text.strip() == RESET_CONFIRM_PHRASE
        if confirm_text and not confirmed:
            st.caption(f"That doesn't match. Type “{RESET_CONFIRM_PHRASE}” exactly (all caps) to proceed.")

        if st.button(
            "🗑️ Permanently delete all data",
            type="primary",
            use_container_width=True,
            disabled=not confirmed,
            key="admin_reset_button",
        ):
            # Re-check server-side — disabled= only guards the button in the
            # browser; a stale rerun must never be able to fire this.
            if confirm_text.strip() != RESET_CONFIRM_PHRASE:
                st.error(f"Type “{RESET_CONFIRM_PHRASE}” exactly to confirm.")
            else:
                result = utils.reset_all_data()
                # reset_all_data() reports a DB failure as {"ok": False, ...}
                # rather than raising, so the counts are absent on that path.
                # Never claim a reset happened when it didn't — the operator
                # would think the tables were cleared and stop checking.
                if result.get("ok") is False:
                    _set_flash(
                        "error",
                        "⚠️ Reset failed — the guest database is unreachable, so nothing was "
                        f"deleted. {result.get('message', '')} Please try again once it's back.",
                    )
                    st.rerun()
                _clear_all_caches_and_state_after_reset()
                summary = (
                    f"✅ Reset complete — deleted {result['guests']} guest(s), "
                    f"{result['checkin_logs']} check-in log(s), {result['page_visits']} page visit(s), "
                    f"{result['submission_logs']} submission log(s). Check-in mode is back to Auto."
                )
                _set_flash("success", summary)
                st.rerun()

        _admin_data_catalog()


def _admin_backup_section():
    """Download every table as CSV before wiping it.

    Two steps on purpose. Building the archive means reading all five tables,
    and Streamlit re-runs this whole function on every widget interaction —
    so it is built only when the operator asks for it, then held in
    st.session_state so the download buttons can serve it without rebuilding.
    The held copy also survives the reset itself: after the tables are empty
    it is the only copy left, so it must stay downloadable.
    """
    st.markdown(
        theme.section_header(
            "Back up first",
            "One CSV per table, bundled as a ZIP — raw columns, ready to reload or open in Excel.",
        ),
        unsafe_allow_html=True,
    )

    if st.button("📦 Prepare backup", use_container_width=True, key="admin_backup_prepare"):
        with st.spinner("Reading every table…"):
            result = utils.export_backup()
        # export_backup() reports a DB failure as {"ok": False, ...} rather
        # than raising, so a failed snapshot has no "zip"/"stamp" keys. Keep
        # it OUT of session_state: storing it would make the download buttons
        # below hand the operator an archive that doesn't exist, and — worse —
        # make the Danger Zone look like a backup had been taken before a wipe.
        if result.get("ok") is False:
            st.error(
                "⚠️ Couldn't build the backup — the guest database is unreachable. "
                f"{result.get('message', '')} Do NOT reset until a backup succeeds."
            )
        else:
            st.session_state["admin_backup"] = result

    backup = st.session_state.get("admin_backup")
    if backup is None:
        st.caption("Nothing prepared yet — click **Prepare backup** to build a snapshot you can download.")
        return

    st.download_button(
        label="⬇ Download full backup (ZIP)",
        data=backup["zip"],
        file_name=f"party_backup_{backup['stamp']}.zip",
        mime="application/zip",
        use_container_width=True,
        key="admin_backup_zip",
    )

    # Individual CSVs too — a phone can't always open a ZIP.
    tables = list(utils.BACKUP_TABLES)
    for start in range(0, len(tables), 3):
        for col, table in zip(st.columns(3), tables[start:start + 3]):
            col.download_button(
                label=f"⬇ {table}.csv ({backup['counts'][table]})",
                data=backup["files"][f"{table}.csv"],
                file_name=f"{table}_{backup['stamp']}.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"admin_backup_csv_{table}",
            )

    total_rows = sum(backup["counts"].values())
    st.caption(
        f"Snapshot taken {utils.format_dt(backup['generated_at'], '%Y-%m-%d %H:%M:%S')} UTC — "
        f"{total_rows} row(s) across {len(tables)} tables. Prepare again if anything has changed since."
    )


def _admin_data_catalog():
    """Reference list of what lives where — for querying the DB directly
    (Supabase SQL editor, psql) rather than through this dashboard. The same
    text ships inside every backup's README.txt.
    """
    st.markdown(
        theme.section_header(
            "Tables & views to query",
            "For direct SQL access — the Supabase SQL editor, psql, or any client.",
        ),
        unsafe_allow_html=True,
    )

    table_rows = "\n".join(f"| `{table}` | {description} |" for table, description in utils.DATA_TABLES)
    st.markdown(
        "**Tables** — everything the reset touches, and everything the backup contains. "
        "The first four are emptied; `app_settings` only has `checkin_mode` put back to `auto`.\n\n"
        "| Table | What it holds |\n|---|---|\n" + table_rows
    )

    view_rows = "\n".join(f"| `{view}` | {description} |" for view, description in utils.REPORTING_VIEWS)
    st.markdown(
        "**Views** — PostgreSQL/Supabase only, created automatically at startup. They read from the "
        "tables above, so they empty out with a reset and refill on their own. Nothing to recreate.\n\n"
        "| View | What it answers |\n|---|---|\n" + view_rows
    )


def _clear_all_caches_and_state_after_reset() -> None:
    """After utils.reset_all_data(): drop every cached stat and any session
    state that could still reference a now-deleted guest, so the dashboard
    reads zero immediately instead of showing stale cached numbers or a
    "guest not found" error from a lingering id (see PART 7 / the flash
    message pattern notes at the top of this file).

    "admin_backup" is deliberately NOT cleared: once the tables are empty that
    prepared archive is the only copy of the data left, and the operator must
    still be able to download it.
    """
    _cached_stats.clear()
    _cached_site_stats.clear()
    _cached_registration_daily_counts.clear()
    _cached_event_day_hourly_checkins.clear()
    _cached_availability.clear()
    st.session_state["registered_guest_id"] = None
    st.session_state["scanner_result"] = None
    st.session_state["admin_pending_changes"] = None
    st.session_state.pop("admin_guest_editor", None)
    st.session_state.pop("admin_reset_confirm_text", None)


def _admin_overview_tab():
    stats = _cached_stats()
    st.markdown(theme.section_header("At a Glance"), unsafe_allow_html=True)

    # Live load, for the organiser to watch during a burst (e.g. right after
    # the registration link goes out). Not cached — it's an in-memory,
    # DB-free read (utils.active_session_count()), so there's no cost to
    # reading it fresh on every Admin render.
    # Guarded for the same reason as the gate itself — see _safe_active_count().
    active_now = _safe_active_count(register=False)
    hard_limit = config.max_concurrent_users()
    st.caption(f"🟢 {active_now} active session(s) in the last minute · capacity guard at {hard_limit}")

    # Ticket cap: how full the party is, and how close sign-ups are to closing.
    availability = _cached_availability()
    st.markdown(
        theme.tickets_remaining(
            availability,
            context="Registration closes automatically once every ticket is claimed. "
                    "Adjust the cap with the MAX_TOTAL_TICKETS secret.",
        ),
        unsafe_allow_html=True,
    )

    if stats["total_guests"] == 0:
        st.markdown(
            theme.empty_state(
                "🪄", "Nothing to show yet",
                "No guests registered yet. Once people sign up and check in, your stats, "
                "check-in rate, and revenue will show up here.",
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            theme.stat_tiles(
                [
                    {"label": "Total Guests", "value": stats["total_guests"], "icon": "👥", "accent": "gold", "emphasis": "hero"},
                    {"label": "Checked In", "value": stats["checked_in"], "icon": "✅", "accent": "ok", "emphasis": "hero"},
                    {"label": "Pending", "value": stats["pending"], "icon": "⏳", "accent": "warn"},
                    {"label": "Bands Given", "value": stats["bands_distributed"], "icon": "🏷️", "accent": "turquoise"},
                    {"label": "Total Tickets", "value": stats["total_tickets"], "icon": "🎫"},
                    {"label": "Admitted Tickets", "value": stats["admitted_tickets"], "icon": "🚪", "accent": "info"},
                    {"label": "Revenue (est.)", "value": f"${stats['revenue']:,.2f}", "icon": "💰", "accent": "gold"},
                    {"label": "Plus Ones", "value": stats["plus_one_count"], "icon": "➕", "accent": "rust"},
                    {"label": "Named Guests", "value": stats["named_guests"], "icon": "👥", "accent": "rust"},
                    {"label": "Unnamed Tickets", "value": stats["unnamed_tickets"], "icon": "❓", "accent": "warn"},
                ]
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            theme.checkin_progress_meter(stats["checked_in"], stats["total_guests"]),
            unsafe_allow_html=True,
        )

    # ── Check-in window control (see PART 3) ───────────────────────────────
    st.markdown(
        theme.section_header(
            "Check-in Window", "Control when guests can check themselves in on the Scanner page."
        ),
        unsafe_allow_html=True,
    )

    status = utils.checkin_status()
    if status["open"]:
        detail_text = "guests can check themselves in on the Scanner page right now"
    elif status["mode"] == utils.CHECKIN_MODE_CLOSED:
        detail_text = "closed by the organiser"
    else:
        detail_text = f"opens {status['opens_at_text']}"
    st.markdown(theme.checkin_window_banner(status["open"], detail_text), unsafe_allow_html=True)

    mode_options = {
        "Auto (opens 2h before event)": utils.CHECKIN_MODE_AUTO,
        "Open now": utils.CHECKIN_MODE_OPEN,
        "Closed": utils.CHECKIN_MODE_CLOSED,
    }
    labels = list(mode_options.keys())
    current_label = next(label for label, mode in mode_options.items() if mode == status["mode"])
    chosen_label = st.radio(
        "Check-in mode",
        labels,
        index=labels.index(current_label),
        horizontal=True,
        key="admin_checkin_mode_radio",
    )
    chosen_mode = mode_options[chosen_label]
    if chosen_mode != status["mode"]:
        utils.set_checkin_mode(chosen_mode)
        _set_flash("success", f"Check-in mode set to “{chosen_label}”.")
        st.rerun()


def _admin_guests_tab():
    st.markdown(
        theme.section_header("Guests", "Search, check people in, hand out bands, or remove a row — all in one pass."),
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("+ Add Guest", use_container_width=True):
            st.session_state["page"] = "Register"
            st.rerun()
    with col2:
        csv_data = utils.generate_csv()
        st.download_button(
            label="⬇ Download CSV",
            data=csv_data,
            file_name=f"party_guests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    guests = utils.list_guests()

    if not guests:
        st.info("No guests registered yet. Once someone registers, they'll show up here.")
        return

    search_term = st.text_input(
        "🔍 Search by name, email, phone, or Zelle ref",
        placeholder="Type to filter...",
        key="admin_guest_search",
    )

    filtered = guests
    if search_term:
        term = search_term.lower()
        # Phone matches on digits alone, so "5551234567", "555-123-4567" and
        # "1234" all find a guest stored as "+1-555-123-4567".
        term_digits = utils.phone_digits(term)
        filtered = [
            g
            for g in guests
            if term in g["name"].lower()
            or term in g["email"].lower()
            or term in (g["zelle_ref"] or "").lower()
            or (term_digits and term_digits in utils.phone_digits(g["phone"]))
        ]

    if not filtered:
        st.warning(f"No guests match “{search_term}”.")
        return

    st.caption(
        f"{len(filtered)} of {len(guests)} guest{'s' if len(guests) != 1 else ''} shown. "
        "Tick boxes below, then Save changes."
    )

    df = pd.DataFrame(
        [
            {
                "id": g["id"],
                "Name": g["name"],
                "Email": g["email"],
                "Phone": g["phone"] or "—",
                "Tickets": g["ticket_count"],
                "Seats": config.format_seat_labels(g["seats"]) or "—",
                "Kid Seats": config.format_seat_labels(g.get("kid_seats", [])) or "—",
                "Party Size": utils.party_size(g),
                "Names": utils.guest_name_count(g["plus_one_name"]),
                "Additional Guests": (g["plus_one_name"] or "").replace("\n", ", ") or "—",
                "Checked In": bool(g["checked_in"]),
                "Band Given": bool(g["band_given"]),
                "Delete": False,
            }
            for g in filtered
        ]
    )

    edited = st.data_editor(
        df,
        key="admin_guest_editor",
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "id": None,  # keep for row identity, hide from display
            "Name": st.column_config.TextColumn("Name"),
            "Email": st.column_config.TextColumn("Email"),
            "Phone": st.column_config.TextColumn("Phone", help="“—” means the guest registered before phone became mandatory."),
            "Tickets": st.column_config.NumberColumn("Tickets"),
            # Read-only: utils.apply_guest_changes() has no validation for a
            # seat edit made here (no conflict check against other guests'
            # seats), so an editable cell could silently double-book a seat.
            # If seats ever need to change, do it through a new booking, not
            # a hand edit in this grid.
            "Seats": st.column_config.TextColumn("Seats", help="Booked seat labels (row + number). Read-only here — edits could silently double-book a seat."),
            # Read-only for the same reason as Seats above: apply_guest_changes()
            # has no seat validation, so an editable cell here could silently
            # double-book a free child seat too.
            "Kid Seats": st.column_config.TextColumn("Kid Seats", help="Free child seat labels (row + number). Read-only here — edits could silently double-book a seat."),
            "Party Size": st.column_config.NumberColumn(
                "Party Size", help="Total people on this booking, including the person who registered."
            ),
            "Names": st.column_config.NumberColumn(
                "Names",
                help="How many additional guests were named. Should be Tickets − 1; a lower "
                     "number means the booking predates mandatory guest names.",
            ),
            "Additional Guests": st.column_config.TextColumn("Additional Guests"),
            "Checked In": st.column_config.CheckboxColumn("Checked In", help="Tick to check this guest in."),
            "Band Given": st.column_config.CheckboxColumn("Band Given", help="Tick once their wristband is on."),
            "Delete": st.column_config.CheckboxColumn("Delete", help="Tick then Save changes — a confirmation step follows."),
        },
        disabled=["id", "Name", "Email", "Phone", "Tickets", "Seats", "Kid Seats", "Party Size", "Names", "Additional Guests"],
    )

    if st.button("💾 Save changes", type="primary", use_container_width=True, key="admin_save_changes"):
        original_by_id = {g["id"]: g for g in filtered}
        pending = []
        for _, row in edited.iterrows():
            gid = int(row["id"])
            orig = original_by_id.get(gid)
            if not orig:
                continue
            pending.append(
                {
                    "id": gid,
                    "name": orig["name"],
                    "checked_in": bool(row["Checked In"]),
                    "band_given": bool(row["Band Given"]),
                    "delete": bool(row["Delete"]),
                }
            )

        to_delete = [p for p in pending if p["delete"]]
        if to_delete:
            # Destructive changes need an explicit confirm step — don't
            # apply anything (not even the check-ins/bands in this same
            # batch) until the admin confirms below (see PART 5).
            st.session_state["admin_pending_changes"] = pending
        else:
            result = _call_apply_guest_changes(pending)
            if result is not None:
                st.session_state.pop("admin_guest_editor", None)
                _apply_guest_changes_cache_clear(result)
                _report_guest_changes(result)
                st.rerun()

    pending_changes = st.session_state.get("admin_pending_changes")
    if pending_changes:
        to_delete = [p for p in pending_changes if p["delete"]]
        names = ", ".join(f"**{p['name']}**" for p in to_delete)
        count = len(to_delete)
        st.warning(
            f"⚠️ This will permanently delete {count} guest{'s' if count != 1 else ''}: {names}. "
            "This cannot be undone."
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button(
                "Yes, apply changes (incl. delete)",
                type="primary",
                use_container_width=True,
                key="admin_confirm_apply",
            ):
                result = _call_apply_guest_changes(st.session_state["admin_pending_changes"])
                if result is not None:
                    st.session_state["admin_pending_changes"] = None
                    st.session_state.pop("admin_guest_editor", None)
                    _apply_guest_changes_cache_clear(result)
                    _report_guest_changes(result)
                    st.rerun()
        with cc2:
            if st.button("Cancel", use_container_width=True, key="admin_cancel_apply"):
                st.session_state["admin_pending_changes"] = None
                st.rerun()


def _call_apply_guest_changes(updates: list):
    """utils.apply_guest_changes() wrapped for the same narrow-race reason as
    _process_checkin_confirmed()/_mark_band_given(): it's a write path (it
    checks guests in, hands out bands, deletes rows) and correctly doesn't
    swallow a DB failure — but the database can still die in the window
    between page_admin()'s once-per-render health check and this button
    click, and a raised exception here must not take down the whole Admin
    page. Returns None (having already shown an error) on failure, so
    callers can skip the cache-clear/report/rerun that assumes success.
    """
    try:
        return utils.apply_guest_changes(updates)
    except Exception as e:
        print(f"apply_guest_changes failed: {e}")
        st.error(
            "Couldn't save those changes — the database is temporarily unreachable. "
            "Please try again in a moment."
        )
        return None


def _apply_guest_changes_cache_clear(result: dict) -> None:
    """Targeted cache invalidation after utils.apply_guest_changes() (PART 7)."""
    _cached_stats.clear()
    if result.get("deleted"):
        # Deleting a guest frees up their tickets against the cap.
        _cached_availability.clear()
        _cached_site_stats.clear()
        _cached_registration_daily_counts.clear()
    if result.get("checked_in") or result.get("deleted"):
        _cached_event_day_hourly_checkins.clear()


def _report_guest_changes(result: dict) -> None:
    """Report what utils.apply_guest_changes() actually did, via toast + flash.

    st.toast() persists across the single st.rerun() that follows this call,
    but it's brief (~4s) and easy to miss, so we also stash a longer-lived
    summary via _set_flash() to show at the top of the next run.
    """
    parts = []
    if result.get("checked_in"):
        parts.append(f"Checked in {result['checked_in']}")
    if result.get("band_given"):
        parts.append(f"Bands given {result['band_given']}")
    if result.get("deleted"):
        parts.append(f"Deleted {result['deleted']}")
    summary = " · ".join(parts) if parts else "No changes to apply."
    st.toast(summary, icon="✅" if parts else "ℹ️")
    _set_flash("success" if parts else "info", summary)


def _admin_checkins_tab():
    st.markdown(
        theme.section_header("Recent Check-ins", "The last 10 guests through the door."),
        unsafe_allow_html=True,
    )
    recent = utils.get_recent_checkins(10)
    if not recent:
        st.info("No check-ins yet. They'll appear here as guests arrive.")
        return

    for g in recent:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                tickets = g["ticket_count"]
                st.markdown(f"**{g['name']}** — {tickets} ticket{'s' if tickets != 1 else ''}")
                st.caption(f"Checked in at {_fmt_checkin_iso(g['checkin_time'], '%I:%M %p')}")
            with c2:
                st.markdown("✅ " + ("Band Given" if g["band_given"] else "No Band"))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP / NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════════
def _render_capacity_page() -> None:
    """The friendly full-page "we're at capacity" screen, plus a Retry button.

    st.button triggers a rerun on click, which re-enters main() and
    re-evaluates the gate from scratch — exactly what "Retry" should do,
    with no special-case state to track.
    """
    st.markdown(theme.brand_bar(), unsafe_allow_html=True)
    st.markdown(theme.capacity_full_page(), unsafe_allow_html=True)
    if st.button("🔄 Try Again", type="primary", use_container_width=True, key="capacity_retry"):
        st.rerun()


def main():
    # Session identity: created once per browser session and reused both by
    # the capacity guard (below) and page-visit tracking (further down) —
    # previously two separate tokens were minted in two different places.
    #
    # Streamlit mints a brand-new session on every full page reload or
    # dropped/reconnected WebSocket (screen lock, backgrounding, a network
    # blip — all common on mobile), which was counting the same returning
    # person as a fresh "unique visitor" every time.
    #
    # ?v= in the URL (st.query_params, the same mechanism _sync_page_query_
    # param already relies on for ?page=) is the primary recovery path: it's
    # proven to round-trip through Streamlit Community Cloud's reverse proxy
    # in production. A cookie was tried first but confirmed NOT to survive a
    # plain refresh once actually deployed there (worked in local testing,
    # not on Cloud — most likely lost in the proxy's WebSocket-upgrade
    # handshake before it ever reaches st.context.cookies) — kept only as a
    # harmless best-effort second attempt.
    if "visitor_token" not in st.session_state:
        token = ""
        try:
            token = st.query_params.get(utils.VISITOR_QUERY_PARAM, "") or ""
        except Exception:
            pass

        if not token:
            try:
                token = st.context.cookies.get(utils.VISITOR_COOKIE_NAME, "") or ""
            except Exception:
                token = ""

        if not token:
            token = base64.urlsafe_b64encode(os.urandom(12)).decode()
            st.components.v1.html(utils.visitor_cookie_js(token), height=0)

        st.session_state["visitor_token"] = token
        try:
            st.query_params[utils.VISITOR_QUERY_PARAM] = token
        except Exception:
            pass

        try:
            user_agent = st.context.headers.get("User-Agent", "") or ""
        except Exception:
            user_agent = ""
        st.session_state["is_bot_visit"] = utils.is_bot_user_agent(user_agent)

    # ── Capacity guard ───────────────────────────────────────────────────
    # Registers this session as active and gets back the current
    # process-wide active-session count — an in-memory, DB-free call (see
    # utils.touch_session()), so it costs nothing even during a burst.
    # Called exactly once per script run, as early as possible.
    #
    # Wrapped defensively: load-shedding telemetry must NEVER be able to take
    # the whole app down. Streamlit Cloud can end up executing a new
    # streamlit_app.py against a `utils` module still cached in the running
    # process from before a deploy, in which case this attribute doesn't
    # exist yet and an unguarded call raises AttributeError on every page
    # load — a total outage caused by an optional feature. Treat any failure
    # here as "we don't know the load", which simply means nobody is gated.
    active_count = _safe_active_count()

    # Resolve which page this run is headed to *before* deciding whether to
    # gate, so Admin/Scanner and an already-authenticated admin are never
    # blocked — staff must never be locked out of their own door. This is
    # the same resolution the sidebar below performs; hoisted up here so the
    # gate can see it without rendering the sidebar first.
    #
    # With no ?page= of its own, the bare app URL opens on
    # config.LANDING_PAGE (Register) — that URL is the registration link the
    # organiser sends out, so it opens on the form. Home is where a guest is
    # sent once they've submitted, and is still reachable directly via
    # ?page=Home or the sidebar.
    if "page" not in st.session_state:
        try:
            qp = st.query_params
            requested = qp["page"] if "page" in qp else None
            st.session_state["page"] = requested if requested in PAGES else config.LANDING_PAGE
        except Exception:
            st.session_state["page"] = config.LANDING_PAGE
    target_page = st.session_state["page"]

    gate_exempt = target_page in ("Admin", "Scanner") or bool(
        st.session_state.get("admin_authenticated")
    )

    hard_limit = config.max_concurrent_users()
    soft_limit = config.busy_warn_users()
    over_capacity = (not gate_exempt) and active_count > hard_limit
    is_busy = (not gate_exempt) and (not over_capacity) and active_count > soft_limit

    if over_capacity:
        # Degrade politely, never collapse: turned-away visitors see a warm,
        # non-technical "give it a minute" screen with a Retry button, never
        # a stack trace or a blank page. Nothing else in this run touches
        # the database.
        _render_capacity_page()
        return

    # Mobile-friendly sidebar (collapsed by default, opens as overlay on mobile)
    with st.sidebar:
        st.title("🎭 Check-In")
        st.markdown("---")

        page = st.radio(
            "Navigate",
            PAGES,
            index=PAGES.index(st.session_state["page"]),
            label_visibility="collapsed",
        )

        if page != st.session_state.get("page"):
            st.session_state["page"] = page
            _sync_page_query_param(page)
            st.rerun()

        st.markdown("---")
        st.markdown(f"<small>v{config.APP_VERSION} • Streamlit Edition</small>", unsafe_allow_html=True)

    # Sticky brand bar on every page
    st.markdown(theme.brand_bar(), unsafe_allow_html=True)

    # ── Database health ─────────────────────────────────────────────────────
    # A cheap, ACTIVELY re-probed check (unlike the cached engine itself,
    # which only validates its connection once, at creation — see
    # utils.db_health()'s docstring). The page is already resolved above, so
    # this renders once, right here, ahead of every page's own content — the
    # one signal a guest or organiser sees regardless of which page they're
    # on. Individual page functions below call utils.db_health() again
    # (cheap: memoized for a few seconds) to decide what DB-backed content to
    # skip; they don't re-render this banner themselves.
    if not _db_ok():
        # getattr for the same stale-module reason as _db_ok(): a freshly
        # deployed page file can run against a `theme` module cached from
        # before the deploy, and an unguarded new builder would then kill
        # every page load. Fall back to a plain st.warning, which always
        # exists, rather than losing the message entirely.
        banner = getattr(theme, "db_unavailable_banner", None)
        if banner is not None:
            st.markdown(banner(_db_health_detail()), unsafe_allow_html=True)
        else:
            st.warning(
                "We can't reach the guest database right now, so registrations and "
                "check-ins are paused. This is a temporary problem on our end — "
                "please try again in a few minutes.",
                icon="🗄️",
            )

    if is_busy:
        st.markdown(theme.busy_banner(), unsafe_allow_html=True)

    # Show (and clear) any flash message stashed by the previous run — see
    # the "Flash messages" section above / PART 6.
    _render_flash()

    # Record page visit once per navigation / refresh for traffic stats.
    # Skipped for known crawlers/link-unfurlers (is_bot_visit) so a shared
    # invite link being fetched for a chat preview doesn't inflate the count.
    try:
        current_page = st.session_state.get("page", config.LANDING_PAGE)
        if (
            not st.session_state.get("is_bot_visit")
            and st.session_state.get("last_recorded_page") != current_page
        ):
            utils.record_visit(st.session_state["visitor_token"], current_page)
            st.session_state["last_recorded_page"] = current_page
    except Exception:
        pass

    # Reset registration state when navigating to the Register page from
    # elsewhere: a fresh visit to the form starts at step 1 with empty
    # fields, and the previous booking's confirmation card on Home goes with
    # it — it belongs to a registration the guest has moved on from.
    current_page = st.session_state.get("page", config.LANDING_PAGE)
    if st.session_state.get("_prev_page") != current_page:
        if current_page == "Register":
            _clear_registration_confirmation()
            st.session_state["reset_register_form"] = True
        st.session_state["_prev_page"] = current_page

    # Render selected page
    if page == "Home":
        page_home()
    elif page == "Register":
        page_register()
    elif page == "My QR":
        page_my_qr()
    elif page == "Scanner":
        page_scanner()
    elif page == "Admin":
        page_admin()


if __name__ == "__main__":
    main()
