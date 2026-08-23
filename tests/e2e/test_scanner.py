"""Flows 6-8: scanner lookup (by QR / email / phone / numeric id), the
confirm-before-check-in step, double check-in, invalid code, wristband
tracking, and the check-in time-window gate (PART 1:
`utils.check_in_by_code` / `utils.checkin_status`).

The door flow is two steps by design: a search only ever *finds* someone,
and a second deliberate press checks them in. Staff search by phone far more
often than anything else (guests don't remember which email address their QR
code went to), and a phone number identifies a booking, not a person — so
the details have to be confirmed against whoever is standing there.

Every test that actually performs a check-in through the Scanner UI uses
the `force_checkin_open` fixture, since the default 'auto' mode is closed
until 2h before the real event date (always far in the future relative to
whenever this suite runs)."""
from playwright.sync_api import expect

from .helpers import SCANNER_LOOKUP_FIELD, goto, scanner_checkin, scanner_find


def test_scanner_checkin_by_qr_code_then_already_checked_in(page, base_url, reset_db, seed_guest, force_checkin_open):
    guest = seed_guest(name="Scan Qr Guest", email="scanqr@example.com",
                        ticket_count=2, zelle_ref="ZELLE-SCANQR01")

    goto(page, base_url, "Scanner")
    scanner_checkin(page, guest["qr_code"])

    # exact=True: the guest name also appears (non-exact) inside the
    # welcome message and the audio-announcement caption on the same card,
    # which would otherwise be a Playwright strict-mode multi-match.
    expect(page.get_by_text("Scan Qr Guest", exact=True)).to_be_visible(timeout=10000)
    # The literal "✅ Checked In" status label, not the "Checked In" stat
    # tile that's also on this page -- the emoji prefix disambiguates them.
    expect(page.get_by_text("✅ Checked In", exact=False)).to_be_visible(timeout=10000)

    updated = reset_db.get_guest(guest["id"])
    assert updated["checked_in"] is True
    assert updated["checkin_time"] is not None

    # Scan the same guest again -> "already checked in" path, no state
    # change, and no confirm button to press a second time.
    page.get_by_role("button", name="🔄 Scan Next Guest").click()
    expect(page.get_by_label(SCANNER_LOOKUP_FIELD)).to_be_visible(timeout=8000)
    scanner_find(page, guest["qr_code"])

    expect(page.get_by_text("Already checked in at", exact=False)).to_be_visible(timeout=10000)
    expect(page.get_by_role("button", name="✅ Confirm & Check In")).to_have_count(0)
    still = reset_db.get_guest(guest["id"])
    assert still["checked_in"] is True


def test_scanner_checkin_by_email(page, base_url, reset_db, seed_guest, force_checkin_open):
    guest = seed_guest(name="Scan Email Guest", email="scanemail@example.com",
                        zelle_ref="ZELLE-SCANEML1")

    goto(page, base_url, "Scanner")
    scanner_checkin(page, guest["email"])

    expect(page.get_by_text("Scan Email Guest", exact=True)).to_be_visible(timeout=10000)
    assert reset_db.get_guest(guest["id"])["checked_in"] is True


def test_scanner_checkin_by_numeric_id(page, base_url, reset_db, seed_guest, force_checkin_open):
    guest = seed_guest(name="Scan Id Guest", email="scanid@example.com",
                        zelle_ref="ZELLE-SCANID001")

    goto(page, base_url, "Scanner")
    scanner_checkin(page, str(guest["id"]))

    expect(page.get_by_text("Scan Id Guest", exact=True)).to_be_visible(timeout=10000)
    assert reset_db.get_guest(guest["id"])["checked_in"] is True


def test_scanner_lookup_by_phone_shows_details_and_checks_nobody_in(
    page, base_url, reset_db, seed_guest, force_checkin_open
):
    """The reason the flow is two steps: staff search by phone, and the
    search alone must not admit anyone. Every identifying detail is on
    screen to confirm against, including how many wristbands are owed."""
    guest = seed_guest(name="Phone Door Guest", email="phonedoor@example.com",
                        phone="+1-555-707-1234", ticket_count=3,
                        zelle_ref="ZELLE-PHDOOR001")

    goto(page, base_url, "Scanner")
    scanner_find(page, "(555) 707-1234")

    expect(page.get_by_text("Phone Door Guest", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_text("phonedoor@example.com", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_text("+1-555-707-1234", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_text("Not checked in yet", exact=False)).to_be_visible(timeout=10000)
    # 3 tickets => 3 wristbands, stated rather than left for staff to infer
    expect(page.get_by_text("Wristbands", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_text("hand over 3 wristbands", exact=False)).to_be_visible(timeout=10000)

    # The whole point: found, but untouched until someone confirms.
    pending = reset_db.get_guest(guest["id"])
    assert pending["checked_in"] is False
    assert pending["checkin_time"] is None

    page.get_by_role("button", name="✅ Confirm & Check In").click()
    expect(page.get_by_text("✅ Checked In", exact=False)).to_be_visible(timeout=10000)
    assert reset_db.get_guest(guest["id"])["checked_in"] is True


def test_scanner_search_for_someone_else_discards_the_match(
    page, base_url, reset_db, seed_guest, force_checkin_open
):
    """Wrong person on screen -> staff back out, and nothing was recorded."""
    guest = seed_guest(name="Wrong Match Guest", email="wrongmatch@example.com",
                        phone="+1-555-808-4321", zelle_ref="ZELLE-WRONGM001")

    goto(page, base_url, "Scanner")
    scanner_find(page, "555-808-4321")
    expect(page.get_by_text("Wrong Match Guest", exact=True)).to_be_visible(timeout=10000)

    page.get_by_role("button", name="🔍 Search for Someone Else").click()

    expect(page.get_by_text("Wrong Match Guest", exact=True)).to_have_count(0, timeout=10000)
    expect(page.get_by_label(SCANNER_LOOKUP_FIELD)).to_be_visible(timeout=8000)
    assert reset_db.get_guest(guest["id"])["checked_in"] is False


def test_scanner_invalid_code_shows_error(page, base_url, reset_db, force_checkin_open):
    goto(page, base_url, "Scanner")
    scanner_find(page, "totally-bogus-code-does-not-exist")
    expect(page.get_by_text("No guest found", exact=False)).to_be_visible(timeout=10000)


def test_wristband_mark_band_given_after_checkin(page, base_url, reset_db, seed_guest, force_checkin_open):
    guest = seed_guest(name="Band Guest", email="bandguest@example.com",
                        zelle_ref="ZELLE-BANDG0001")

    goto(page, base_url, "Scanner")
    scanner_checkin(page, guest["qr_code"])
    band_button = page.get_by_role("button", name="✓ Mark 1 Wristband Given")
    expect(band_button).to_be_visible(timeout=10000)

    assert reset_db.get_guest(guest["id"])["band_given"] is False

    # NOTE: not asserting the "Band marked as given" success text here.
    # `_mark_band_given()` in streamlit_app.py calls st.success(message)
    # immediately followed by st.rerun() in the same function -- the rerun
    # appears to supersede the frame before the success message is ever
    # flushed to the browser, so it never becomes visible (confirmed: DB
    # state below still updates correctly). Filed as a real bug in the
    # test-suite report; the task's acceptance criterion for this flow is
    # the DB assertion, which we do check.
    band_button.click()
    page.wait_for_timeout(2000)

    assert reset_db.get_guest(guest["id"])["band_given"] is True


# ── Check-in window gate (PART 1) ───────────────────────────────────────

def test_scanner_gate_closed_shows_notice_hides_manual_entry_and_leaves_guest_untouched(
    page, base_url, reset_db, seed_guest
):
    """Positive coverage of the gate itself (no `force_checkin_open` here):
    default mode is 'auto' and the real event date is always far in the
    future relative to whenever this suite runs, so the window is closed.
    The Scanner page must show the "opens at ..." notice, must NOT render
    the manual-entry input at all, and an attempted check-in against the
    closed window must leave the guest row completely untouched.

    The UI intentionally gives a guest nothing to click while closed, so
    the "attempted check-in" half of this test calls
    `utils.check_in_by_code()` directly (service-level) -- this is exactly
    the server-side control the UI gate is a convenience wrapper around."""
    guest = seed_guest(name="Gate Closed Guest", email="gateclosed@example.com",
                        zelle_ref="ZELLE-GATECL01")

    assert reset_db.get_checkin_mode() == reset_db.CHECKIN_MODE_AUTO
    assert reset_db.checkin_status()["open"] is False

    goto(page, base_url, "Scanner")
    expect(page.get_by_text("Check-in isn't open yet", exact=False)).to_be_visible(timeout=10000)
    expect(page.get_by_text("opens", exact=False)).to_be_visible(timeout=10000)
    expect(page.get_by_label(SCANNER_LOOKUP_FIELD)).to_have_count(0)
    expect(page.get_by_role("button", name="🔍 Find Guest")).to_have_count(0)

    result = reset_db.check_in_by_code(guest["qr_code"])
    assert result["status"] == "not_open"
    assert result["guest"] is None

    untouched = reset_db.get_guest(guest["id"])
    assert untouched["checked_in"] is False
    assert untouched["checkin_time"] is None
