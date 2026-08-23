"""Flow 12: every page renders with no horizontal overflow at a 390x844
mobile viewport."""
import pytest

from .conftest import ADMIN_PASSWORD
from .helpers import assert_no_horizontal_overflow, goto, login_admin, scanner_checkin


@pytest.mark.slow
def test_no_horizontal_overflow_on_any_page_at_mobile_viewport(
    mobile_page, base_url, reset_db, seed_guest, force_checkin_open
):
    # Seed a guest so the Admin guest table has real content to render on a
    # narrow screen too, not just its empty state. Checked in via the UI
    # below (rather than directly) so we also exercise the denser
    # post-checkin success card (with its "Mark Band Given" button and
    # audio-announcement notice) at this viewport.
    guest = seed_guest(name="Mobile Overflow Guest", email="mobileoverflow@example.com",
                        ticket_count=3, zelle_ref="ZELLE-MOBILE001")

    page = mobile_page

    for target in ["Home", "Register", "My QR", "Scanner", "Admin"]:
        goto(page, base_url, target, settle_ms=1200)
        assert_no_horizontal_overflow(page)

    # Also check the Scanner's post-checkin result card and the logged-in
    # Admin dashboard (tabs + guest table), which only render after further
    # interaction and are the most layout-dense states in the app.
    goto(page, base_url, "Scanner", settle_ms=1200)
    scanner_checkin(page, guest["qr_code"])
    page.wait_for_timeout(1000)
    assert_no_horizontal_overflow(page)

    goto(page, base_url, "Admin", settle_ms=1200)
    login_admin(page, ADMIN_PASSWORD)
    page.wait_for_timeout(1500)
    assert_no_horizontal_overflow(page)

    page.get_by_role("tab", name="Guests").click()
    page.wait_for_timeout(1000)
    assert_no_horizontal_overflow(page)
