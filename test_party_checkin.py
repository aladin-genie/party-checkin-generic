"""
Party Check-In System — Comprehensive Test Suite
Tests all backend features: DB, QR, email, security, CSV, check-in flow.
Run with: python test_party_checkin.py
"""

import os
import sys
import html
import io
import csv
import threading
import time
import zipfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import utils
from utils import (
    init_db,
    get_db,
    Guest,
    CheckInLog,
    PageVisit,
    SubmissionLog,
    AppSetting,
    get_stats,
    generate_qr_image,
    generate_qr_code,
    send_qr_email,
    send_qr_email_async,
    generate_welcome_announcement,
    generate_csv,
    verify_admin_password,
    admin_password_is_configured,
    audio_announcement_js,
    sanitize_email,
    sanitize_name,
    sanitize_phone,
    sanitize_zelle_ref,
    sanitize_guest_names,
    _sanitize_csv_field,
    _normalize_postgres_url,
    record_visit,
    get_visit_stats,
    record_submission,
    get_table_counts,
    get_engine,
    reset_all_data,
    export_backup,
    BACKUP_TABLES,
    DATA_TABLES,
    REPORTING_VIEWS,
    _reporting_view_sql,
    validate_registration,
    register_guest,
    check_in_by_code,
    find_guest_by_code,
    check_in_guest,
    wristband_count,
    phone_input_mask_js,
    get_guest,
    mark_band_given,
    delete_guest,
    list_guests,
    get_recent_checkins,
    get_registration_daily_counts,
    get_event_day_hourly_checkins,
    format_dt,
    get_setting,
    set_setting,
    get_checkin_mode,
    set_checkin_mode,
    checkin_status,
    CHECKIN_MODE_AUTO,
    CHECKIN_MODE_OPEN,
    CHECKIN_MODE_CLOSED,
    resolve_image_src,
    gallery_photos,
    sponsor_list,
)
from datetime import datetime, timezone, timedelta

# We need to mock Streamlit for testing outside the app
import unittest
from unittest.mock import patch, MagicMock

import config
import theme

# Mock st.secrets before importing utils
mock_secrets = {
    "SECRET_KEY": "test-secret",
    "DATABASE_URL": "sqlite:///test_party.db",
    "ADMIN_PASSWORD": "testadmin123",
    "TICKET_PRICE_CENTS": "5000",
    "ZELLE_INFO": "test@zelle.com",
    "MAIL_USERNAME": "",
    "MAIL_PASSWORD": "",
}


def _guest_name(index: int) -> str:
    """A distinct, always-valid guest name for the Nth guest in a booking.

    sanitize_name() accepts letters and spaces only, so the suffix has to
    keep being letters past the 26th guest — "Guest A"…"Guest Z", then
    "Guest AA", "Guest AB", …. (A plain chr(65 + index) silently produced
    "Guest [" at index 26, which is exactly the sort of invalid name these
    tests are meant to prove gets rejected.) MAX_GUEST_NAMES is derived from
    config.MAX_TICKETS_PER_REGISTRATION, so this has to hold for whatever
    that cap is raised to.
    """
    label = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        label = chr(65 + rem) + label
    return f"Guest {label}"


class TestPartyCheckIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Patch st.secrets
        cls.secrets_patcher = patch('utils.st')
        cls.mock_st = cls.secrets_patcher.start()
        cls.mock_st.secrets = mock_secrets
        
        # Remove test DB if exists
        if os.path.exists("test_party.db"):
            os.remove("test_party.db")
        
        init_db()
    
    @classmethod
    def tearDownClass(cls):
        cls.secrets_patcher.stop()
        if os.path.exists("test_party.db"):
            os.remove("test_party.db")
    
    def setUp(self):
        # Clean up guests between tests
        session = get_db()
        session.query(CheckInLog).delete()
        session.query(Guest).delete()
        session.commit()
        session.close()
        # Force the check-in window open by default so existing check-in
        # tests don't depend on the real wall-clock date relative to the
        # (2026) event date. Tests that specifically exercise auto/closed
        # modes override this within their own body; tearDown() always
        # resets the persisted setting so tests stay order-independent.
        set_checkin_mode(CHECKIN_MODE_OPEN)

    def tearDown(self):
        # Remove any app_settings rows written during the test (checkin
        # mode override, etc.) so later tests aren't affected by leftover
        # state and the suite stays order-independent.
        session = get_db()
        session.query(AppSetting).delete()
        session.commit()
        session.close()

    def _register(self, name="Reg Guest", email="reg@test.com", phone="",
                   ticket_count=1, plus_one_name="", zelle_ref="ZELLE-DEFAULT01",
                   veg_count=0, non_veg_count=0):
        """Helper: create a guest via the service layer (returns the result dict)."""
        return register_guest(name, email, phone, ticket_count, plus_one_name, zelle_ref,
                               veg_count, non_veg_count)

    # ── Database Tests ──────────────────────────────────────────────────────
    
    def test_create_guest(self):
        session = get_db()
        guest = Guest(
            name="Test User",
            email="test@example.com",
            phone="+1-555-0100",
            ticket_count=2,
            zelle_ref="ZELLE-ABC123",
            qr_code=generate_qr_code(),
        )
        session.add(guest)
        session.commit()
        
        self.assertIsNotNone(guest.id)
        self.assertTrue(guest.qr_code.startswith("PARTY2026-"))
        self.assertFalse(guest.checked_in)
        session.close()
    
    def test_checkin_flow(self):
        session = get_db()
        guest = Guest(
            name="Alice",
            email="alice@example.com",
            ticket_count=1,
            zelle_ref="ZELLE-XYZ789",
            qr_code=generate_qr_code(),
        )
        session.add(guest)
        session.commit()
        
        # Check in
        guest.checked_in = True
        guest.checkin_time = datetime.now(timezone.utc).replace(tzinfo=None)
        log = CheckInLog(guest_id=guest.id, action="checkin", device_info="Test")
        session.add(log)
        session.commit()
        
        stats = get_stats()
        self.assertEqual(stats["total_guests"], 1)
        self.assertEqual(stats["checked_in"], 1)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["total_tickets"], 1)
        session.close()
    
    def test_band_given_flow(self):
        session = get_db()
        guest = Guest(
            name="Bob",
            email="bob@example.com",
            ticket_count=3,
            zelle_ref="ZELLE-999",
            qr_code=generate_qr_code(),
            checked_in=True,
            checkin_time=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(guest)
        session.commit()
        
        guest.band_given = True
        log = CheckInLog(guest_id=guest.id, action="band_given", device_info="Test")
        session.add(log)
        session.commit()
        
        stats = get_stats()
        self.assertEqual(stats["bands_distributed"], 1)
        session.close()
    
    # ── QR Code Tests ───────────────────────────────────────────────────────
    
    def test_qr_generation(self):
        guest = Guest(name="QR Test", email="qr@test.com", ticket_count=1, qr_code="TEST-QR-123")
        qr_bytes = generate_qr_image("TEST-QR-123")
        self.assertGreater(len(qr_bytes), 1000)  # PNG should be at least 1KB
        # Verify it's a valid PNG by checking magic bytes
        self.assertEqual(qr_bytes[:4], b'\x89PNG')
    
    def test_qr_code_uniqueness(self):
        codes = set()
        for _ in range(100):
            code = generate_qr_code()
            self.assertNotIn(code, codes)
            codes.add(code)
    
    # ── Stats Tests ─────────────────────────────────────────────────────────
    
    def test_stats_with_multiple_guests(self):
        session = get_db()
        for i in range(5):
            g = Guest(
                name=f"Guest{i}",
                email=f"guest{i}@test.com",
                ticket_count=i+1,
                zelle_ref=f"ZELLE-{i}",
                qr_code=generate_qr_code(),
            )
            session.add(g)
        session.commit()
        
        # Check in 2 guests
        guests = session.query(Guest).all()
        for g in guests[:2]:
            g.checked_in = True
            g.checkin_time = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        
        stats = get_stats()
        self.assertEqual(stats["total_guests"], 5)
        self.assertEqual(stats["checked_in"], 2)
        self.assertEqual(stats["pending"], 3)
        self.assertEqual(stats["total_tickets"], 15)  # 1+2+3+4+5
        self.assertEqual(stats["admitted_tickets"], 3)  # 1+2
        session.close()
    
    def test_stats_extended(self):
        session = get_db()
        guests_data = [
            ("Alice", 2, True, "Bob"),
            ("Charlie", 1, False, ""),
            ("Dave", 3, True, "Eve"),
        ]
        for name, tickets, checked, plus in guests_data:
            g = Guest(
                name=name,
                email=f"{name.lower()}@test.com",
                ticket_count=tickets,
                plus_one_name=plus,
                zelle_ref=f"ZELLE-{name}",
                qr_code=generate_qr_code(),
                checked_in=checked,
                checkin_time=datetime.now(timezone.utc).replace(tzinfo=None) if checked else None,
            )
            session.add(g)
        session.commit()
        
        stats = get_stats()
        self.assertEqual(stats["total_guests"], 3)
        self.assertEqual(stats["total_tickets"], 6)
        self.assertEqual(stats["checked_in"], 2)
        self.assertEqual(stats["plus_one_count"], 2)
        # Bookings that name somebody: 2. People actually named: also 2
        # (one each). Dave holds 3 tickets but names only 1 guest, so one
        # ticket on that booking has no name against it.
        self.assertEqual(stats["named_guests"], 2)
        self.assertEqual(stats["unnamed_tickets"], 1)
        self.assertEqual(stats["avg_tickets_per_guest"], 2.0)
        self.assertAlmostEqual(stats["checkin_percentage"], 66.7, places=1)
        self.assertEqual(stats["revenue"], 300.0)  # $100 + $50 + $150 for the three bookings
        session.close()

    def test_get_stats_reports_meal_totals_across_guests(self):
        session = get_db()
        session.add(Guest(
            name="Meal Guest A", email="mealstatsa@test.com", ticket_count=2,
            zelle_ref="ZELLE-MEALSTATA", qr_code=generate_qr_code(),
            veg_count=1, non_veg_count=1,
        ))
        session.add(Guest(
            name="Meal Guest B", email="mealstatsb@test.com", ticket_count=3,
            zelle_ref="ZELLE-MEALSTATB", qr_code=generate_qr_code(),
            veg_count=3, non_veg_count=0,
        ))
        session.commit()
        session.close()

        stats = get_stats()
        self.assertEqual(stats["veg_total"], 4)
        self.assertEqual(stats["non_veg_total"], 1)

    def test_visit_stats(self):
        # Record a few visits from different tokens
        record_visit("token-abc", "Home")
        record_visit("token-abc", "Register")
        record_visit("token-xyz", "Home")
        record_visit("token-xyz", "Admin")
        
        stats = get_visit_stats()
        self.assertEqual(stats["total_visits"], 4)
        self.assertEqual(stats["unique_visitors"], 2)
    
    # ── Security Tests ──────────────────────────────────────────────────────
    
    def test_csv_injection_prevention(self):
        malicious = "=cmd|' /C calc'!A0"
        sanitized = _sanitize_csv_field(malicious)
        self.assertTrue(sanitized.startswith("'"))
        self.assertIn("=cmd", sanitized)
    
    def test_csv_injection_safe_value(self):
        safe = "John Doe"
        sanitized = _sanitize_csv_field(safe)
        self.assertEqual(sanitized, "John Doe")
    
    def test_email_sanitization(self):
        self.assertEqual(sanitize_email("  Test@Example.COM  "), "test@example.com")
        self.assertEqual(sanitize_email("not-an-email"), "")
        self.assertEqual(sanitize_email(""), "")
    
    def test_name_sanitization(self):
        self.assertEqual(sanitize_name("  John   Doe  "), "John Doe")
        self.assertEqual(sanitize_name(""), "")
        # Control characters removed
        self.assertEqual(sanitize_name("John\x00Doe"), "JohnDoe")
        # Letters and spaces only
        self.assertEqual(sanitize_name("Mary Jane OConnor"), "Mary Jane OConnor")
        # Invalid: digits, symbols, hyphens, apostrophes
        self.assertEqual(sanitize_name("John123"), "")
        self.assertEqual(sanitize_name("John@Doe"), "")
        self.assertEqual(sanitize_name("Mary-Jane O'Connor"), "")
    
    def test_phone_sanitization(self):
        # Prefix-only stub sanitizes to empty; validate_registration turns that
        # into the "phone is required" error (phone is mandatory since Aug 2026)
        self.assertEqual(sanitize_phone("+1-"), "")
        # Formatted US number
        self.assertEqual(sanitize_phone("+1 (555) 123-4567"), "+1-555-123-4567")
        # Bare 10 digits
        self.assertEqual(sanitize_phone("5551234567"), "+1-555-123-4567")
        # 11 digits with the country code, unpunctuated
        self.assertEqual(sanitize_phone("15551234567"), "+1-555-123-4567")
        # Empty stays empty
        self.assertEqual(sanitize_phone(""), "")
        # Too few digits rejected
        self.assertEqual(sanitize_phone("123"), "")
        # Letters rejected
        self.assertEqual(sanitize_phone("+1-555-123-abc"), "")
        # Non-US length rejected
        self.assertEqual(sanitize_phone("+44 20 7946 0958"), "")

    def test_phone_sanitization_rejects_non_us(self):
        # A non-+1 country code that happens to leave 10 digits must not be
        # silently relabelled as a US number
        self.assertEqual(sanitize_phone("+44 7946 0958"), "")
        self.assertEqual(sanitize_phone("+91 9876543210"), "")
        # Area codes never start with 0 or 1 in the US
        self.assertEqual(sanitize_phone("0551234567"), "")
        self.assertEqual(sanitize_phone("1112223333"), "")
        # ...including once the +1 country code is stripped
        self.assertEqual(sanitize_phone("+1 (055) 123-4567"), "")
    
    def test_zelle_ref_sanitization(self):
        # Valid 8-30 character refs (uppercased, cleaned)
        self.assertEqual(sanitize_zelle_ref("ABC-12345678"), "ABC-12345678")
        self.assertEqual(sanitize_zelle_ref("  zelle-9876543210  "), "ZELLE-9876543210")
        # Invalid: too short
        self.assertEqual(sanitize_zelle_ref("ABC-123"), "")
        # Symbols removed, remaining valid
        self.assertEqual(sanitize_zelle_ref("ABC-123!@#45678"), "ABC-12345678")
    
    def test_plus_one_name_optional(self):
        # Optional plus-one name follows same rules as name
        self.assertEqual(sanitize_name("Alice Smith"), "Alice Smith")
        self.assertEqual(sanitize_name(""), "")
        self.assertEqual(sanitize_name("Bob123"), "")
    
    def test_admin_password_constant_time(self):
        self.assertTrue(verify_admin_password("testadmin123"))
        self.assertFalse(verify_admin_password("wrongpassword"))
        self.assertFalse(verify_admin_password(""))
    
    def test_audio_announcement_xss_prevention(self):
        malicious_name = '<script>alert("xss")</script>'
        text = generate_welcome_announcement(malicious_name, 1)
        js = audio_announcement_js(text)
        # The malicious script tag should be HTML-escaped in the JS string
        self.assertIn('&lt;script&gt;', js)
        self.assertIn('&lt;/script&gt;', js)
        # Raw unescaped script tag should NOT appear in the JSON string content
        # (the outer HTML <script> tags are legitimate)
        self.assertNotIn('<script>alert', js)
        self.assertNotIn('</script>!', js)
    
    # ── CSV Export Tests ────────────────────────────────────────────────────
    
    def test_csv_export(self):
        session = get_db()
        guest = Guest(
            name="CSV Test",
            email="csv@test.com",
            phone="+1-555-0000",
            ticket_count=2,
            zelle_ref="ZELLE-CSV123",
            qr_code=generate_qr_code(),
            checked_in=True,
            checkin_time=datetime.now(timezone.utc).replace(tzinfo=None),
            band_given=True,
        )
        session.add(guest)
        session.commit()
        session.close()
        
        csv_data = generate_csv()
        self.assertIn("CSV Test", csv_data)
        self.assertIn("csv@test.com", csv_data)
        self.assertIn("ZELLE-CSV123", csv_data)
        self.assertIn("Yes", csv_data)

    def test_generate_csv_carries_the_additional_guest_count(self):
        session = get_db()
        session.add(Guest(
            name="Counted Booking",
            email="csvcount@test.com",
            ticket_count=3,
            plus_one_name="Ann Lee\nBob Ray",
            zelle_ref="ZELLE-CSVCOUNT",
            qr_code=generate_qr_code(),
        ))
        session.commit()
        session.close()

        rows = list(csv.DictReader(io.StringIO(generate_csv())))
        row = next(r for r in rows if r["Email"] == "csvcount@test.com")
        # 3 tickets, 2 named guests — the count is its own column so the
        # organiser can sort/sum on it without parsing the name blob.
        self.assertEqual(row["Tickets"], "3")
        self.assertEqual(row["Additional Guests"], "2")
        # One spreadsheet line per guest: the stored newlines must not leak
        # into the cell and split the row.
        self.assertEqual(row["Additional Guest Names"], "Ann Lee, Bob Ray")
        self.assertEqual(len(rows), 1)

    def test_generate_csv_carries_the_meal_counts(self):
        session = get_db()
        session.add(Guest(
            name="Meal CSV Guest",
            email="mealcsv@test.com",
            ticket_count=3,
            plus_one_name="Ann Lee\nBob Ray",
            zelle_ref="ZELLE-MEALCSV",
            qr_code=generate_qr_code(),
            veg_count=2,
            non_veg_count=1,
        ))
        session.commit()
        session.close()

        rows = list(csv.DictReader(io.StringIO(generate_csv())))
        row = next(r for r in rows if r["Email"] == "mealcsv@test.com")
        self.assertEqual(row["Veg"], "2")
        self.assertEqual(row["Non-Veg"], "1")

    # ── Email Tests ─────────────────────────────────────────────────────────
    
    def test_email_without_credentials(self):
        # With empty MAIL_USERNAME, should return False
        guest = Guest(name="Email Test", email="email@test.com", ticket_count=1, qr_code="TEST")
        result = send_qr_email(guest)
        self.assertFalse(result)  # No SMTP credentials configured
    
    # ── Announcement Tests ────────────────────────────────────────────────
    
    def test_welcome_announcement_singular(self):
        text = generate_welcome_announcement("Alice", 1)
        self.assertIn("Alice", text)
        self.assertIn("1 ticket", text)
    
    def test_welcome_announcement_plural(self):
        text = generate_welcome_announcement("Bob", 3)
        self.assertIn("Bob", text)
        self.assertIn("3 tickets", text)

    # ── Submission Log Tests ──────────────────────────────────────────────

    def test_record_submission_validation_error(self):
        record_submission(
            name="Bad Name 123",
            email="not-an-email",
            phone="abc",
            ticket_count=2,
            plus_one_name="",
            zelle_ref="short",
            status="validation_error",
            errors="invalid name; invalid email; invalid Zelle reference",
        )
        session = get_db()
        try:
            log = session.query(SubmissionLog).order_by(SubmissionLog.id.desc()).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, "validation_error")
            self.assertIn("invalid name", log.errors)
            self.assertEqual(log.ticket_count, 2)
        finally:
            session.close()

    def test_record_submission_registered(self):
        record_submission(
            name="Alice Smith",
            email="alice@example.com",
            phone="+1-555-123-4567",
            ticket_count=1,
            plus_one_name="Bob Smith",
            zelle_ref="ZELLE12345678",
            status="registered",
            guest_id=42,
        )
        session = get_db()
        try:
            log = session.query(SubmissionLog).order_by(SubmissionLog.id.desc()).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, "registered")
            self.assertEqual(log.email, "alice@example.com")
            self.assertEqual(log.guest_id, 42)
        finally:
            session.close()

    # ── Service Layer: register_guest ───────────────────────────────────────

    def test_register_guest_success(self):
        result = self._register(
            name="Reg Success",
            email="regsuccess@test.com",
            phone="+1-555-000-1111",
            ticket_count=2,
            plus_one_name="Plus One",
            zelle_ref="ZELLE-REGSUCC1",
        )
        self.assertTrue(result["ok"])
        guest = result["guest"]
        self.assertIsInstance(guest, dict)
        self.assertIsNotNone(guest["id"])
        self.assertEqual(guest["email"], "regsuccess@test.com")
        self.assertEqual(guest["ticket_count"], 2)
        self.assertTrue(guest["qr_code"].startswith(config.qr_prefix() + "-"))

    def test_register_guest_duplicate_email(self):
        first = self._register(name="First", email="dupe@test.com", zelle_ref="ZELLE-DUPE1111")
        self.assertTrue(first["ok"])
        second = self._register(name="Second", email="dupe@test.com", zelle_ref="ZELLE-DUPE2222")
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "duplicate_email")

    def test_register_guest_ticket_count_coercion_falsy(self):
        # ticket_count=0 is falsy -> coerced to the default of 1
        result = self._register(name="Zero Tix", email="zerotix@test.com",
                                 ticket_count=0, zelle_ref="ZELLE-ZEROTIX1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["guest"]["ticket_count"], 1)

    def test_register_guest_persists_meal_counts(self):
        # register_guest doesn't re-validate (it trusts the caller), so this
        # only checks the values it's given are saved and read back correctly.
        result = self._register(
            name="Meal Counter",
            email="mealcounter@test.com",
            phone="+1-555-000-2222",
            ticket_count=4,
            plus_one_name="Ann Lee\nBob Ray\nCal Vue",
            zelle_ref="ZELLE-MEALCNT1",
            veg_count=3,
            non_veg_count=1,
        )
        self.assertTrue(result["ok"])
        guest = result["guest"]
        self.assertEqual(guest["veg_count"], 3)
        self.assertEqual(guest["non_veg_count"], 1)

    def test_register_guest_ticket_count_coercion_numeric_string(self):
        result = self._register(name="Str Tix", email="strtix@test.com",
                                 ticket_count="4", zelle_ref="ZELLE-STRTIX01")
        self.assertTrue(result["ok"])
        self.assertEqual(result["guest"]["ticket_count"], 4)

    # ── Ticket Capacity (config.max_total_tickets) ──────────────────────────
    # The venue's hard cap. Every test here pins the cap explicitly rather
    # than relying on the 225 default, so raising the real cap later doesn't
    # silently turn these into no-ops.

    def test_tickets_sold_sums_ticket_counts_not_guest_rows(self):
        self._register(name="Sum A", email="sum.a@test.com", ticket_count=3,
                       zelle_ref="ZELLE-SUMA1111")
        self._register(name="Sum B", email="sum.b@test.com", ticket_count=4,
                       zelle_ref="ZELLE-SUMB1111")
        self.assertEqual(utils.tickets_sold(), 7)

    def test_tickets_sold_is_zero_on_an_empty_table(self):
        self.assertEqual(utils.tickets_sold(), 0)

    def test_ticket_availability_reports_remaining(self):
        self._register(name="Avail", email="avail@test.com", ticket_count=8,
                       zelle_ref="ZELLE-AVAIL111")
        with patch.object(config, "max_total_tickets", return_value=10):
            availability = utils.ticket_availability()
        self.assertEqual(availability["cap"], 10)
        self.assertEqual(availability["sold"], 8)
        self.assertEqual(availability["remaining"], 2)
        self.assertFalse(availability["sold_out"])
        self.assertFalse(availability["unlimited"])

    def test_ticket_availability_sold_out_at_exactly_the_cap(self):
        self._register(name="Exact", email="exact@test.com", ticket_count=5,
                       zelle_ref="ZELLE-EXACT111")
        with patch.object(config, "max_total_tickets", return_value=5):
            availability = utils.ticket_availability()
        self.assertTrue(availability["sold_out"])
        self.assertEqual(availability["remaining"], 0)

    def test_ticket_availability_never_reports_negative_remaining(self):
        # The organiser can lower the cap below what's already sold.
        self._register(name="Over", email="over@test.com", ticket_count=9,
                       zelle_ref="ZELLE-OVER1111")
        with patch.object(config, "max_total_tickets", return_value=4):
            availability = utils.ticket_availability()
        self.assertEqual(availability["remaining"], 0)
        self.assertTrue(availability["sold_out"])

    def test_ticket_availability_cap_of_zero_means_unlimited(self):
        with patch.object(config, "max_total_tickets", return_value=0):
            availability = utils.ticket_availability()
        self.assertTrue(availability["unlimited"])
        self.assertFalse(availability["sold_out"])

    def test_ticket_availability_fails_open_when_the_count_raises(self):
        # A DB blip must not tell guests the party is sold out — see the
        # docstring on utils.ticket_availability.
        with patch.object(config, "max_total_tickets", return_value=50), \
             patch.object(utils, "tickets_sold", side_effect=RuntimeError("db down")):
            availability = utils.ticket_availability()
        self.assertTrue(availability["unlimited"])
        self.assertFalse(availability["sold_out"])

    def test_register_guest_refused_when_sold_out(self):
        self._register(name="Filler", email="filler@test.com", ticket_count=6,
                       zelle_ref="ZELLE-FILLER11")
        with patch.object(config, "max_total_tickets", return_value=6):
            result = self._register(name="Too Late", email="toolate@test.com",
                                    ticket_count=1, zelle_ref="ZELLE-TOOLATE1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "sold_out")
        self.assertEqual(result["remaining"], 0)
        self.assertIsNone(utils.get_guest_by_email("toolate@test.com"))

    def test_register_guest_refused_when_asking_for_more_than_remain(self):
        self._register(name="Filler2", email="filler2@test.com", ticket_count=8,
                       zelle_ref="ZELLE-FILLER22")
        with patch.object(config, "max_total_tickets", return_value=10):
            result = self._register(name="Greedy", email="greedy@test.com",
                                    ticket_count=5, zelle_ref="ZELLE-GREEDY11")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_enough_tickets")
        self.assertEqual(result["remaining"], 2)
        self.assertIn("2 tickets left", result["message"])
        self.assertIsNone(utils.get_guest_by_email("greedy@test.com"))

    def test_register_guest_allowed_up_to_exactly_the_cap(self):
        self._register(name="Filler3", email="filler3@test.com", ticket_count=7,
                       zelle_ref="ZELLE-FILLER33")
        with patch.object(config, "max_total_tickets", return_value=10):
            result = self._register(name="Last Three", email="lastthree@test.com",
                                    ticket_count=3, zelle_ref="ZELLE-LASTTHR1")
        self.assertTrue(result["ok"])
        self.assertEqual(utils.tickets_sold(), 10)

    def test_register_guest_uncapped_when_max_total_tickets_is_zero(self):
        with patch.object(config, "max_total_tickets", return_value=0):
            result = self._register(name="Uncapped", email="uncapped@test.com",
                                    ticket_count=500, zelle_ref="ZELLE-UNCAP111")
        self.assertTrue(result["ok"])
        self.assertEqual(result["guest"]["ticket_count"], 500)

    def test_register_guest_capacity_check_runs_after_duplicate_check(self):
        # A duplicate email is the more useful message of the two, and it
        # must still be reported even when the party is already full.
        self._register(name="Dupe Cap", email="dupecap@test.com", ticket_count=4,
                       zelle_ref="ZELLE-DUPECAP1")
        with patch.object(config, "max_total_tickets", return_value=4):
            result = self._register(name="Dupe Cap Again", email="dupecap@test.com",
                                    ticket_count=1, zelle_ref="ZELLE-DUPECAP2")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "duplicate_email")

    # ── Service Layer: find_guest_by_contact ────────────────────────────────
    # Guests are looked up by phone as well as email because an attendee may
    # have several email addresses and not remember which one they used.

    def test_get_guest_by_phone_normalizes_the_query(self):
        self._register(name="Phone Guest", email="phoneguest@test.com",
                       phone="+1-555-321-7654", zelle_ref="ZELLE-PHONE001")
        for typed in ("+1-555-321-7654", "5553217654", "(555) 321-7654", "1 555 321 7654"):
            found = utils.get_guest_by_phone(typed)
            self.assertIsNotNone(found, typed)
            self.assertEqual(found["email"], "phoneguest@test.com", typed)

    def test_get_guest_by_phone_blank_does_not_match_legacy_rows(self):
        # Rows created before phone was mandatory have phone="" — an
        # unparseable query must not match them (or each other)
        self._register(name="Legacy Guest", email="legacy@test.com",
                       phone="", zelle_ref="ZELLE-LEGACY01")
        self.assertIsNone(utils.get_guest_by_phone(""))
        self.assertIsNone(utils.get_guest_by_phone("not a number"))

    def test_get_guest_by_phone_returns_most_recent_registration(self):
        self._register(name="Shared One", email="shared1@test.com",
                       phone="+1-555-777-8888", zelle_ref="ZELLE-SHARED01")
        self._register(name="Shared Two", email="shared2@test.com",
                       phone="+1-555-777-8888", zelle_ref="ZELLE-SHARED02")
        found = utils.get_guest_by_phone("555-777-8888")
        self.assertEqual(found["email"], "shared2@test.com")

    def test_find_guest_by_contact_by_email_and_by_phone(self):
        self._register(name="Contact Guest", email="contact@test.com",
                       phone="+1-555-246-8100", zelle_ref="ZELLE-CONTACT1")
        for query in ("contact@test.com", "  Contact@Test.com ", "555-246-8100", "5552468100"):
            guest, error = utils.find_guest_by_contact(query)
            self.assertIsNone(error, query)
            self.assertEqual(guest["name"], "Contact Guest", query)

    def test_find_guest_by_contact_errors(self):
        # Blank
        guest, error = utils.find_guest_by_contact("   ")
        self.assertIsNone(guest)
        self.assertIn("email address or phone number", error)
        # Unparseable as either
        guest, error = utils.find_guest_by_contact("12345")
        self.assertIsNone(guest)
        self.assertIn("valid", error)
        # Well-formed but unknown — distinct from the "invalid input" message
        guest, error = utils.find_guest_by_contact("555-999-0000")
        self.assertIsNone(guest)
        self.assertIn("No guest found", error)
        guest, error = utils.find_guest_by_contact("nobody@test.com")
        self.assertIsNone(guest)
        self.assertIn("No guest found", error)

    def test_phone_digits_strips_formatting_and_country_code(self):
        self.assertEqual(utils.phone_digits("+1-555-123-4567"), "5551234567")
        self.assertEqual(utils.phone_digits("(555) 123-4567"), "5551234567")
        self.assertEqual(utils.phone_digits(""), "")
        self.assertEqual(utils.phone_digits(None), "")

    # ── Service Layer: find_guest_by_code / check_in_guest ──────────────────
    # The door flow is deliberately two steps: find the person, confirm the
    # details, then check them in.

    def test_find_guest_by_code_resolves_qr_email_phone_and_id(self):
        created = self._register(
            name="Door Guest", email="door@test.com", phone="+1-555-404-3030",
            ticket_count=3, zelle_ref="ZELLE-DOOR0001",
        )["guest"]

        for query in (created["qr_code"], "door@test.com", "DOOR@test.com",
                      "+1-555-404-3030", "5554043030", "(555) 404-3030",
                      str(created["id"])):
            found = find_guest_by_code(query)
            self.assertEqual(found["status"], "found", query)
            self.assertEqual(found["guest"]["id"], created["id"], query)

    def test_find_guest_by_code_does_not_check_anyone_in(self):
        created = self._register(name="Untouched Guest", email="untouched@test.com",
                                 phone="+1-555-404-4040", zelle_ref="ZELLE-UNTOUCH1")["guest"]

        find_guest_by_code("555-404-4040")

        still = get_guest(created["id"])
        self.assertFalse(still["checked_in"])
        self.assertIsNone(still["checkin_time"])

    def test_find_guest_by_code_not_found_and_blank_phone_rows(self):
        # A legacy row with phone="" must not be matched by an unparseable
        # query that sanitizes down to nothing
        self._register(name="Legacy Door", email="legacydoor@test.com",
                       phone="", zelle_ref="ZELLE-LEGDOOR1")
        for query in ("nobody@test.com", "555-000", "", "   "):
            result = find_guest_by_code(query)
            self.assertEqual(result["status"], "not_found", query)
            self.assertIsNone(result["guest"], query)

    def test_check_in_guest_by_id_then_already(self):
        created = self._register(name="Confirm Guest", email="confirm@test.com",
                                 phone="+1-555-404-5050", zelle_ref="ZELLE-CONFIRM1")["guest"]

        first = check_in_guest(created["id"])
        self.assertEqual(first["status"], "success")
        self.assertTrue(get_guest(created["id"])["checked_in"])

        second = check_in_guest(created["id"])
        self.assertEqual(second["status"], "already")
        self.assertIn("already checked in", second["message"])

    def test_check_in_guest_unknown_id(self):
        result = check_in_guest(999999)
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["guest"])

    def test_check_in_guest_respects_and_bypasses_the_window(self):
        created = self._register(name="Window Confirm", email="windowconfirm@test.com",
                                 phone="+1-555-404-6060", zelle_ref="ZELLE-WINCONF1")["guest"]
        set_checkin_mode(CHECKIN_MODE_CLOSED)

        blocked = check_in_guest(created["id"])
        self.assertEqual(blocked["status"], "not_open")
        self.assertFalse(get_guest(created["id"])["checked_in"])

        # ...but an organiser acting by hand always gets through
        allowed = check_in_guest(created["id"], bypass_window=True)
        self.assertEqual(allowed["status"], "success")
        self.assertTrue(get_guest(created["id"])["checked_in"])

    def test_shared_phone_resolves_to_the_most_recent_booking(self):
        """Two bookings on one number: the search must be deterministic, and
        the confirm step keys off the id staff actually saw."""
        older = self._register(name="Shared Older", email="sharedolder@test.com",
                               phone="+1-555-404-7070", zelle_ref="ZELLE-SHOLD001")["guest"]
        newer = self._register(name="Shared Newer", email="sharednewer@test.com",
                               phone="+1-555-404-7070", zelle_ref="ZELLE-SHNEW001")["guest"]

        found = find_guest_by_code("5554047070")
        self.assertEqual(found["guest"]["id"], newer["id"])

        # Staff who spot the wrong person can still check in the right one,
        # because confirmation goes by id rather than re-running the search.
        self.assertEqual(check_in_guest(older["id"])["status"], "success")
        self.assertTrue(get_guest(older["id"])["checked_in"])
        self.assertFalse(get_guest(newer["id"])["checked_in"])

    def test_check_in_by_code_also_accepts_a_phone_number(self):
        created = self._register(name="Code Phone", email="codephone@test.com",
                                 phone="+1-555-404-8080", zelle_ref="ZELLE-CODEPH01")["guest"]
        result = check_in_by_code("(555) 404-8080")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["guest"]["id"], created["id"])

    def test_wristband_count_is_one_per_ticket(self):
        self.assertEqual(wristband_count({"ticket_count": 4}), 4)
        self.assertEqual(wristband_count({"ticket_count": 1}), 1)
        # Never promise zero bands to someone standing at the door
        self.assertEqual(wristband_count({"ticket_count": 0}), 1)
        self.assertEqual(wristband_count({"ticket_count": None}), 1)
        self.assertEqual(wristband_count({}), 1)
        self.assertEqual(wristband_count({"ticket_count": "oops"}), 1)

    # ── Service Layer: check_in_by_code ─────────────────────────────────────

    def test_check_in_by_code_by_qr_code_success_then_already(self):
        reg = self._register(name="QR Flow", email="qrflow@test.com", zelle_ref="ZELLE-QRFLOW01")
        code = reg["guest"]["qr_code"]

        first = check_in_by_code(code)
        self.assertEqual(first["status"], "success")
        self.assertTrue(first["guest"]["checked_in"])

        second = check_in_by_code(code)
        self.assertEqual(second["status"], "already")
        self.assertIn("QR Flow", second["message"])

    def test_check_in_by_code_by_email(self):
        self._register(name="Email Flow", email="emailflow@test.com", zelle_ref="ZELLE-EMLFLOW1")
        result = check_in_by_code("emailflow@test.com")
        self.assertEqual(result["status"], "success")

    def test_check_in_by_code_by_numeric_id(self):
        reg = self._register(name="Id Flow", email="idflow@test.com", zelle_ref="ZELLE-IDFLOW01")
        gid = reg["guest"]["id"]
        result = check_in_by_code(str(gid))
        self.assertEqual(result["status"], "success")

    def test_check_in_by_code_not_found(self):
        result = check_in_by_code("totally-garbage-code-does-not-exist")
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["guest"])

    def test_check_in_by_code_already_with_null_checkin_time_does_not_raise(self):
        # A guest can end up checked_in=True with checkin_time=None (e.g. rows
        # edited outside the app). Resolving it a second time must return the
        # "already" status without raising AttributeError.
        session = get_db()
        code = generate_qr_code()
        guest = Guest(
            name="NullTime Guest",
            email="nulltime@test.com",
            ticket_count=1,
            qr_code=code,
            checked_in=True,
            checkin_time=None,
        )
        session.add(guest)
        session.commit()
        session.close()

        result = check_in_by_code(code)
        self.assertEqual(result["status"], "already")
        self.assertIn("NullTime Guest", result["message"])

    # ── Service Layer: mark_band_given ──────────────────────────────────────

    def test_mark_band_given_flow(self):
        reg = self._register(name="Band Flow", email="bandflow@test.com", zelle_ref="ZELLE-BANDFLW1")
        gid = reg["guest"]["id"]

        first = mark_band_given(gid)
        self.assertTrue(first["ok"])

        second = mark_band_given(gid)
        self.assertFalse(second["ok"])
        self.assertIn("already", second["message"].lower())

    def test_mark_band_given_nonexistent(self):
        result = mark_band_given(999999)
        self.assertFalse(result["ok"])

    # ── Service Layer: delete_guest ─────────────────────────────────────────

    def test_delete_guest_flow(self):
        reg = self._register(name="Delete Me", email="deleteme@test.com", zelle_ref="ZELLE-DELETEM1")
        gid = reg["guest"]["id"]

        self.assertTrue(delete_guest(gid))

        session = get_db()
        remaining = session.query(Guest).filter_by(id=gid).first()
        session.close()
        self.assertIsNone(remaining)

    def test_delete_guest_nonexistent(self):
        self.assertFalse(delete_guest(999999))

    # ── Service Layer: list_guests / get_recent_checkins ───────────────────

    def test_list_guests_returns_dicts_newest_first(self):
        r1 = self._register(name="Alice LG", email="alice.lg@test.com", zelle_ref="ZELLE-ALICELG1")
        r2 = self._register(name="Bob LG", email="bob.lg@test.com", zelle_ref="ZELLE-BOBLG0001")
        r3 = self._register(name="Carol LG", email="carol.lg@test.com", zelle_ref="ZELLE-CAROLLG1")

        # Pin distinct created_at values so ordering is deterministic
        # regardless of clock resolution.
        session = get_db()
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i, gid in enumerate([r1["guest"]["id"], r2["guest"]["id"], r3["guest"]["id"]]):
            g = session.query(Guest).filter_by(id=gid).first()
            g.created_at = base + timedelta(minutes=i)
        session.commit()
        session.close()

        guests = list_guests()
        self.assertTrue(all(isinstance(g, dict) for g in guests))
        ids_in_order = [g["id"] for g in guests]
        expected_order = [r3["guest"]["id"], r2["guest"]["id"], r1["guest"]["id"]]
        self.assertEqual(ids_in_order, expected_order)

    def test_get_recent_checkins_limit_and_checked_in_only(self):
        ids = []
        for i in range(5):
            r = self._register(name=f"Recent{i}", email=f"recent{i}@test.com",
                                zelle_ref=f"ZELLE-RECENT0{i}")
            ids.append(r["guest"]["id"])

        # Only check in the first 3 of 5 guests.
        for gid in ids[:3]:
            check_in_by_code(str(gid))

        limited = get_recent_checkins(limit=2)
        self.assertEqual(len(limited), 2)
        for g in limited:
            self.assertTrue(g["checked_in"])

        all_checked_in = get_recent_checkins(limit=10)
        self.assertEqual(len(all_checked_in), 3)  # never includes the 2 not checked in

    # ── Service Layer: analytics bucketing ──────────────────────────────────

    def test_get_registration_daily_counts_buckets_by_day(self):
        r1 = self._register(name="Day1a", email="day1a@test.com", zelle_ref="ZELLE-DAY1A0001")
        r2 = self._register(name="Day1b", email="day1b@test.com", zelle_ref="ZELLE-DAY1B0001")
        r3 = self._register(name="Day2a", email="day2a@test.com", zelle_ref="ZELLE-DAY2A0001")

        day1 = datetime(2026, 3, 1, 9, 0, 0)
        day1_later = datetime(2026, 3, 1, 15, 0, 0)
        day2 = datetime(2026, 3, 2, 10, 0, 0)

        session = get_db()
        for gid, dt in [
            (r1["guest"]["id"], day1),
            (r2["guest"]["id"], day1_later),
            (r3["guest"]["id"], day2),
        ]:
            g = session.query(Guest).filter_by(id=gid).first()
            g.created_at = dt
        session.commit()
        session.close()

        counts = get_registration_daily_counts()
        counts_dict = dict(counts)
        self.assertEqual(counts_dict[day1.date()], 2)
        self.assertEqual(counts_dict[day2.date()], 1)
        # Oldest first
        self.assertEqual(counts[0][0], day1.date())

    def test_get_event_day_hourly_checkins_24_entries_and_bucketing(self):
        r1 = self._register(name="Hourly1", email="hourly1@test.com", zelle_ref="ZELLE-HOURLY001")
        r2 = self._register(name="Hourly2", email="hourly2@test.com", zelle_ref="ZELLE-HOURLY002")
        r3 = self._register(name="OffDay", email="offday@test.com", zelle_ref="ZELLE-OFFDAY001")

        event_hour_a = config.EVENT_DATE.replace(hour=9, minute=15)
        event_hour_b = config.EVENT_DATE.replace(hour=9, minute=45)
        other_day = config.EVENT_DATE - timedelta(days=1)
        other_day = other_day.replace(hour=9, minute=0)

        session = get_db()
        for gid, dt in [
            (r1["guest"]["id"], event_hour_a),
            (r2["guest"]["id"], event_hour_b),
            (r3["guest"]["id"], other_day),
        ]:
            g = session.query(Guest).filter_by(id=gid).first()
            g.checked_in = True
            g.checkin_time = dt
        session.commit()
        session.close()

        hourly = get_event_day_hourly_checkins()
        self.assertEqual(len(hourly), 24)
        self.assertEqual(hourly[9], 2)
        self.assertEqual(sum(hourly), 2)  # the off-day checkin must not be counted

    # ── Service Layer: validate_registration ────────────────────────────────

    def test_validate_registration_all_valid(self):
        # 2 tickets = the booker plus exactly 1 named guest.
        cleaned, errors = validate_registration(
            name="Jane Doe",
            email="janevalid@example.com",
            phone="555-123-4567",
            plus_one_name="John Doe",
            zelle_ref="ZELLE12345678",
            agree_terms=True,
            ticket_count=2,
            veg_count=1,
            non_veg_count=1,
        )
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["name"], "Jane Doe")
        self.assertEqual(cleaned["email"], "janevalid@example.com")
        self.assertEqual(cleaned["phone"], "+1-555-123-4567")
        self.assertEqual(cleaned["plus_one_name"], "John Doe")
        self.assertEqual(cleaned["ticket_count"], 2)
        self.assertEqual(cleaned["additional_guest_count"], 1)
        self.assertEqual(cleaned["zelle_ref"], "ZELLE12345678")
        self.assertTrue(cleaned["terms"])
        self.assertEqual(cleaned["veg_count"], 1)
        self.assertEqual(cleaned["non_veg_count"], 1)

    def test_validate_registration_invalid_name(self):
        cleaned, errors = validate_registration(
            "John123", "a@b.com", "", "", "ZELLE12345678", True
        )
        self.assertIn("name", errors)
        self.assertEqual(cleaned["name"], "")

    def test_validate_registration_invalid_email(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "not-an-email", "", "", "ZELLE12345678", True
        )
        self.assertIn("email", errors)
        self.assertEqual(cleaned["email"], "")

    def test_validate_registration_blank_phone_is_required_error(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane2@example.com", "", "", "ZELLE12345678", True
        )
        self.assertIn("required", errors["phone"])
        self.assertEqual(cleaned["phone"], "")

    def test_validate_registration_phone_stub_is_required_error(self):
        # The placeholder the field used to be pre-filled with is not an answer
        for stub in ("+", "+1", "+1-", "   "):
            cleaned, errors = validate_registration(
                "Jane Doe", "jane2b@example.com", stub, "", "ZELLE12345678", True
            )
            self.assertIn("required", errors["phone"], stub)

    def test_validate_registration_invalid_phone_non_blank(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane3@example.com", "123", "", "ZELLE12345678", True
        )
        self.assertIn("phone", errors)
        # A typed-but-wrong number gets the "what's valid" message, not the
        # "you left it blank" one
        self.assertNotIn("required", errors["phone"])

    def test_validate_registration_non_us_phone_rejected(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane3b@example.com", "+44 20 7946 0958", "", "ZELLE12345678", True
        )
        self.assertIn("phone", errors)
        self.assertEqual(cleaned["phone"], "")

    def test_validate_registration_single_ticket_needs_no_names(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane4@example.com", "", "", "ZELLE12345678", True
        )
        self.assertNotIn("plus_one_name", errors)
        self.assertEqual(cleaned["plus_one_name"], "")
        self.assertEqual(cleaned["additional_guest_count"], 0)

    def test_validate_registration_invalid_plus_one_non_blank(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane5@example.com", "", "Bob123", "ZELLE12345678", True
        )
        self.assertIn("plus_one_name", errors)

    def test_validate_registration_invalid_zelle_ref(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane6@example.com", "", "", "short", True
        )
        self.assertIn("zelle_ref", errors)
        self.assertEqual(cleaned["zelle_ref"], "")

    def test_validate_registration_terms_not_agreed(self):
        cleaned, errors = validate_registration(
            "Jane Doe", "jane7@example.com", "", "", "ZELLE12345678", False
        )
        self.assertIn("terms", errors)
        self.assertFalse(cleaned["terms"])

    # ── format_dt ────────────────────────────────────────────────────────────

    def test_format_dt_formats_datetime(self):
        dt = datetime(2026, 10, 9, 14, 30, 0)
        self.assertEqual(format_dt(dt, "%H:%M"), "14:30")

    def test_format_dt_fallback_for_none(self):
        self.assertEqual(format_dt(None), "—")
        self.assertEqual(format_dt(None, fallback="N/A"), "N/A")

    # ── Security: admin password fail-closed ────────────────────────────────

    def test_verify_admin_password_fails_closed_when_unconfigured(self):
        with patch.dict(mock_secrets, {"ADMIN_PASSWORD": ""}):
            self.assertFalse(verify_admin_password(""))
            self.assertFalse(verify_admin_password("anything"))
            self.assertFalse(verify_admin_password("testadmin123"))

    def test_verify_admin_password_non_ascii_does_not_raise(self):
        try:
            result = verify_admin_password("pässwörd™😀")
        except TypeError:
            self.fail("verify_admin_password raised TypeError on non-ASCII input")
        self.assertFalse(result)

    def test_admin_password_is_configured_true(self):
        self.assertTrue(admin_password_is_configured())

    def test_admin_password_is_configured_false(self):
        with patch.dict(mock_secrets, {"ADMIN_PASSWORD": ""}):
            self.assertFalse(admin_password_is_configured())

    # ── CSV export edge cases ───────────────────────────────────────────────

    def test_generate_csv_escapes_formula_name_and_handles_null_checkin_time(self):
        session = get_db()
        guest = Guest(
            name='=HYPERLINK("http://evil.com","click")',
            email="csvformula@test.com",
            ticket_count=1,
            zelle_ref="ZELLE-CSVFORM1",
            qr_code=generate_qr_code(),
            checked_in=True,
            checkin_time=None,  # must not crash the export
        )
        session.add(guest)
        session.commit()
        session.close()

        csv_data = generate_csv()  # must not raise

        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)
        header = rows[0]
        name_idx = header.index("Name")
        checkin_idx = header.index("Check-in Time")
        row = next(r for r in rows[1:] if "HYPERLINK" in r[name_idx])
        self.assertTrue(row[name_idx].startswith("'"))
        self.assertEqual(row[checkin_idx], "")

    # ── Email: HTML-escaping of guest-controlled values ─────────────────────

    def test_send_qr_email_escapes_html_and_never_hits_the_network(self):
        guest = Guest(
            id=99999,
            name="<script>alert(1)</script>",
            email="xss@test.com",
            ticket_count=1,
            plus_one_name="",
            qr_code="XSS-QR-CODE",
        )
        with patch.dict(mock_secrets, {"MAIL_USERNAME": "sender@test.com", "MAIL_PASSWORD": "testpass"}):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value.__enter__.return_value = mock_server
                result = send_qr_email(guest)

        self.assertTrue(result)
        mock_smtp_cls.assert_called_once()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@test.com", "testpass")
        mock_server.send_message.assert_called_once()

        sent_msg = mock_server.send_message.call_args[0][0]
        # The body is transfer-encoded (base64, since it contains emoji), so
        # decode the actual HTML part rather than grepping the raw message.
        html_part = next(
            part for part in sent_msg.walk() if part.get_content_type() == "text/html"
        )
        html_content = html_part.get_payload(decode=True).decode("utf-8")
        self.assertNotIn("<script>alert", html_content)
        self.assertIn("&lt;script&gt;", html_content)

    def test_qr_email_lists_every_additional_guest_with_a_count(self):
        guest = Guest(
            id=99998,
            name="Group Booker",
            email="group@test.com",
            ticket_count=4,
            plus_one_name="Ann Lee\nBob Ray\nCal <b>Vue</b>",
            qr_code="GROUP-QR-CODE",
        )
        with patch.dict(mock_secrets, {"MAIL_USERNAME": "sender@test.com", "MAIL_PASSWORD": "testpass"}):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value.__enter__.return_value = mock_server
                self.assertTrue(send_qr_email(guest))

        sent_msg = mock_server.send_message.call_args[0][0]
        parts = {p.get_content_type(): p.get_payload(decode=True).decode("utf-8")
                 for p in sent_msg.walk() if p.get_content_type().startswith("text/")}

        html_content = parts["text/html"]
        self.assertIn("Additional guests (3)", html_content)
        # Newline-joined names must come out as separate list items, not one
        # run-together blob — and still be escaped.
        self.assertIn("<li>Ann Lee</li>", html_content)
        self.assertIn("<li>Bob Ray</li>", html_content)
        self.assertNotIn("<b>Vue</b>", html_content)
        self.assertIn("&lt;b&gt;", html_content)

        plain_content = parts["text/plain"]
        self.assertIn("Additional guests (3)", plain_content)
        self.assertIn("  - Ann Lee", plain_content)
        self.assertIn("  - Bob Ray", plain_content)

    def test_qr_email_omits_the_guest_list_for_a_solo_booking(self):
        guest = Guest(
            id=99997, name="Solo", email="solo@test.com", ticket_count=1,
            plus_one_name="", qr_code="SOLO-QR-CODE",
        )
        with patch.dict(mock_secrets, {"MAIL_USERNAME": "sender@test.com", "MAIL_PASSWORD": "testpass"}):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value.__enter__.return_value = mock_server
                self.assertTrue(send_qr_email(guest))

        sent_msg = mock_server.send_message.call_args[0][0]
        html_part = next(p for p in sent_msg.walk() if p.get_content_type() == "text/html")
        self.assertNotIn("Additional guests", html_part.get_payload(decode=True).decode("utf-8"))

    # ── Pure helpers: _normalize_postgres_url ───────────────────────────────

    def test_normalize_postgres_url_variants(self):
        expected = "postgresql+psycopg2://user:pass@host:5432/db"
        self.assertEqual(_normalize_postgres_url("postgres://user:pass@host:5432/db"), expected)
        self.assertEqual(_normalize_postgres_url("postgresql://user:pass@host:5432/db"), expected)
        self.assertEqual(_normalize_postgres_url("postgresql+psycopg://user:pass@host:5432/db"), expected)
        self.assertEqual(_normalize_postgres_url("postgresql+psycopg2://user:pass@host:5432/db"), expected)

    def test_normalize_postgres_url_sqlite_passthrough(self):
        self.assertEqual(_normalize_postgres_url("sqlite:///test.db"), "sqlite:///test.db")

    # ── Pure helpers: generate_qr_code ──────────────────────────────────────

    def test_generate_qr_code_prefix(self):
        code = generate_qr_code()
        self.assertTrue(code.startswith(config.qr_prefix() + "-"))

    # ── Pure helpers: sanitize_* edge cases ─────────────────────────────────

    def test_sanitize_name_edge_cases(self):
        # Very long input: exceeds the 100-char cap -> rejected outright
        self.assertEqual(sanitize_name("A" * 150), "")
        # Unicode letters are outside the ASCII-only [A-Za-z] allow-list
        self.assertEqual(sanitize_name("Émile Zola"), "")
        # Tabs/newlines are collapsed to single spaces, not rejected
        self.assertEqual(sanitize_name("John\tDoe"), "John Doe")
        self.assertEqual(sanitize_name("  \n Jane  Doe \t "), "Jane Doe")

    def test_sanitize_email_edge_cases(self):
        # Long but well-formed email passes (no explicit length cap)
        long_email = "a" * 100 + "@example.com"
        self.assertEqual(sanitize_email(long_email), long_email)
        # Unicode local part rejected by the ASCII-only regex
        self.assertEqual(sanitize_email("josé@example.com"), "")
        # Leading/trailing whitespace and mixed case normalized
        self.assertEqual(sanitize_email("\t  Foo.Bar+tag@Example.COM \n"), "foo.bar+tag@example.com")

    def test_sanitize_phone_edge_cases(self):
        # Very long garbage input rejected
        self.assertEqual(sanitize_phone("1" * 50), "")
        # Unicode (full-width) digits are not ASCII digits -> rejected
        self.assertEqual(sanitize_phone("５５５１２３４５６７"), "")
        # Leading/trailing whitespace tolerated around a valid number
        self.assertEqual(sanitize_phone("   555-123-4567   "), "+1-555-123-4567")

    def test_phone_input_mask_js_targets_the_field_and_escapes_the_label(self):
        js = phone_input_mask_js("Phone Number *")
        # It has to find the widget by the aria-label Streamlit renders...
        self.assertIn('"Phone Number *"', js)
        self.assertIn("aria-label", js)
        # ...and the prefix it maintains must match what the server treats
        # as "not filled in" (see validate_registration)
        self.assertIn('"+1-"', js)
        self.assertEqual(sanitize_phone(utils.US_PHONE_PREFIX), "")

        # A label carrying markup cannot break out of the <script> block
        hostile = phone_input_mask_js('</script><img src=x onerror=alert(1)>')
        self.assertNotIn("</script><img", hostile)
        self.assertIn("<\\/script>", hostile)

    def test_sanitize_zelle_ref_edge_cases(self):
        # Very long ref exceeds 30 chars after cleaning -> rejected
        self.assertEqual(sanitize_zelle_ref("A" * 40), "")
        # Unicode characters are stripped out entirely; remaining digits still valid
        self.assertEqual(sanitize_zelle_ref("ÉÉÉÉÉÉÉÉ12345678"), "12345678")
        # Leading/trailing junk (symbols) cleaned, remainder valid
        self.assertEqual(sanitize_zelle_ref("***ABC-12345678***"), "ABC-12345678")

    # ── App Settings: get_setting / set_setting ─────────────────────────────

    def test_get_setting_set_setting_round_trip_and_default(self):
        # Default when unset
        self.assertEqual(get_setting("no_such_setting_key", "fallback"), "fallback")
        self.assertEqual(get_setting("no_such_setting_key"), "")

        set_setting("my_setting", "value1")
        self.assertEqual(get_setting("my_setting"), "value1")

        # set_setting overwrites rather than duplicating the row
        set_setting("my_setting", "value2")
        self.assertEqual(get_setting("my_setting"), "value2")

        session = get_db()
        try:
            count = session.query(AppSetting).filter_by(key="my_setting").count()
        finally:
            session.close()
        self.assertEqual(count, 1)

    # ── Check-in window: get_checkin_mode / set_checkin_mode ────────────────

    def test_get_checkin_mode_defaults_to_auto_when_unset(self):
        session = get_db()
        session.query(AppSetting).delete()
        session.commit()
        session.close()
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_AUTO)

    def test_get_checkin_mode_defaults_to_auto_when_stored_value_is_garbage(self):
        # Bypass set_checkin_mode's validation to simulate a corrupted/old
        # value already sitting in the table.
        set_setting("checkin_mode", "not-a-real-mode")
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_AUTO)

    def test_set_checkin_mode_rejects_invalid_mode(self):
        with self.assertRaises(ValueError):
            set_checkin_mode("definitely-not-valid")
        # And the invalid value must not have been persisted.
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_OPEN)  # set by setUp()

    # ── Check-in window: checkin_status() ───────────────────────────────────

    def test_checkin_status_open_mode(self):
        set_checkin_mode(CHECKIN_MODE_OPEN)
        status = checkin_status()
        self.assertTrue(status["open"])
        self.assertEqual(status["message"], "")

    def test_checkin_status_closed_mode(self):
        set_checkin_mode(CHECKIN_MODE_CLOSED)
        status = checkin_status()
        self.assertFalse(status["open"])
        self.assertGreater(len(status["message"]), 0)

    def test_checkin_status_auto_mode_before_window_is_closed(self):
        set_checkin_mode(CHECKIN_MODE_AUTO)
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        with patch.object(config, "checkin_opens_at_utc", return_value=future):
            status = checkin_status()
        self.assertFalse(status["open"])
        self.assertGreater(len(status["message"]), 0)

    def test_checkin_status_auto_mode_after_window_is_open(self):
        set_checkin_mode(CHECKIN_MODE_AUTO)
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        with patch.object(config, "checkin_opens_at_utc", return_value=past):
            status = checkin_status()
        self.assertTrue(status["open"])
        self.assertEqual(status["message"], "")

    # ── Check-in window: check_in_by_code gating ────────────────────────────

    def test_check_in_by_code_auto_mode_before_window_leaves_guest_unmodified(self):
        set_checkin_mode(CHECKIN_MODE_AUTO)
        reg = self._register(name="Early Bird", email="earlybird@test.com", zelle_ref="ZELLE-EARLYBRD")
        code = reg["guest"]["qr_code"]
        gid = reg["guest"]["id"]

        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        with patch.object(config, "checkin_opens_at_utc", return_value=future):
            result = check_in_by_code(code)

        self.assertEqual(result["status"], "not_open")
        self.assertIsNone(result["guest"])

        # Assert against the DB, not just the return value: the row must be
        # genuinely untouched -- no lookup/write happened at all.
        session = get_db()
        try:
            guest = session.query(Guest).filter_by(id=gid).first()
            self.assertFalse(guest.checked_in)
            self.assertIsNone(guest.checkin_time)
        finally:
            session.close()

    def test_check_in_by_code_bypass_window_succeeds_when_closed(self):
        set_checkin_mode(CHECKIN_MODE_CLOSED)
        reg = self._register(name="Admin Admit", email="adminadmit@test.com", zelle_ref="ZELLE-ADMADMIT")
        code = reg["guest"]["qr_code"]

        result = check_in_by_code(code, bypass_window=True)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["guest"]["checked_in"])

    def test_check_in_by_code_mode_open_allows_checkin(self):
        set_checkin_mode(CHECKIN_MODE_OPEN)
        reg = self._register(name="Open Mode Guest", email="openmodeguest@test.com", zelle_ref="ZELLE-OPENMODE1")
        result = check_in_by_code(reg["guest"]["qr_code"])
        self.assertEqual(result["status"], "success")

    def test_check_in_by_code_mode_closed_blocks_checkin(self):
        set_checkin_mode(CHECKIN_MODE_CLOSED)
        reg = self._register(name="Closed Mode Guest", email="closedmodeguest@test.com", zelle_ref="ZELLE-CLSDMODE1")
        result = check_in_by_code(reg["guest"]["qr_code"])
        self.assertEqual(result["status"], "not_open")
        self.assertIsNone(result["guest"])

    # ── Bulk guest names: sanitize_guest_names ──────────────────────────────

    def test_sanitize_guest_names_newline_separated(self):
        result = sanitize_guest_names("Alice Smith\nBob Jones\nCarol White")
        self.assertEqual(result, "Alice Smith\nBob Jones\nCarol White")

    def test_sanitize_guest_names_comma_separated(self):
        result = sanitize_guest_names("Alice Smith, Bob Jones, Carol White")
        self.assertEqual(result, "Alice Smith\nBob Jones\nCarol White")

    def test_sanitize_guest_names_mixed_separators(self):
        result = sanitize_guest_names("Alice Smith, Bob Jones\nCarol White")
        self.assertEqual(result, "Alice Smith\nBob Jones\nCarol White")

    def test_sanitize_guest_names_blank_input_returns_empty(self):
        self.assertEqual(sanitize_guest_names(""), "")
        self.assertEqual(sanitize_guest_names("   "), "")
        self.assertEqual(sanitize_guest_names("\n\n  \n"), "")

    def test_sanitize_guest_names_any_invalid_entry_rejects_all(self):
        # "Bob123" contains digits -> entire list is rejected, not just that entry
        result = sanitize_guest_names("Alice Smith\nBob123\nCarol White")
        self.assertEqual(result, "")

    def test_sanitize_guest_names_over_max_returns_empty(self):
        too_many = [_guest_name(i) for i in range(utils.MAX_GUEST_NAMES + 1)]
        self.assertEqual(sanitize_guest_names("\n".join(too_many)), "")

    def test_sanitize_guest_names_exactly_max_accepted(self):
        at_max = [_guest_name(i) for i in range(utils.MAX_GUEST_NAMES)]
        expected = "\n".join(at_max)
        self.assertEqual(sanitize_guest_names("\n".join(at_max)), expected)

    def test_guest_name_storage_fits_a_maximum_size_booking(self):
        """The name box and the plus_one_name column are derived from the
        ticket cap, so raising the cap can never silently truncate the tail
        of a big booking's guest list — which would lose real people off the
        door list with no error anywhere."""
        widest = "\n".join("A" * utils.MAX_NAME_LENGTH for _ in range(utils.MAX_GUEST_NAMES))
        self.assertLessEqual(len(widest), utils.GUEST_NAMES_MAX_CHARS)
        self.assertEqual(
            utils.Guest.__table__.c.plus_one_name.type.length, utils.GUEST_NAMES_MAX_CHARS
        )
        self.assertEqual(
            utils.SubmissionLog.__table__.c.plus_one_name.type.length,
            utils.GUEST_NAMES_MAX_CHARS,
        )

    def test_a_maximum_size_booking_stores_every_guest_name(self):
        """The end-to-end version of the above: book the largest party the
        form allows and read all its names back out."""
        tickets = config.MAX_TICKETS_PER_REGISTRATION
        names = [_guest_name(i) for i in range(tickets - 1)]
        result = self._register(
            name="Biggest Booking", email="biggest.booking@example.com",
            ticket_count=tickets, plus_one_name="\n".join(names),
            zelle_ref="ZELLE-BIGGEST01",
        )
        self.assertTrue(result["ok"], result)
        stored = get_guest(result["guest"]["id"])
        self.assertEqual(utils.guest_names_list(stored["plus_one_name"]), names)
        self.assertEqual(utils.party_size(stored), tickets)

    def test_max_guest_names_is_one_below_the_ticket_cap(self):
        # The booker holds the first ticket, so the biggest possible booking
        # names one fewer person than it has tickets. If these two ever
        # disagree, a guest could pick a ticket count they can never satisfy.
        self.assertEqual(utils.MAX_GUEST_NAMES, config.MAX_TICKETS_PER_REGISTRATION - 1)

    def test_sanitize_guest_names_collapses_blank_lines_and_whitespace(self):
        result = sanitize_guest_names("Alice Smith\n\n\n   Bob Jones   \n\n,,,")
        self.assertEqual(result, "Alice Smith\nBob Jones")

    # ── Bulk guest names: validate_registration integration ─────────────────

    def test_validate_registration_plus_one_bulk_names_at_max_no_error(self):
        # The largest bookable party: every ticket the selector allows, with
        # a name for everyone but the booker.
        names = [_guest_name(i) for i in range(utils.MAX_GUEST_NAMES)]
        text = "\n".join(names)
        cleaned, errors = validate_registration(
            "Jane Doe", "janebulkmax@example.com", "", text, "ZELLE12345678", True,
            ticket_count=config.MAX_TICKETS_PER_REGISTRATION,
        )
        self.assertNotIn("plus_one_name", errors)
        self.assertEqual(cleaned["plus_one_name"], text)
        self.assertEqual(cleaned["additional_guest_count"], utils.MAX_GUEST_NAMES)

    def test_validate_registration_plus_one_over_max_names_error(self):
        too_many = [_guest_name(i) for i in range(utils.MAX_GUEST_NAMES + 1)]
        text = "\n".join(too_many)
        cleaned, errors = validate_registration(
            "Jane Doe", "janebulkover@example.com", "", text, "ZELLE12345678", True,
            ticket_count=config.MAX_TICKETS_PER_REGISTRATION,
        )
        self.assertIn("plus_one_name", errors)
        self.assertEqual(cleaned["plus_one_name"], "")

    # ── Guest names must match the ticket count ─────────────────────────────
    # One ticket per person: N tickets is the booker plus N-1 named guests.

    def _names_check(self, ticket_count, plus_one_name, email, veg_count=0, non_veg_count=0):
        """validate_registration with everything but the names/tickets valid."""
        return validate_registration(
            "Jane Doe", email, "555-123-4567", plus_one_name, "ZELLE12345678", True,
            ticket_count=ticket_count,
            veg_count=veg_count, non_veg_count=non_veg_count,
        )

    def test_validate_registration_exact_name_count_accepted(self):
        cleaned, errors = self._names_check(
            4, "Ann Lee\nBob Ray\nCal Vue", "exactnames@example.com",
            veg_count=2, non_veg_count=2,
        )
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["additional_guest_count"], 3)
        self.assertEqual(cleaned["plus_one_name"], "Ann Lee\nBob Ray\nCal Vue")

    def test_validate_registration_multi_ticket_with_no_names_rejected(self):
        cleaned, errors = self._names_check(3, "", "nonames@example.com")
        self.assertIn("plus_one_name", errors)
        self.assertIn("2 other guests", errors["plus_one_name"])
        self.assertEqual(cleaned["additional_guest_count"], 0)

    def test_validate_registration_too_few_names_rejected_and_counted(self):
        cleaned, errors = self._names_check(5, "Ann Lee\nBob Ray", "toofew@example.com")
        self.assertIn("plus_one_name", errors)
        # The message has to name both numbers, or the guest can't tell which
        # of the two to change.
        self.assertIn("4 additional guest names", errors["plus_one_name"])
        self.assertIn("you listed 2", errors["plus_one_name"])
        self.assertIn("add the 2 missing names", errors["plus_one_name"].lower())

    def test_validate_registration_too_many_names_rejected(self):
        # The case a capacity-clamped ticket count produces: more names in
        # the box than tickets left to cover them.
        cleaned, errors = self._names_check(
            2, "Ann Lee\nBob Ray\nCal Vue", "toomany@example.com"
        )
        self.assertIn("plus_one_name", errors)
        self.assertIn("listed 3", errors["plus_one_name"])
        self.assertIn("remove 2 names", errors["plus_one_name"])
        # Must not tell someone with a surplus to "add the missing names"
        self.assertNotIn("missing", errors["plus_one_name"])

    def test_validate_registration_names_on_single_ticket_rejected(self):
        cleaned, errors = self._names_check(1, "Ann Lee", "soloplusname@example.com")
        self.assertIn("plus_one_name", errors)
        self.assertIn("only booked 1 ticket", errors["plus_one_name"])

    def test_validate_registration_singular_wording_for_one_missing_name(self):
        _cleaned, errors = self._names_check(2, "", "onemissing@example.com")
        msg = errors["plus_one_name"]
        self.assertIn("1 other guest", msg)
        self.assertIn("their name", msg)
        self.assertNotIn("guests", msg)

    def test_validate_registration_invalid_name_beats_count_check(self):
        # A typo'd name must report the typo, not a confusing count mismatch.
        _cleaned, errors = self._names_check(3, "Ann Lee\nBob123", "typoname@example.com")
        self.assertIn("letters and spaces", errors["plus_one_name"])

    def test_validate_registration_rejects_out_of_range_ticket_count(self):
        for bad in (0, -3, config.MAX_TICKETS_PER_REGISTRATION + 1, "abc", None):
            with self.subTest(ticket_count=bad):
                cleaned, errors = self._names_check(bad, "", f"tickets{bad}@example.com")
                self.assertIn("ticket_count", errors)
                # Always clamped back into range, so nothing downstream sees
                # a nonsense ticket count even on the error path.
                self.assertGreaterEqual(cleaned["ticket_count"], 1)
                self.assertLessEqual(cleaned["ticket_count"], config.MAX_TICKETS_PER_REGISTRATION)

    def test_validate_registration_comma_separated_names_count_correctly(self):
        cleaned, errors = self._names_check(
            3, "Ann Lee, Bob Ray", "commanames@example.com",
            veg_count=2, non_veg_count=1,
        )
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["plus_one_name"], "Ann Lee\nBob Ray")
        self.assertEqual(cleaned["additional_guest_count"], 2)

    # ── Meal counts are optional planning preferences ───────────────────────
    # Food is available for purchase at the venue, so veg + non-veg may be 0
    # up to ticket_count. Only more meals than tickets is rejected.

    def _food_check(self, ticket_count, veg_count, non_veg_count, email):
        """validate_registration with everything but the food count valid."""
        expected_names = utils.additional_guests_expected(ticket_count)
        names = "\n".join(_guest_name(i) for i in range(expected_names))
        return validate_registration(
            "Jane Doe", email, "555-123-4567", names, "ZELLE12345678", True,
            ticket_count=ticket_count, veg_count=veg_count, non_veg_count=non_veg_count,
        )

    def test_validate_registration_exact_food_count_accepted(self):
        cleaned, errors = self._food_check(4, 2, 2, "exactfood@example.com")
        self.assertNotIn("food_count", errors)
        self.assertEqual(cleaned["veg_count"], 2)
        self.assertEqual(cleaned["non_veg_count"], 2)

    def test_validate_registration_zero_meals_accepted(self):
        cleaned, errors = self._food_check(4, 0, 0, "nomeals@example.com")
        self.assertNotIn("food_count", errors)
        self.assertEqual(cleaned["veg_count"], 0)
        self.assertEqual(cleaned["non_veg_count"], 0)

    def test_validate_registration_fewer_meals_than_tickets_accepted(self):
        cleaned, errors = self._food_check(4, 1, 1, "fewermeals@example.com")
        self.assertNotIn("food_count", errors)

    def test_validate_registration_too_many_meals_rejected(self):
        cleaned, errors = self._food_check(2, 2, 2, "toomanymeals@example.com")
        self.assertIn("food_count", errors)

    def test_validate_registration_negative_veg_count_rejected(self):
        cleaned, errors = self._food_check(2, -1, 3, "negveg@example.com")
        self.assertIn("food_count", errors)

    def test_validate_registration_negative_non_veg_count_rejected(self):
        cleaned, errors = self._food_check(2, 3, -1, "negnonveg@example.com")
        self.assertIn("food_count", errors)

    # ── Head-count helpers ──────────────────────────────────────────────────

    def test_additional_guests_expected(self):
        self.assertEqual(utils.additional_guests_expected(1), 0)
        self.assertEqual(utils.additional_guests_expected(4), 3)
        # Never negative, and never raises on junk
        self.assertEqual(utils.additional_guests_expected(0), 0)
        self.assertEqual(utils.additional_guests_expected(None), 0)
        self.assertEqual(utils.additional_guests_expected("nope"), 0)

    def test_guest_names_list_and_count(self):
        self.assertEqual(utils.guest_names_list("Ann Lee\nBob Ray"), ["Ann Lee", "Bob Ray"])
        self.assertEqual(utils.guest_name_count("Ann Lee\nBob Ray"), 2)
        # The column's blank default and NULL both mean "nobody"
        self.assertEqual(utils.guest_names_list(""), [])
        self.assertEqual(utils.guest_names_list(None), [])
        self.assertEqual(utils.guest_name_count(None), 0)
        # Stray blank lines from a hand-edited row don't inflate the count
        self.assertEqual(utils.guest_name_count("Ann Lee\n\n  \nBob Ray\n"), 2)

    def test_count_guest_name_entries_counts_invalid_entries_too(self):
        # Progress display: what's in the box, not what would pass validation
        self.assertEqual(utils.count_guest_name_entries("Ann Lee\nBob123, Cal"), 3)
        self.assertEqual(utils.count_guest_name_entries(""), 0)

    def test_party_size_counts_the_booker(self):
        self.assertEqual(utils.party_size({"ticket_count": 3, "plus_one_name": "A Lee\nB Ray"}), 3)
        self.assertEqual(utils.party_size({"ticket_count": 1, "plus_one_name": ""}), 1)
        # A legacy row with fewer names than tickets still reports the tickets
        self.assertEqual(utils.party_size({"ticket_count": 5, "plus_one_name": "A Lee"}), 5)
        # ...and a row naming more people than it has tickets reports the people
        self.assertEqual(utils.party_size({"ticket_count": 1, "plus_one_name": "A Lee\nB Ray"}), 3)
        self.assertEqual(utils.party_size({}), 1)

    def test_parse_guest_names_reports_why_it_failed(self):
        self.assertEqual(utils.parse_guest_names("Ann Lee\nBob Ray"), (["Ann Lee", "Bob Ray"], ""))
        self.assertEqual(utils.parse_guest_names(""), ([], ""))
        self.assertEqual(utils.parse_guest_names("Ann Lee\nBob123"), ([], "invalid"))
        too_many = "\n".join(_guest_name(i) for i in range(utils.MAX_GUEST_NAMES + 1))
        self.assertEqual(utils.parse_guest_names(too_many), ([], "too_many"))

    # ── Async email: send_qr_email_async ────────────────────────────────────

    def test_send_qr_email_async_blank_credentials_returns_without_smtp(self):
        # Class-level mock_secrets already has blank MAIL_USERNAME/MAIL_PASSWORD.
        guest = {
            "id": 1,
            "name": "No Creds",
            "email": "nocreds@test.com",
            "ticket_count": 1,
            "plus_one_name": "",
            "qr_code": "NOCREDS-QR",
            "phone": "",
            "zelle_ref": "",
        }
        with patch("smtplib.SMTP") as mock_smtp_cls, patch("smtplib.SMTP_SSL") as mock_smtp_ssl_cls:
            send_qr_email_async(guest)  # must return promptly, no thread spawned

        mock_smtp_cls.assert_not_called()
        mock_smtp_ssl_cls.assert_not_called()

    def test_send_qr_email_async_missing_optional_keys_does_not_raise(self):
        # Blank credentials -> returns immediately without touching the
        # (missing) optional keys at all, but must not raise regardless.
        guest = {"id": 2, "name": "Minimal", "email": "minimal@test.com"}
        try:
            send_qr_email_async(guest)
        except Exception as e:
            self.fail(f"send_qr_email_async raised with a minimal guest dict: {e}")

    def test_send_qr_email_async_with_credentials_sends_and_worker_touches_no_st(self):
        guest = {"id": 3, "name": "Async Guest", "email": "asyncguest@test.com"}  # missing optional keys too

        local_secrets = dict(mock_secrets)
        local_secrets.update({"MAIL_USERNAME": "sender@test.com", "MAIL_PASSWORD": "testpass"})

        # A Mock (not a plain dict) so we can assert on call_count: every
        # st.secrets.get() must happen on the calling thread, synchronously,
        # before send_qr_email_async() returns -- never from the worker.
        secrets_mock = MagicMock()
        secrets_mock.get.side_effect = local_secrets.get
        mock_st_local = MagicMock()
        mock_st_local.secrets = secrets_mock

        done = threading.Event()

        with patch.object(utils, "st", mock_st_local):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value.__enter__.return_value = mock_server
                mock_server.send_message.side_effect = lambda *a, **k: done.set()

                send_qr_email_async(guest)

                # _read_mail_secrets() runs synchronously on the calling
                # thread before the worker thread is even started.
                calls_after_dispatch = secrets_mock.get.call_count
                self.assertGreater(calls_after_dispatch, 0)

                # Join deterministically on the worker's own completion
                # signal rather than sleeping and hoping.
                self.assertTrue(done.wait(timeout=5), "background email send did not complete in time")

            mock_server.send_message.assert_called_once()

        # No additional st.secrets reads must have happened after dispatch
        # -- proves the worker thread itself never touched st.*.
        self.assertEqual(secrets_mock.get.call_count, calls_after_dispatch)

    def test_send_qr_email_sync_paths_still_pass(self):
        # Guards against the async addition above accidentally sharing
        # mutable state with the synchronous sender.
        guest = Guest(name="Sync Check", email="synccheck@test.com", ticket_count=1, qr_code="SYNC-QR")
        self.assertFalse(send_qr_email(guest))  # blank creds -> False, unchanged behavior

    # ── Postgres pool config: _get_engine_cached ────────────────────────────

    def test_get_engine_cached_passes_pool_kwargs_for_postgres_url(self):
        with patch.dict(mock_secrets, {"DATABASE_URL": "postgresql://user:pass@host:5432/db"}):
            with patch("utils.create_engine") as mock_create_engine, \
                 patch("utils.inspect") as mock_inspect:
                mock_inspect.return_value.get_table_names.return_value = []
                db_url_hash = utils._get_engine_url_hash()
                # Bypass st.cache_resource's memoization via the underlying
                # function so each call actually re-invokes create_engine().
                utils._get_engine_cached.__wrapped__(db_url_hash)

        mock_create_engine.assert_called_once()
        args, kwargs = mock_create_engine.call_args
        self.assertTrue(args[0].startswith("postgresql+psycopg2://"))
        self.assertEqual(kwargs.get("pool_size"), 5)
        self.assertEqual(kwargs.get("max_overflow"), 10)
        self.assertEqual(kwargs.get("pool_recycle"), 1800)

    def test_get_engine_cached_omits_pool_kwargs_for_sqlite_url(self):
        with patch.dict(mock_secrets, {"DATABASE_URL": "sqlite:///somefile.db"}):
            with patch("utils.create_engine") as mock_create_engine, \
                 patch("utils.inspect") as mock_inspect:
                mock_inspect.return_value.get_table_names.return_value = []
                db_url_hash = utils._get_engine_url_hash()
                utils._get_engine_cached.__wrapped__(db_url_hash)

        mock_create_engine.assert_called_once()
        args, kwargs = mock_create_engine.call_args
        self.assertTrue(args[0].startswith("sqlite://"))
        self.assertNotIn("pool_size", kwargs)
        self.assertNotIn("max_overflow", kwargs)
        self.assertNotIn("pool_recycle", kwargs)


    # ── Reset / wipe-all (destructive admin action) ────────────────────────

    def _seed_for_reset(self):
        """Populate every table reset_all_data() is supposed to empty."""
        session = get_db()
        try:
            g = Guest(name="Reset Me", email="reset.me@test.com", ticket_count=2,
                      zelle_ref="ZELLE-RESET1", qr_code=generate_qr_code())
            session.add(g)
            session.commit()
            gid = g.id
            session.add(CheckInLog(guest_id=gid, action="checkin", device_info="Test"))
            session.commit()
        finally:
            session.close()
        record_visit("reset-token", "Home")
        record_submission("Reset Me", "reset.me@test.com", "", 2, "", "ZELLE-RESET1",
                          status="registered", guest_id=gid)
        return gid

    def test_get_table_counts_matches_reality(self):
        self._seed_for_reset()
        counts = get_table_counts()
        self.assertEqual(set(counts), {"guests", "checkin_logs", "page_visits", "submission_logs"})
        self.assertEqual(counts["guests"], 1)
        self.assertEqual(counts["checkin_logs"], 1)
        self.assertGreaterEqual(counts["page_visits"], 1)
        self.assertGreaterEqual(counts["submission_logs"], 1)

    def test_reset_all_data_empties_every_table(self):
        self._seed_for_reset()
        result = reset_all_data()

        self.assertEqual(result["guests"], 1)
        self.assertEqual(result["checkin_logs"], 1)
        self.assertGreaterEqual(result["page_visits"], 1)
        self.assertGreaterEqual(result["submission_logs"], 1)

        after = get_table_counts()
        self.assertEqual(after["guests"], 0)
        self.assertEqual(after["checkin_logs"], 0)
        self.assertEqual(after["page_visits"], 0)
        self.assertEqual(after["submission_logs"], 0)

    def test_reset_all_data_preserves_schema(self):
        """It must empty tables, never drop them — the app has to keep working."""
        self._seed_for_reset()
        reset_all_data()
        from sqlalchemy import inspect as sa_inspect
        tables = set(sa_inspect(get_engine()).get_table_names())
        for expected in ("guests", "checkin_logs", "page_visits", "submission_logs", "app_settings"):
            self.assertIn(expected, tables)
        # and the app can still write afterwards
        res = register_guest("After Reset", "after.reset@test.com", "", 1, "", "ZELLE-AFTER01")
        self.assertTrue(res["ok"])

    def test_reset_all_data_restores_auto_checkin_mode(self):
        """A wipe must not leave check-in forced open from testing."""
        set_checkin_mode(CHECKIN_MODE_OPEN)
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_OPEN)
        reset_all_data()
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_AUTO)

    def test_reset_all_data_keep_settings_false_clears_settings(self):
        set_checkin_mode(CHECKIN_MODE_CLOSED)
        reset_all_data(keep_settings=False)
        # With no rows left, get_checkin_mode() falls back to its own default.
        self.assertEqual(get_checkin_mode(), CHECKIN_MODE_AUTO)

    def test_reset_all_data_on_empty_db_is_a_harmless_noop(self):
        result = reset_all_data()
        self.assertEqual(result["guests"], 0)
        self.assertEqual(get_table_counts()["guests"], 0)

    # ── Backup Export Tests ─────────────────────────────────────────────────

    def test_export_backup_covers_every_table_the_reset_wipes(self):
        """A backup that misses a table isn't a backup."""
        self._seed_for_reset()
        backup = export_backup()

        self.assertEqual(set(BACKUP_TABLES), set(backup["counts"]))
        for table in get_table_counts():
            self.assertIn(table, backup["counts"], f"{table} is wiped by reset but absent from the backup")
        self.assertEqual(backup["counts"]["guests"], 1)
        self.assertEqual(backup["counts"]["checkin_logs"], 1)
        self.assertGreaterEqual(backup["counts"]["page_visits"], 1)
        self.assertGreaterEqual(backup["counts"]["submission_logs"], 1)

    def test_export_backup_zip_holds_one_csv_per_table_plus_readme(self):
        self._seed_for_reset()
        backup = export_backup()

        with zipfile.ZipFile(io.BytesIO(backup["zip"])) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for table in BACKUP_TABLES:
                self.assertIn(f"{table}.csv", names)
            self.assertIn("README.txt", names)
            # ZIP content and the in-memory copy the UI serves must agree.
            self.assertEqual(
                archive.read("guests.csv").decode("utf-8"),
                backup["files"]["guests.csv"],
            )

    def test_export_backup_guest_csv_keeps_raw_column_names_and_values(self):
        """Headers are the real DB column names so the file can be reloaded."""
        gid = self._seed_for_reset()
        backup = export_backup()

        rows = list(csv.reader(io.StringIO(backup["files"]["guests.csv"])))
        self.assertEqual(rows[0][:4], ["id", "name", "email", "phone"])
        self.assertEqual(len(rows), 2)
        record = dict(zip(rows[0], rows[1]))
        self.assertEqual(record["id"], str(gid))
        self.assertEqual(record["name"], "Reset Me")
        self.assertEqual(record["email"], "reset.me@test.com")
        self.assertEqual(record["ticket_count"], "2")
        self.assertEqual(record["checked_in"], "false")
        self.assertTrue(record["created_at"])  # ISO timestamp, not empty

    def test_export_backup_escapes_formula_fields(self):
        """Backups get opened in Excel — a name must never run as a formula."""
        session = get_db()
        try:
            session.add(Guest(name="=cmd|'/c calc'!A1", email="formula@test.com",
                              ticket_count=1, qr_code=generate_qr_code()))
            session.commit()
        finally:
            session.close()

        backup = export_backup()
        rows = list(csv.reader(io.StringIO(backup["files"]["guests.csv"])))
        record = dict(zip(rows[0], rows[1]))
        self.assertTrue(record["name"].startswith("'="))

    def test_export_backup_on_empty_db_still_writes_headers(self):
        reset_all_data(keep_settings=False)  # keep_settings=True leaves a checkin_mode row
        backup = export_backup()

        self.assertEqual(sum(backup["counts"].values()), 0)
        for table in BACKUP_TABLES:
            rows = list(csv.reader(io.StringIO(backup["files"][f"{table}.csv"])))
            self.assertEqual(len(rows), 1, f"{table}.csv should be header-only")
            self.assertTrue(rows[0])

    def test_export_backup_readme_documents_tables_and_views(self):
        self._seed_for_reset()
        readme = export_backup()["files"]["README.txt"]

        for table in BACKUP_TABLES:
            self.assertIn(f"{table}.csv", readme)
        for view, _description in REPORTING_VIEWS:
            self.assertIn(view, readme)

    def test_documented_tables_and_views_match_the_real_ones(self):
        """The admin UI's reference list must not drift from the schema."""
        self.assertEqual([table for table, _desc in DATA_TABLES], list(BACKUP_TABLES))
        self.assertEqual(set(dict(REPORTING_VIEWS)), set(_reporting_view_sql()))
        from sqlalchemy import inspect as sa_inspect
        real_tables = set(sa_inspect(get_engine()).get_table_names())
        for table in BACKUP_TABLES:
            self.assertIn(table, real_tables)

    # ── Home page content: photos & sponsors ────────────────────────────
    # config.PHOTOS / config.SPONSORS are hand-edited by the organiser, so
    # every one of these covers a way that hand-editing goes wrong: a
    # mistyped path, a half-filled entry, a pasted `javascript:` URL. None
    # of them may take the Home page down or reach the browser.

    def _photo_uri(self, name="pixel.png"):
        """Write a real 1x1 PNG into the project dir and return its path."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        # Smallest valid PNG — this is decoded by a browser, never by us.
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with open(path, "wb") as fh:
            fh.write(png)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        # The resolver caches by (path, mtime), and these files are created
        # and deleted per-test, so a stale hit would leak between tests.
        self.addCleanup(utils._read_asset_data_uri.cache_clear)
        utils._read_asset_data_uri.cache_clear()
        return name

    def test_resolve_image_src_passes_through_https_and_data_uris(self):
        self.assertEqual(
            resolve_image_src("https://example.com/a.jpg"), "https://example.com/a.jpg"
        )
        self.assertEqual(resolve_image_src("data:image/png;base64,AAA"), "data:image/png;base64,AAA")

    def test_resolve_image_src_rejects_non_https_and_script_schemes(self):
        """Only https and local files ever reach an <img src>."""
        for bad in (
            "http://example.com/a.jpg",      # blocked as mixed content anyway
            "javascript:alert(1)",
            "JavaScript:alert(1)",           # casing must not get through
            "jAvAsCrIpT:alert(1)",
            "vbscript:msgbox(1)",
            "data:text/html,<script>alert(1)</script>",
            "//example.com/a.jpg",
            "ftp://example.com/a.jpg",
            "",
            "   ",
        ):
            with self.subTest(src=bad):
                self.assertEqual(resolve_image_src(bad), "")

    def test_resolve_image_src_accepts_https_and_data_uris_in_any_casing(self):
        self.assertEqual(
            resolve_image_src("HTTPS://example.com/a.jpg"), "HTTPS://example.com/a.jpg"
        )
        self.assertEqual(resolve_image_src("DATA:image/png;base64,AAA"), "DATA:image/png;base64,AAA")

    def test_resolve_image_src_inlines_a_local_file_as_a_data_uri(self):
        name = self._photo_uri()
        result = resolve_image_src(name)
        self.assertTrue(result.startswith("data:image/png;base64,"), result[:40])

    def test_resolve_image_src_resolves_relative_to_the_project_not_the_cwd(self):
        """The app is deliberately run from a different cwd (see AGENTS.md),
        so a project-relative photo path must still resolve there."""
        name = self._photo_uri()
        original_cwd = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(os.sep)))  # "/" — definitely not the project
        try:
            result = resolve_image_src(name)
        finally:
            os.chdir(original_cwd)
        self.assertTrue(result.startswith("data:image/png;base64,"))

    def test_resolve_image_src_skips_missing_and_unsupported_files(self):
        self.assertEqual(resolve_image_src("assets/photos/definitely-not-here.jpg"), "")
        self.assertEqual(resolve_image_src("assets/photos/notes.txt"), "")

    def test_resolve_image_src_picks_up_a_replaced_file_without_a_restart(self):
        """A deploy that reruns the script in the same long-lived process
        (e.g. Streamlit Cloud, which doesn't always restart on push) must
        not keep serving a since-replaced file's old bytes forever."""
        name = self._photo_uri()
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        first = resolve_image_src(name)

        # Same path, different content — mimics dropping in a new flyer.
        # Bump the mtime explicitly: back-to-back writes in a fast test run
        # can otherwise land on the same filesystem-clock tick.
        with open(path, "wb") as fh:
            fh.write(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
                b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        os.utime(path, ns=(time.time_ns() + 1_000_000_000, time.time_ns() + 1_000_000_000))

        second = resolve_image_src(name)
        self.assertTrue(second.startswith("data:image/png;base64,"))
        self.assertNotEqual(first, second)

    def test_resolve_image_src_skips_an_oversized_file(self):
        """Local images are base64'd into the page on every rerun, so an
        unresized photo has to be refused rather than shipped."""
        name = self._photo_uri("oversized.png")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        with open(path, "wb") as fh:
            fh.write(b"\x00" * (utils.MAX_INLINE_IMAGE_BYTES + 1))
        utils._read_asset_data_uri.cache_clear()
        self.assertEqual(resolve_image_src(name), "")

    def test_gallery_photos_returns_nothing_when_none_are_configured(self):
        """With PHOTOS empty, Home falls back to its "coming soon" state
        rather than rendering an empty grid."""
        with patch.object(config, "PHOTOS", []):
            self.assertEqual(gallery_photos(), [])

    def test_gallery_photos_drops_entries_that_cannot_render(self):
        name = self._photo_uri()
        with patch.object(config, "PHOTOS", [
            {"src": name, "caption": "Good one"},
            {"src": "assets/photos/missing.jpg", "caption": "Bad path"},
            {"src": "", "caption": "No source"},
            "not-even-a-dict",
        ]):
            photos = gallery_photos()
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["caption"], "Good one")
        self.assertTrue(photos[0]["src"].startswith("data:image/png;base64,"))

    def test_sponsor_list_orders_by_tier_and_marks_the_top_one(self):
        """Tier ranking is a config question, so the ordering happens in the
        service layer and the wall just walks it."""
        with patch.object(config, "SPONSOR_TIERS", ("Top Sponsor", "Gold", "Silver")):
            with patch.object(config, "SPONSORS", [
                {"name": "Silver Co", "tier": "Silver"},
                {"name": "Top Co", "tier": "Top Sponsor"},
                {"name": "Gold One", "tier": "Gold"},
                {"name": "Gold Two", "tier": "Gold"},
            ]):
                sponsors = sponsor_list()

        self.assertEqual(
            [s["name"] for s in sponsors], ["Top Co", "Gold One", "Gold Two", "Silver Co"],
            "tiers must sort best-first, and sponsors within a tier must keep their listed order",
        )
        self.assertEqual([s["featured"] for s in sponsors], [True, False, False, False])

    def test_sponsor_list_keeps_an_unknown_tier_at_the_end_rather_than_dropping_it(self):
        """A sponsor who paid must never vanish because their tier label
        isn't in the list — a typo costs them position, not their card."""
        with patch.object(config, "SPONSOR_TIERS", ("Top Sponsor", "Gold")):
            with patch.object(config, "SPONSORS", [
                {"name": "Mystery Co", "tier": "Platinum-ish"},
                {"name": "Gold Co", "tier": "Gold"},
                {"name": "No Tier Co"},
            ]):
                sponsors = sponsor_list()
        self.assertEqual([s["name"] for s in sponsors][0], "Gold Co")
        self.assertEqual(len(sponsors), 3)
        self.assertIn("Mystery Co", [s["name"] for s in sponsors])

    def test_sponsor_list_features_the_best_tier_present_even_without_a_top_sponsor(self):
        with patch.object(config, "SPONSOR_TIERS", ("Top Sponsor", "Gold", "Silver")):
            with patch.object(config, "SPONSORS", [
                {"name": "Gold Co", "tier": "Gold"},
                {"name": "Silver Co", "tier": "Silver"},
            ]):
                sponsors = sponsor_list()
        self.assertTrue(sponsors[0]["featured"], "the best tier present leads the wall")
        self.assertFalse(sponsors[1]["featured"])

    def test_sponsor_list_keeps_a_sponsor_with_no_logo_yet(self):
        """The lineup is usually confirmed before the artwork arrives."""
        with patch.object(config, "SPONSORS", [{"name": "Logo-less Co", "tier": "Gold"}]):
            sponsors = sponsor_list()
        self.assertEqual(len(sponsors), 1)
        self.assertEqual(sponsors[0]["name"], "Logo-less Co")
        self.assertEqual(sponsors[0]["logo"], "")

    def test_sponsor_list_drops_nameless_entries_and_unsafe_urls(self):
        with patch.object(config, "SPONSORS", [
            {"name": "  ", "tier": "Gold"},
            {"tier": "Silver"},
            {"name": "Script Co", "url": "JavaScript:alert(1)"},
            {"name": "Plain Co", "url": "http://example.com"},
            {"name": "Safe Co", "url": "https://example.com"},
        ]):
            sponsors = sponsor_list()
        self.assertEqual([s["name"] for s in sponsors], ["Script Co", "Plain Co", "Safe Co"])
        self.assertEqual(sponsors[0]["url"], "")   # javascript: dropped, any casing
        self.assertEqual(sponsors[1]["url"], "")   # plain http dropped
        self.assertEqual(sponsors[2]["url"], "https://example.com")

    # ── Home page content: rendering ────────────────────────────────────

    def test_photo_gallery_and_sponsor_wall_render_nothing_when_empty(self):
        """An empty list must produce no markup at all, so the caller can
        swap in a placeholder instead of showing an empty grid."""
        self.assertEqual(theme.photo_gallery([]), "")
        self.assertEqual(theme.sponsor_wall([]), "")

    def test_photo_gallery_escapes_captions_and_sets_alt_text(self):
        html_out = theme.photo_gallery(
            [{"src": "https://example.com/a.jpg", "caption": '<script>alert("x")</script>'}]
        )
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertIn('alt="', html_out)

    def test_sponsor_wall_groups_into_labelled_tiers_in_the_given_order(self):
        html_out = theme.sponsor_wall([
            {"name": "Top Co", "tier": "Top Sponsor", "featured": True},
            {"name": "Gold One", "tier": "Gold"},
            {"name": "Gold Two", "tier": "Gold"},
            {"name": "Silver Co", "tier": "Silver"},
        ])
        headings = [
            block.split("</div>")[0]
            for block in html_out.split('<div class="sponsor-tier-heading">')[1:]
        ]
        self.assertEqual(headings, ["Top Sponsor", "Gold", "Silver"],
                         "one heading per tier, in the order the list came in")
        # Two sponsors in one tier share a single grid, not one each.
        self.assertEqual(html_out.count('class="sponsor-grid'), 3)
        # Only the top tier's row gets the larger treatment.
        self.assertEqual(html_out.count("is-featured-row"), 1)
        self.assertEqual(html_out.count("sponsor-card is-featured"), 1)

    def test_sponsor_wall_handles_a_lineup_with_no_tiers_at_all(self):
        html_out = theme.sponsor_wall([{"name": "Just A Name"}])
        self.assertIn("Just A Name", html_out)
        self.assertNotIn("sponsor-tier-heading", html_out)

    def test_sponsor_wall_renders_the_real_configured_lineup(self):
        """End-to-end over the shipped config: every sponsor gets a card and
        every tier a heading, with no unresolved logos."""
        sponsors = sponsor_list()
        html_out = theme.sponsor_wall(sponsors)
        for sponsor in sponsors:
            self.assertIn(html.escape(sponsor["name"]), html_out)
        for tier in {s["tier"] for s in sponsors if s["tier"]}:
            self.assertIn(f'>{html.escape(tier)}</div>', html_out)

    def test_configured_sponsor_logos_and_photos_all_resolve(self):
        """A mistyped path silently drops the image, so assert the shipped
        config actually points at files that exist."""
        self.assertEqual(
            len(gallery_photos()), len(config.PHOTOS),
            "a configured photo failed to resolve — check the path and extension",
        )
        for sponsor in config.SPONSORS:
            if sponsor.get("logo"):
                with self.subTest(sponsor=sponsor["name"]):
                    self.assertTrue(
                        resolve_image_src(sponsor["logo"]).startswith("data:image/"),
                        f"logo did not resolve: {sponsor['logo']}",
                    )

    def test_sponsor_wall_links_only_when_a_url_is_present(self):
        linked = theme.sponsor_wall([{"name": "Acme", "url": "https://acme.example"}])
        self.assertIn('href="https://acme.example"', linked)
        self.assertIn('rel="noopener noreferrer"', linked)

        unlinked = theme.sponsor_wall([{"name": "Acme", "url": ""}])
        self.assertNotIn("<a ", unlinked)
        self.assertIn("Acme", unlinked)

    def test_sponsor_wall_escapes_hostile_names_and_blurbs(self):
        html_out = theme.sponsor_wall([{
            "name": '<img src=x onerror=alert(1)>',
            "tier": '"><script>',
            "blurb": "<b>bold</b>",
        }])
        self.assertNotIn("<img src=x", html_out)
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("<b>bold</b>", html_out)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html_out)

    def test_registration_confirmation_reports_the_saved_booking(self):
        html_out = theme.registration_confirmation(
            "Ada Lovelace", "ada@example.com", 3, ["Alan Turing", "Grace Hopper"]
        )
        self.assertIn("You're in, Ada Lovelace!", html_out)
        self.assertIn("ada@example.com", html_out)
        self.assertIn("3 tickets", html_out)
        self.assertIn("Additional guests (2)", html_out)
        self.assertIn("3 people, including you", html_out)
        # Fire-and-forget email: never claim it was delivered (PART 1).
        self.assertIn("on its way", html_out)
        self.assertNotIn("has been sent", html_out)

    def test_registration_confirmation_omits_guest_rows_for_a_solo_booking(self):
        html_out = theme.registration_confirmation("Solo Guest", "solo@example.com", 1, [])
        self.assertIn("1 ticket", html_out)
        self.assertNotIn("Additional guests", html_out)
        self.assertNotIn("On this booking", html_out)

    def test_registration_confirmation_escapes_guest_supplied_text(self):
        html_out = theme.registration_confirmation(
            "<script>alert(1)</script>", "x@y.com", 2, ["<b>Bold Guest</b>"]
        )
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("<b>Bold Guest</b>", html_out)

    def test_stepper_marks_only_the_current_step_active(self):
        """The Register page lands on step 1, so nothing may be pre-marked
        as done — that told a first-time visitor they'd missed something."""
        first = theme.stepper(1)
        self.assertIn("step-active", first)
        self.assertNotIn("step-done", first)

        last = theme.stepper(3)
        self.assertEqual(last.count("step-done"), 2)
        self.assertIn("step-active", last)

    # ── Hero / theme ────────────────────────────────────────────────────

    def test_hero_carries_the_flyer_details(self):
        """Guests arrive here straight from the printed flyer, so the hero
        has to say the same things it does."""
        html_out = theme.hero()
        self.assertIn(html.escape(config.EVENT_NAME), html_out)
        self.assertIn(html.escape(config.EVENT_TAGLINE), html_out)
        self.assertIn(config.EVENT_TAGLINE_LOCAL, html_out)
        self.assertIn(config.EVENT_THEME, html_out)
        self.assertIn(html.escape(config.VENUE_NAME), html_out)
        self.assertIn(html.escape(config.EVENT_DATE_TEXT), html_out)

    def test_hero_survives_the_optional_theme_fields_being_absent(self):
        """EVENT_THEME / EVENT_TAGLINE_LOCAL are optional extras; dropping
        them must degrade the banner, not break it."""
        with patch.object(config, "EVENT_THEME", ""):
            with patch.object(config, "EVENT_TAGLINE_LOCAL", ""):
                html_out = theme.hero()
        self.assertIn(html.escape(config.EVENT_NAME), html_out)
        self.assertNotIn("hero-theme", html_out)
        self.assertNotIn("hero-subtitle-local", html_out)

    def test_event_strip_states_date_venue_and_dress_theme(self):
        """Register is the landing page, so this strip is the only place
        many guests will see the venue or the dress theme at all."""
        html_out = theme.event_strip()
        self.assertIn(html.escape(config.EVENT_DATE_SHORT), html_out)
        self.assertIn(html.escape(config.VENUE_NAME), html_out)
        self.assertIn(config.EVENT_THEME, html_out)

    def test_flyer_card_renders_nothing_without_an_image(self):
        """config.EVENT_FLYER names a path that may not exist yet, so every
        caller has to tolerate "" — that is the shipped state."""
        self.assertEqual(theme.flyer_card(""), "")
        self.assertEqual(theme.flyer_card("   "), "")

    def test_flyer_card_renders_and_escapes_its_source(self):
        html_out = theme.flyer_card("https://example.com/f.png?a=1&b=2", alt='Ev"il')
        self.assertIn("flyer-card", html_out)
        self.assertIn("&amp;b=2", html_out)
        self.assertNotIn('alt="Ev"il"', html_out)

    def test_event_flyer_is_optional_and_resolves_when_set(self):
        """The flyer was removed for this event because the same details are
        shown on the site, so an empty EVENT_FLYER is valid. When one is set,
        resolve_image_src() must still turn it into a usable src."""
        src = utils.event_flyer_src()
        self.assertTrue(
            src == "" or src.startswith("data:image/") or src.startswith("https://"),
            "config.EVENT_FLYER did not resolve",
        )

    def test_inlined_images_stay_within_a_sane_page_weight(self):
        """Every local image is base64'd into the page HTML and re-sent on
        EVERY Streamlit rerun — there is no browser cache to save us. A
        full-size camera JPEG dropped in here would quietly make the whole
        app feel broken on phone data, with nothing in the UI to explain it.

        Budget is generous (well under the per-file MAX_INLINE_IMAGE_BYTES
        limit x the number of images) but finite: it fails loudly the moment
        someone commits an unresized photo.
        """
        budget_bytes = 4 * 1024 * 1024
        payload = len(utils.event_flyer_src())
        payload += sum(len(p["src"]) for p in utils.gallery_photos())
        payload += sum(len(s["logo"]) for s in utils.sponsor_list() if s["logo"])
        self.assertLess(
            payload, budget_bytes,
            f"inlined Home-page images total {payload / 1024 / 1024:.1f}MB of base64 — "
            "resize the originals (see assets/README.md)",
        )

    def test_every_configured_photo_resolves(self):
        """Same reason as the flyer: a mistyped path drops the photo
        silently, so the gallery shrinks with no error anywhere."""
        self.assertEqual(
            len(gallery_photos()), len(config.PHOTOS),
            "a configured photo failed to resolve — check the path and extension",
        )

    def test_event_flyer_src_uses_the_same_allowlist_as_every_other_image(self):
        with patch.object(config, "EVENT_FLYER", "javascript:alert(1)"):
            self.assertEqual(utils.event_flyer_src(), "")
        with patch.object(config, "EVENT_FLYER", "https://example.com/flyer.png"):
            self.assertEqual(utils.event_flyer_src(), "https://example.com/flyer.png")

    def test_stat_accents_match_the_themed_tokens(self):
        """stat_tiles() drops any accent it doesn't recognise, so the set has
        to track the CSS token names — a rename that misses one silently
        turns those tiles grey."""
        self.assertEqual(
            theme._STAT_ACCENTS,
            {"gold", "ok", "warn", "err", "info", "rust", "turquoise"},
        )
        for accent in theme._STAT_ACCENTS:
            with self.subTest(accent=accent):
                self.assertIn(f"--{accent}", theme._CSS)
                self.assertIn(f"accent-{accent}", theme._CSS)

    def test_landing_page_is_a_real_page(self):
        """config.LANDING_PAGE feeds straight into the router's page list."""
        self.assertEqual(config.LANDING_PAGE, "Register")
        self.assertIn(
            config.LANDING_PAGE,
            ["Home", "Register", "My QR", "Scanner", "Admin"],
        )

    # ── Group discounts ─────────────────────────────────────────────────

    def test_group_discount_prices_at_every_boundary(self):
        """$50 individual, $25 from 26 tickets, $10 from 76 — checked on both
        sides of each boundary. An off-by-one here charges the wrong amount
        rather than failing loudly, and a guest who priced their group off the
        table would Zelle a number the app disagrees with."""
        for tickets, expected_cents in [
            (1, 5000), (2, 5000), (25, 5000),              # below the first tier
            (26, 2500), (27, 2500), (75, 2500),            # first tier, 26 INCLUSIVE
            (76, 1000), (77, 1000), (100, 1000),           # second tier, 76 INCLUSIVE
        ]:
            with self.subTest(tickets=tickets):
                self.assertEqual(config.ticket_price_cents_for(tickets), expected_cents)

    def test_group_discount_totals(self):
        self.assertEqual(config.booking_total_cents(1), 5000)      # $50.00
        self.assertEqual(config.booking_total_cents(25), 125000)   # $1,250.00
        self.assertEqual(config.booking_total_cents(26), 127500)   # $1,250 + $25
        self.assertEqual(config.booking_total_cents(75), 250000)   # $1,250 + 50×$25
        self.assertEqual(config.booking_total_cents(76), 251000)   # + $10
        self.assertEqual(config.booking_total_cents(100), 275000)  # max seats: $1,250 + $1,250 + $250
        self.assertEqual(config.booking_total_dollars(26), 1275.0)

    def test_group_discount_savings_are_zero_below_the_first_tier(self):
        self.assertEqual(config.booking_savings_cents(1), 0)
        self.assertEqual(config.booking_savings_cents(25), 0)
        self.assertEqual(config.booking_savings_cents(26), 2500)   # $1,300 - $1,275
        self.assertEqual(config.booking_savings_cents(76), 129000) # $3,800 - $2,510

    def test_group_discount_never_raises_on_a_garbage_ticket_count(self):
        """The selector is a client-side widget; a bad value must fall back
        to the FULL price, never to a discount nobody earned."""
        base = config.ticket_price_cents()
        for bad in (None, "", "abc", [], {}):
            with self.subTest(value=bad):
                self.assertEqual(config.ticket_price_cents_for(bad), base)
        self.assertEqual(config.booking_total_cents(None), 0)
        self.assertEqual(config.booking_savings_cents("nope"), 0)

    def test_seat_tiers_are_absolute_prices(self):
        """Seat tiers are fixed prices, not discounts off a base — changing
        TICKET_PRICE_CENTS leaves every configured seat unchanged."""
        with patch.object(config, "TICKET_PRICE_CENTS", 10000):
            self.assertEqual(config.ticket_price_cents_for(1), 5000)
            self.assertEqual(config.ticket_price_cents_for(25), 5000)
            self.assertEqual(config.ticket_price_cents_for(26), 2500)
            self.assertEqual(config.ticket_price_cents_for(76), 1000)
        # The base price is still the fallback for seat numbers past the tiers.
        with patch.object(config, "SEAT_TIERS", ((26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(config.ticket_price_cents_for(1), 5000)
            self.assertEqual(config.ticket_price_cents_for(25), 5000)

    def test_seat_tier_price_falls_back_to_base_for_unconfigured_seats(self):
        """A seat number past the configured tiers pays the base price rather
        than becoming free or raising an error."""
        with patch.object(config, "SEAT_TIERS", ((1, 5, 5000),)):
            self.assertEqual(config.ticket_price_cents_for(1), 5000)
            self.assertEqual(config.ticket_price_cents_for(10), 5000)

    def test_price_tiers_cover_every_booking_size_without_gaps(self):
        tiers = config.price_tiers()
        self.assertEqual(tiers[0]["min"], 1)
        self.assertEqual(tiers[-1]["max"], 100, "the top tier ends at the booking cap")
        for earlier, later in zip(tiers, tiers[1:]):
            self.assertEqual(later["min"], earlier["max"] + 1, "gap between tiers")
        # And the table must agree with what guests are actually charged.
        for tier in tiers:
            self.assertEqual(
                tier["price_cents"], config.ticket_price_cents_for(tier["min"])
            )

    def test_price_tiers_are_sorted_even_if_the_config_is_not(self):
        with patch.object(config, "SEAT_TIERS", ((76, 100, 1000), (26, 75, 2500), (1, 25, 5000))):
            self.assertEqual(config.ticket_price_cents_for(26), 2500)
            self.assertEqual(config.ticket_price_cents_for(76), 1000)
            self.assertEqual([t["min"] for t in config.price_tiers()], [1, 26, 76])

    def test_next_price_tier_points_at_the_next_cheaper_one(self):
        self.assertEqual(config.next_price_tier(1)["min"], 26)
        self.assertEqual(config.next_price_tier(25)["min"], 26)
        self.assertEqual(config.next_price_tier(26)["min"], 76)
        self.assertIsNone(config.next_price_tier(76), "already on the best tier")
        self.assertIsNone(config.next_price_tier(100))

    def test_next_price_tier_is_hidden_when_it_exceeds_the_booking_cap(self):
        """Never advertise a price the form won't let anyone buy."""
        with patch.object(config, "MAX_TICKETS_PER_REGISTRATION", 50):
            self.assertEqual(config.next_price_tier(1)["min"], 26)
            self.assertIsNone(config.next_price_tier(30), "76+ is past the cap of 50")

    def test_top_discount_tier_is_actually_bookable(self):
        """The whole point of the 76+ tier is that someone can reach it —
        a per-registration cap below it would make it advertising fiction."""
        largest_tier_min = max(start for start, _end, _price in config.SEAT_TIERS)
        self.assertGreaterEqual(config.MAX_TICKETS_PER_REGISTRATION, largest_tier_min)

    # ── Group discounts: rendering ──────────────────────────────────────

    def _tier_rows(self, html_out):
        """Split rendered tier-table HTML back into one string per row."""
        return [f'<div class="tier-row{part}' for part in html_out.split('<div class="tier-row')[1:]]

    def test_price_tier_table_lists_every_tier_and_marks_the_current_one(self):
        for tickets, expected_price, expected_range in [
            (1, "$50.00", "1–25"),
            (25, "$50.00", "1–25"),
            (26, "$25.00", "26–75"),
            (76, "$10.00", "76–100"),
        ]:
            with self.subTest(tickets=tickets):
                html_out = theme.price_tier_table(config.price_tiers(), ticket_count=tickets)
                # The whole table is always shown — that's the point of
                # putting it above the selector.
                for price in ("$50.00", "$25.00", "$10.00"):
                    self.assertIn(price, html_out)
                # ...with exactly one row highlighted: the one they're on.
                active = [row for row in self._tier_rows(html_out) if "is-active" in row]
                self.assertEqual(len(active), 1)
                self.assertIn(expected_price, active[0])
                self.assertIn(expected_range, active[0])

    def test_price_tier_table_highlights_nothing_before_a_count_is_chosen(self):
        html_out = theme.price_tier_table(config.price_tiers(), ticket_count=0)
        self.assertNotIn("is-active", html_out)

    def test_price_tier_table_renders_nothing_without_tiers(self):
        self.assertEqual(theme.price_tier_table([]), "")

    def test_tier_range_labels(self):
        self.assertEqual(theme.tier_range_label({"min": 1, "max": 10}), "1–10")
        self.assertEqual(theme.tier_range_label({"min": 22, "max": None}), "22+")
        self.assertEqual(theme.tier_range_label({"min": 5, "max": 5}), "5")

    def test_total_card_shows_the_discounted_price_and_savings(self):
        html_out = theme.total_card(26, 127500, savings=25.0)
        self.assertIn("$1,275.00", html_out)
        self.assertIn("26 seats selected", html_out)
        self.assertIn("you save $25.00", html_out)

    def test_total_card_hides_the_savings_line_when_there_is_no_discount(self):
        html_out = theme.total_card(1, 5000, savings=0.0)
        self.assertIn("$50.00", html_out)
        self.assertIn("1 seat selected", html_out)
        self.assertNotIn("you save", html_out)

    def test_next_tier_nudge_states_the_new_price_and_renders_nothing_at_the_top(self):
        tier = config.next_price_tier(1)
        html_out = theme.next_tier_nudge(1, tier, config.ticket_price_cents_for(1))
        self.assertIn("$25.00", html_out)
        self.assertIn("26", html_out)

        self.assertEqual(theme.next_tier_nudge(76, None, 1000), "")
        self.assertEqual(theme.next_tier_nudge(76, config.next_price_tier(76), 1000), "")

    def test_expected_revenue_prices_each_booking_at_its_own_tier(self):
        """A flat tickets × base_price would over-report the take on every
        group, which is exactly the number an organiser reconciles against
        their Zelle history."""
        self._register(name="Solo Guest", email="solo.rev@example.com", ticket_count=1)
        self._register(
            name="Group Guest", email="group.rev@example.com", ticket_count=26,
            plus_one_name="\n".join(_guest_name(i) for i in range(25)),
        )
        stats = get_stats()
        self.assertEqual(stats["total_tickets"], 27)
        # 1 × $50 + seats 1..26 = $50 + $1,275 = $1,325.00, NOT 27 × $50 = $1,350.00
        self.assertEqual(stats["revenue"], 1325.0)


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPartyCheckIn)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
