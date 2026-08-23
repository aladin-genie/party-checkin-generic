"""Flows 9-10: admin authentication (wrong password / correct password /
lockout), the redesigned admin dashboard (Overview stats + CSV, the new
Check-in Window control, and the Guests `st.data_editor` grid).

The Guests tab's spreadsheet (PART 4/5) is a canvas-rendered grid
(glide-data-grid) whose Checked In / Band Given / Delete checkboxes have no
interactable DOM element -- confirmed by hand against the running app: the
grid's hidden accessibility-mirror `<td>` cells report text via
`get_by_text` but time out on `.click()` ("element is not visible"), and
there is no other selector for an individual cell. So coverage here is
split in two:

  - UI-level (this file): the editor renders, its column headers and row
    content are present, the Save button exists and a no-op Save round-trips
    cleanly, and the search box actually filters which rows the grid holds.
  - Service-level (this file, bottom section): the real mutation logic --
    batching check-ins/bands, deleting, and bypassing the check-in window --
    is exercised directly against `utils.apply_guest_changes()`, which is
    exactly the function the Save button's `st.button` handler calls with
    the grid's edited rows.
"""
import pytest
from playwright.sync_api import expect

from .conftest import ADMIN_PASSWORD
from .helpers import fill_and_blur, goto, login_admin, scanner_checkin, select_checkin_mode


# ── Flow 9: admin auth ──────────────────────────────────────────────────

def test_admin_auth_wrong_password_rejected(page, base_url, reset_db):
    goto(page, base_url, "Admin")
    login_admin(page, "definitely-the-wrong-password")
    expect(page.get_by_text("Incorrect password", exact=False)).to_be_visible(timeout=10000)


def test_admin_auth_correct_password_grants_access(page, base_url, reset_db):
    goto(page, base_url, "Admin")
    login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_role("tab", name="Overview")).to_be_visible(timeout=10000)
    expect(page.get_by_role("tab", name="Guests")).to_be_visible()
    expect(page.get_by_role("tab", name="Check-ins")).to_be_visible()


@pytest.mark.slow
def test_admin_auth_lockout_after_five_failed_attempts(page, base_url, reset_db):
    goto(page, base_url, "Admin")
    for _ in range(5):
        login_admin(page, "still-wrong")
        page.wait_for_timeout(500)

    expect(page.get_by_text("Too many attempts", exact=False)).to_be_visible(timeout=10000)

    # The lockout timer is set partway through the 5th submit's own run --
    # after the login form had already been rendered earlier in that same
    # run -- so the form is still on screen this instant. One more
    # interaction forces a fresh run, where the top-of-function lockout
    # check now short-circuits before the form is rendered at all. Using
    # the *correct* password here also proves lockout blocks it too.
    if page.get_by_label("Admin Password").count():
        login_admin(page, ADMIN_PASSWORD)
        page.wait_for_timeout(500)

    expect(page.get_by_text("Too many attempts", exact=False)).to_be_visible(timeout=10000)
    expect(page.get_by_label("Admin Password")).to_have_count(0)
    expect(page.get_by_role("tab", name="Overview")).to_have_count(0)


# ── Flow 10a: Overview stats + CSV export + Check-ins tab ───────────────

@pytest.mark.slow
def test_admin_overview_stats_and_csv_export(page, base_url, reset_db):
    # 2 tickets + 1 + 1 = 4 tickets @ $30 => $120.00 revenue.
    reset_db.register_guest("Filtera One", "filtera.one@example.com", "", 2, "", "ZELLE-FILTERA01")
    reset_db.register_guest("Filterb Two", "filterb.two@example.com", "", 1, "", "ZELLE-FILTERB01")
    reset_db.register_guest("Filterc Three", "filterc.three@example.com", "", 1, "", "ZELLE-FILTERC01")

    goto(page, base_url, "Admin")
    login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_role("tab", name="Overview")).to_be_visible(timeout=10000)

    # The Overview tab's stat tiles are read through st.cache_data(ttl=10).
    # This Streamlit process is shared across the whole test session, so an
    # earlier test may have already populated that cache before our direct
    # DB seed above ran. Wait out the TTL, then reload so the read we assert
    # on is guaranteed to reflect the state we just seeded, not a stale one.
    page.wait_for_timeout(11000)
    goto(page, base_url, "Admin")
    if page.get_by_label("Admin Password").count():
        login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_role("tab", name="Overview")).to_be_visible(timeout=10000)

    expect(page.get_by_text("$120.00", exact=True)).to_be_visible(timeout=10000)  # Revenue (est.)
    # NOTE: the Overview tab no longer shows Traffic tiles, the two charts,
    # or an "Avg Tickets" stat -- those moved to the Home page's "Party
    # Buzz" section (see test_home.py) or were dropped outright ("Avg
    # Tickets" is no longer rendered anywhere in the app).

    # ── Guests tab: table lists seeded guests ──────────────────────────
    page.get_by_role("tab", name="Guests").click()
    page.wait_for_timeout(1000)

    # st.data_editor renders through a canvas grid with a visually-hidden
    # accessibility mirror table: its cell text is findable via get_by_text
    # but is never Playwright-"visible", so guest-table assertions use
    # .count()/to_have_count(), not to_be_visible().
    expect(page.get_by_text("Filtera One", exact=False).first).to_be_attached(timeout=10000)
    assert page.get_by_text("Filtera One", exact=False).count() >= 1
    assert page.get_by_text("Filterb Two", exact=False).count() >= 1
    assert page.get_by_text("Filterc Three", exact=False).count() >= 1

    # ── CSV export ───────────────────────────────────────────────────────
    with page.expect_download(timeout=10000) as dl_info:
        page.get_by_role("button", name="⬇ Download CSV").click()
    csv_path = dl_info.value.path()
    csv_content = open(csv_path, "r", encoding="utf-8").read()
    assert "Filtera One" in csv_content
    assert "filtera.one@example.com" in csv_content

    # ── Check-ins tab renders ───────────────────────────────────────────
    # The Overview tab no longer has a "no check-ins yet" chart caption
    # (that chart moved to the Home page entirely -- see test_home.py), so
    # there's nothing on the concurrently-mounted Overview panel this could
    # collide with; match the tab's full empty-state sentence exactly.
    page.get_by_role("tab", name="Check-ins").click()
    expect(
        page.get_by_text("No check-ins yet. They'll appear here as guests arrive.", exact=True)
    ).to_be_visible(timeout=10000)


# ── Flow 10b: Check-in Window control (PART 1 admin side) ───────────────

def test_admin_checkin_window_control_open_now_persists_and_enables_scanner(
    page, base_url, reset_db, seed_guest
):
    """Flipping the radio to "Open now" persists to app_settings (verified
    both via the service layer and by reloading the Admin page) and makes
    the Scanner page immediately usable for a real check-in."""
    guest = seed_guest(name="Window Guest", email="windowguest@example.com",
                        zelle_ref="ZELLE-WINDOW001")

    assert reset_db.get_checkin_mode() == reset_db.CHECKIN_MODE_AUTO

    goto(page, base_url, "Admin")
    login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_role("tab", name="Overview")).to_be_visible(timeout=10000)

    expect(page.get_by_text("CLOSED", exact=True)).to_be_visible(timeout=10000)

    select_checkin_mode(page, "Open now")
    page.wait_for_timeout(1500)

    expect(page.get_by_text("OPEN", exact=True)).to_be_visible(timeout=10000)
    assert reset_db.get_checkin_mode() == reset_db.CHECKIN_MODE_OPEN

    # Reload to prove the mode is a persisted setting, not just local UI
    # state -- a fresh navigation gets a brand-new Streamlit session.
    goto(page, base_url, "Admin")
    if page.get_by_label("Admin Password").count():
        login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_text("OPEN", exact=True)).to_be_visible(timeout=10000)

    # Scanner is now usable: the manual-entry input renders and a real
    # check-in succeeds and is persisted.
    goto(page, base_url, "Scanner")
    scanner_checkin(page, guest["qr_code"])
    expect(page.get_by_text("Window Guest", exact=True)).to_be_visible(timeout=10000)
    assert reset_db.get_guest(guest["id"])["checked_in"] is True


# ── Flow 10c: Guests tab data_editor -- UI-level coverage only ──────────

def test_admin_guests_tab_editor_renders_columns_search_and_save_button(page, base_url, reset_db):
    """UI-driven coverage of the Guests spreadsheet: the editor renders,
    its expected column headers and row content are present, the search
    box filters which rows it holds, and the Save button exists and a
    no-op Save (no cells ever touched) round-trips without mutating
    anything. Toggling the grid's own checkboxes is NOT covered here -- see
    the module docstring and the service-level tests below."""
    reset_db.register_guest("Grid Alpha", "grid.alpha@example.com", "+1-555-311-0001", 2, "Kid One\nKid Two", "ZELLE-GRIDALPHA1")
    reset_db.register_guest("Grid Beta", "grid.beta@example.com", "+1-555-311-0002", 1, "", "ZELLE-GRIDBETA01")

    goto(page, base_url, "Admin")
    login_admin(page, ADMIN_PASSWORD)
    page.get_by_role("tab", name="Guests").click()
    page.wait_for_timeout(1200)

    expect(page.locator("div[data-testid='stDataFrame']").first).to_be_visible(timeout=10000)

    for header in ["Name", "Email", "Phone", "Tickets", "Additional Guests", "Checked In", "Band Given", "Delete"]:
        assert page.get_by_text(header, exact=True).count() >= 1, f"missing column header {header!r}"

    # st.data_editor paints its cells on a <canvas>; unlike st.dataframe it
    # exposes no hidden accessibility mirror, so cell TEXT is simply not in the
    # DOM and cannot be asserted on. The app's own row-count caption is real
    # DOM text, so use that as the observable proxy for editor contents.
    expect(page.get_by_text("2 of 2 guests shown", exact=False)).to_be_visible(timeout=10000)

    save_button = page.get_by_role("button", name="Save changes", exact=False)
    expect(save_button).to_be_visible(timeout=8000)

    # ── search filters the editor's row count ───────────────────────────
    search_label = "🔍 Search by name, email, phone, or Zelle ref"
    fill_and_blur(page, search_label, "Grid Alpha")
    expect(page.get_by_text("1 of 2 guests shown", exact=False)).to_be_visible(timeout=10000)

    # Phone search matches on digits, so an organiser can type the number the
    # way the guest reads it out. Each step below changes the expected count,
    # so the assertion can't pass on the previous step's stale caption.
    fill_and_blur(page, search_label, "555-311")
    expect(page.get_by_text("2 of 2 guests shown", exact=False)).to_be_visible(timeout=10000)

    fill_and_blur(page, search_label, "5553110002")
    expect(page.get_by_text("1 of 2 guests shown", exact=False)).to_be_visible(timeout=10000)

    fill_and_blur(page, search_label, "")
    page.wait_for_timeout(700)

    # ── Save with no edits is a harmless no-op ──────────────────────────
    save_button.click()
    expect(page.get_by_text("No changes to apply.", exact=True)).to_be_visible(timeout=10000)
    assert reset_db.get_guest_by_email("grid.alpha@example.com")["checked_in"] is False
    assert reset_db.get_guest_by_email("grid.beta@example.com")["checked_in"] is False


# ── Flow 10c: Danger Zone backup-before-reset ───────────────────────────

def test_admin_danger_zone_backup_downloads_zip_and_per_table_csvs(page, base_url, reset_db):
    """The backup has to actually produce files — it is the only undo the
    reset has. Also covers the reference list of tables/views rendered
    alongside it."""
    import io
    import zipfile

    reset_db.register_guest("Backup Bob", "backup.bob@example.com", "+1-555-300-0000",
                            2, "", "ZELLE-BACKUP001")

    goto(page, base_url, "Admin")
    login_admin(page, ADMIN_PASSWORD)
    expect(page.get_by_role("tab", name="Overview")).to_be_visible(timeout=10000)

    page.get_by_text("Danger Zone", exact=False).first.click()
    page.wait_for_timeout(700)

    # Before preparing anything, the operator is told a backup is missing.
    expect(page.get_by_text("No backup prepared in this session", exact=False)).to_be_visible(timeout=10000)

    page.get_by_role("button", name="📦 Prepare backup").click()
    expect(page.get_by_role("button", name="⬇ Download full backup (ZIP)")).to_be_visible(timeout=15000)

    with page.expect_download(timeout=15000) as dl_info:
        page.get_by_role("button", name="⬇ Download full backup (ZIP)").click()
    with zipfile.ZipFile(io.BytesIO(open(dl_info.value.path(), "rb").read())) as archive:
        names = set(archive.namelist())
        assert names == {f"{t}.csv" for t in reset_db.BACKUP_TABLES} | {"README.txt"}
        guests_csv = archive.read("guests.csv").decode("utf-8")
        assert "Backup Bob" in guests_csv
        assert "backup.bob@example.com" in guests_csv
        assert "vw_registrations_summary" in archive.read("README.txt").decode("utf-8")

    # Per-table CSVs are offered individually too (a phone can't open a ZIP).
    with page.expect_download(timeout=15000) as dl_info:
        page.get_by_role("button", name="⬇ guests.csv", exact=False).click()
    assert "Backup Bob" in open(dl_info.value.path(), "r", encoding="utf-8").read()

    # The "what can I query" reference renders every table and view name.
    for table, _desc in reset_db.DATA_TABLES:
        assert page.get_by_text(table, exact=False).count() >= 1
    for view, _desc in reset_db.REPORTING_VIEWS:
        assert page.get_by_text(view, exact=False).count() >= 1


# ── Service-level coverage of the real Guests-tab mutation logic ────────

def test_apply_guest_changes_service_layer_batches_checkin_and_band(reset_db, seed_guest):
    """Mirrors what Save changes does after the admin ticks Checked In on
    one row and both Checked In + Band Given on another, in a single pass."""
    g1 = seed_guest(name="Batch One", email="batchone@example.com", zelle_ref="ZELLE-BATCH0001")
    g2 = seed_guest(name="Batch Two", email="batchtwo@example.com", zelle_ref="ZELLE-BATCH0002")

    result = reset_db.apply_guest_changes([
        {"id": g1["id"], "checked_in": True, "band_given": True, "delete": False},
        {"id": g2["id"], "checked_in": True, "band_given": False, "delete": False},
    ])

    assert result == {"checked_in": 2, "band_given": 1, "deleted": 0}

    updated1 = reset_db.get_guest(g1["id"])
    updated2 = reset_db.get_guest(g2["id"])
    assert updated1["checked_in"] is True and updated1["band_given"] is True
    assert updated2["checked_in"] is True and updated2["band_given"] is False


def test_apply_guest_changes_service_layer_is_a_noop_for_unchanged_rows(reset_db, seed_guest):
    """checked_in/band_given are one-way (True -> True is a no-op, no
    "undo"). Re-applying an already-True row must not be counted again."""
    guest = seed_guest(name="Already Done", email="alreadydone@example.com", zelle_ref="ZELLE-ALREADY01")
    first = reset_db.apply_guest_changes([{"id": guest["id"], "checked_in": True, "band_given": True, "delete": False}])
    assert first == {"checked_in": 1, "band_given": 1, "deleted": 0}

    second = reset_db.apply_guest_changes([{"id": guest["id"], "checked_in": True, "band_given": True, "delete": False}])
    assert second == {"checked_in": 0, "band_given": 0, "deleted": 0}


def test_apply_guest_changes_service_layer_deletes_guest(reset_db, seed_guest):
    """Mirrors the admin ticking Delete and confirming: delete takes
    priority and the row disappears entirely."""
    guest = seed_guest(name="Delete Me", email="deleteme@example.com", zelle_ref="ZELLE-DELETE001")

    result = reset_db.apply_guest_changes([
        {"id": guest["id"], "checked_in": False, "band_given": False, "delete": True},
    ])

    assert result == {"checked_in": 0, "band_given": 0, "deleted": 1}
    assert reset_db.get_guest(guest["id"]) is None


def test_apply_guest_changes_service_layer_bypasses_checkin_window(reset_db, seed_guest):
    """The admin must always be able to check a guest in from the Guests
    tab, regardless of whether the public check-in window is currently
    closed (default 'auto' mode, event far in the future -> closed)."""
    guest = seed_guest(name="Window Bypass Guest", email="windowbypass@example.com",
                        zelle_ref="ZELLE-WINBYP001")
    assert reset_db.get_checkin_mode() == reset_db.CHECKIN_MODE_AUTO
    assert reset_db.checkin_status()["open"] is False

    result = reset_db.apply_guest_changes(
        [{"id": guest["id"], "checked_in": True, "band_given": False, "delete": False}]
    )
    assert result["checked_in"] == 1
    assert reset_db.get_guest(guest["id"])["checked_in"] is True
