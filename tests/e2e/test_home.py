"""Flow 1: Home loads; hero shows the event name; the "Party Buzz" section
(PART 4 admin redesign: traffic tiles + both bar charts, moved here from
the old admin Overview tab) renders; the Photos and Sponsors sections show
their placeholders while unconfigured; each nav card navigates to the right
page.

Home is NOT the landing page — the bare app URL opens on Register (see
config.LANDING_PAGE and test_registration.test_landing_page_is_register), so
every test here navigates to it explicitly with `goto(page, base_url, "Home")`.
"""
import re

import pytest
from playwright.sync_api import expect

from .helpers import goto

NAV_CARDS = [
    (re.compile(r"Register Guest"), re.compile(r"Register Guest")),
    (re.compile(r"My QR Code"), re.compile(r"My QR Code")),
    (re.compile(r"Self Check-In"), re.compile(r"Self Check-In")),
    (re.compile(r"Admin Dashboard"), re.compile(r"Admin Dashboard")),
]

PARTY_BUZZ_STAT_LABELS = [
    "Unique Visitors",
    "Page Views",
    "Registered Guests",
    "Visitors Today",
]


def test_home_hero_and_party_buzz_tiles_render(page, base_url, reset_db, app_config):
    goto(page, base_url, "Home")

    expect(page.get_by_text(app_config.EVENT_NAME, exact=False).first).to_be_visible(timeout=10000)
    expect(page.get_by_text(app_config.EVENT_TAGLINE, exact=False).first).to_be_visible(timeout=10000)

    expect(page.get_by_text("Party Buzz", exact=False).first).to_be_visible(timeout=10000)
    for label in PARTY_BUZZ_STAT_LABELS:
        expect(page.get_by_text(label, exact=True)).to_be_visible(timeout=10000)


def test_home_party_buzz_registrations_chart_renders_once_there_are_registrations(
    page, base_url, reset_db, app_config
):
    """The registrations-by-day bar chart (also moved here from the old
    admin Overview tab) only renders once there's at least one guest --
    before that it shows an info fallback ("No registrations yet").

    The check-ins-by-hour chart is deliberately NOT asserted in its
    real-bar-rendered state: it only has data for check-ins whose
    checkin_time falls on the actual `config.EVENT_DATE`, which a test
    can't manufacture without changing the app's clock (the event date is
    always far in the future relative to whenever this suite runs). So
    it's covered via its own equally-real empty-state message instead.
    """
    reset_db.register_guest("Buzz Guest", "buzzguest@example.com", "", 1, "", "ZELLE-BUZZ00001")

    # Party Buzz reads through @st.cache_data(ttl=30). Seeding straight into
    # the DB (rather than registering through the form, which clears that
    # cache) leaves the app holding a pre-seed value, so wait the TTL out
    # before asserting. This is a real, bounded synchronisation point, not a
    # hopeful sleep.
    page.wait_for_timeout(31000)

    goto(page, base_url, "Home")

    expect(page.get_by_text("Registrations by day", exact=False)).to_be_visible(timeout=10000)
    expect(page.get_by_text("No registrations yet", exact=False)).to_have_count(0)
    expect(page.locator("[data-testid='stVegaLiteChart']").first).to_be_visible(timeout=10000)

    expect(
        page.get_by_text(
            f"Check-ins will show up here live once doors open on {app_config.EVENT_DATE_SHORT}.",
            exact=False,
        )
    ).to_be_visible(timeout=10000)


def test_home_nav_cards_navigate_to_correct_pages(page, base_url, reset_db):
    for button_pattern, heading_pattern in NAV_CARDS:
        goto(page, base_url, "Home")  # start fresh from Home each time
        page.get_by_role("button", name=button_pattern).click()
        expect(page.get_by_role("heading", name=heading_pattern, level=1)).to_be_visible(timeout=10000)


def test_home_renders_the_configured_photos_and_tiered_sponsors(
    page, base_url, reset_db, app_config
):
    """Whatever is in config.PHOTOS / config.SPONSORS actually reaches the
    page — every photo tile, every tier heading, and no broken images.

    Images are inlined as data URIs, so a wrong path doesn't 404 loudly; it
    just silently disappears. This is what catches that.
    """
    if not (app_config.PHOTOS or app_config.SPONSORS):
        pytest.skip("nothing configured — covered by the placeholder test instead")

    goto(page, base_url, "Home")

    if app_config.PHOTOS:
        expect(page.locator(".photo-card")).to_have_count(len(app_config.PHOTOS), timeout=15000)
        for photo in app_config.PHOTOS:
            if photo.get("caption"):
                expect(page.get_by_text(photo["caption"], exact=False).first).to_be_visible(
                    timeout=10000
                )

    if app_config.SPONSORS:
        expect(page.locator(".sponsor-card")).to_have_count(
            len(app_config.SPONSORS), timeout=15000
        )
        for sponsor in app_config.SPONSORS:
            expect(page.get_by_text(sponsor["name"], exact=False).first).to_be_visible(
                timeout=10000
            )
        # Tiers are grouped under headings, best first, and exactly one tier
        # is rendered as the featured row.
        tiers = [s.get("tier") for s in app_config.SPONSORS if s.get("tier")]
        headings = page.locator(".sponsor-tier-heading")
        expect(headings).to_have_count(len(dict.fromkeys(tiers)), timeout=10000)
        expect(page.locator(".sponsor-grid.is-featured-row")).to_have_count(1)

    broken = page.evaluate(
        "[...document.images].filter(i => i.complete && i.naturalWidth === 0).length"
    )
    assert broken == 0, f"{broken} image(s) failed to load on Home"


def test_home_photos_and_sponsors_show_placeholders_while_unconfigured(
    page, base_url, reset_db, app_config
):
    """Both sections render whether or not there is content to put in them.

    config.PHOTOS / config.SPONSORS ship empty and are expected to stay that
    way until the organiser fills them in, so the state that actually gets
    deployed is this one — the sections must read as "not yet", never as a
    gap or a broken image. Guarded on the config being empty so that adding
    real photos later turns this into a skip rather than a false failure.
    """
    if app_config.PHOTOS or app_config.SPONSORS:
        pytest.skip("PHOTOS/SPONSORS are configured — the placeholder path no longer applies")

    goto(page, base_url, "Home")

    expect(page.get_by_text("Photos", exact=False).first).to_be_visible(timeout=10000)
    expect(page.get_by_text("Photos are on the way", exact=False)).to_be_visible(timeout=10000)

    expect(page.get_by_text("Our Sponsors", exact=False).first).to_be_visible(timeout=10000)
    expect(page.get_by_text("Sponsor lineup coming soon", exact=False)).to_be_visible(timeout=10000)

    # A placeholder must never leave a broken <img> behind.
    expect(page.locator(".photo-grid")).to_have_count(0)
    expect(page.locator(".sponsor-grid")).to_have_count(0)
