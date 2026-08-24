"""
Party Check-In System — Config Module Test Suite
Tests config.py: secret access, computed helpers, and the fail-never
guarantees needed on a fresh deploy that has no secrets file at all.

Run with: python -m unittest test_config -v
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import config


class _RaisingSecrets:
    """Stand-in for the `streamlit` module whose `.secrets` access raises,
    mimicking StreamlitSecretsFileNotFoundError on a deploy with no secrets
    file configured at all."""

    @property
    def secrets(self):
        raise RuntimeError("No secrets found. Valid paths for a secrets.toml file are: ...")


class TestConfig(unittest.TestCase):
    def setUp(self):
        # Keep tests deterministic regardless of the host machine's env vars.
        self._env_keys = (
            "CFG_TEST_KEY", "TICKET_PRICE_CENTS", "MAX_TOTAL_TICKETS", "ZELLE_INFO", "APP_URL",
        )
        self._env_backup = {k: os.environ.pop(k, None) for k in self._env_keys}

    def tearDown(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ── get_secret ───────────────────────────────────────────────────────

    def test_get_secret_reads_from_streamlit_secrets(self):
        mock_st = MagicMock()
        mock_st.secrets = {"CFG_TEST_KEY": "from-secrets"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.get_secret("CFG_TEST_KEY", "default"), "from-secrets")

    def test_get_secret_falls_back_to_env_var(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        os.environ["CFG_TEST_KEY"] = "from-env"
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.get_secret("CFG_TEST_KEY", "default"), "from-env")

    def test_get_secret_falls_back_to_default(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.get_secret("CFG_TEST_KEY", "default-value"), "default-value")

    def test_get_secret_never_raises_when_secrets_file_missing(self):
        # This is the crash that used to take down the whole app on a fresh
        # deploy with no secrets.toml configured at all.
        with patch.object(config, "st", _RaisingSecrets()):
            result = config.get_secret("CFG_TEST_KEY", "safe-default")
        self.assertEqual(result, "safe-default")

    def test_get_secret_never_raises_when_st_is_none(self):
        # Mirrors the `import streamlit as st` failing at module load time.
        with patch.object(config, "st", None):
            self.assertEqual(config.get_secret("CFG_TEST_KEY", "safe-default"), "safe-default")

    # ── get_secret_int ───────────────────────────────────────────────────

    def test_get_secret_int_valid_numeric_value(self):
        mock_st = MagicMock()
        mock_st.secrets = {"CFG_TEST_KEY": "42"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.get_secret_int("CFG_TEST_KEY", 99), 42)

    def test_get_secret_int_non_numeric_returns_default(self):
        mock_st = MagicMock()
        mock_st.secrets = {"CFG_TEST_KEY": "not-a-number"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.get_secret_int("CFG_TEST_KEY", 77), 77)

    def test_get_secret_int_never_raises_when_secrets_file_missing(self):
        with patch.object(config, "st", _RaisingSecrets()):
            self.assertEqual(config.get_secret_int("CFG_TEST_KEY", 55), 55)

    # ── ticket_price_dollars ─────────────────────────────────────────────

    def test_ticket_price_ignores_a_stale_secret(self):
        """The price is a code constant, NOT a secret.

        A leftover TICKET_PRICE_CENTS in the Streamlit Cloud dashboard used
        to win over the shipped price, so a deployed price change silently
        did nothing. Guarding it here because the failure is invisible: the
        app works perfectly and just charges the wrong amount.
        """
        mock_st = MagicMock()
        mock_st.secrets = {"TICKET_PRICE_CENTS": "2000"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.ticket_price_dollars(), 50.0)
            self.assertEqual(config.ticket_price_cents(), 5000)

    def test_ticket_price_ignores_a_stale_env_var(self):
        os.environ["TICKET_PRICE_CENTS"] = "2000"
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.ticket_price_dollars(), 50.0)

    def test_ticket_price_dollars_default(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.ticket_price_dollars(), 50.0)

    # ── max_total_tickets ────────────────────────────────────────────────

    def test_max_total_tickets_default(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), 225)

    def test_max_total_tickets_from_secret(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "300"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), 300)

    def test_max_total_tickets_zero_disables_cap(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "0"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), 0)

    def test_max_total_tickets_garbage_falls_back_to_default(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "not-a-number"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), 225)

    # ── zelle_info ───────────────────────────────────────────────────────

    def test_zelle_info_explicit_value_passes_through(self):
        mock_st = MagicMock()
        mock_st.secrets = {"ZELLE_INFO": "myhandle@example.com"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.zelle_info(), "myhandle@example.com")

    def test_zelle_info_falls_back_when_unset(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.zelle_info(), config._DEFAULT_ZELLE)

    def test_zelle_info_falls_back_when_blank(self):
        mock_st = MagicMock()
        mock_st.secrets = {"ZELLE_INFO": "   "}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.zelle_info(), config._DEFAULT_ZELLE)

    def test_zelle_info_falls_back_on_placeholder_value(self):
        mock_st = MagicMock()
        mock_st.secrets = {"ZELLE_INFO": config._PLACEHOLDER_ZELLE}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.zelle_info(), config._DEFAULT_ZELLE)

    def test_zelle_info_falls_back_on_organizer_will_share_text(self):
        mock_st = MagicMock()
        mock_st.secrets = {"ZELLE_INFO": "Organizer will share closer to the event"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.zelle_info(), config._DEFAULT_ZELLE)

    # ── days_until_event ─────────────────────────────────────────────────

    def test_days_until_event_never_negative_for_past_date(self):
        with patch.object(config, "EVENT_DATE", datetime(2000, 1, 1)):
            self.assertEqual(config.days_until_event(), 0)

    def test_days_until_event_positive_for_future_date(self):
        future = datetime.now() + timedelta(days=30)
        with patch.object(config, "EVENT_DATE", future):
            # Allow either 29 or 30 depending on the microsecond gap between
            # computing `future` above and datetime.now() inside the call.
            self.assertIn(config.days_until_event(), (29, 30))

    # ── qr_prefix ────────────────────────────────────────────────────────

    def test_qr_prefix_derived_from_event_year(self):
        self.assertEqual(config.qr_prefix(), f"PARTY{config.EVENT_DATE.year}")

    # ── Check-in window: event_start_utc / checkin_opens_at_utc ────────────

    def test_event_start_utc_matches_expected_cdt_offset(self):
        # EVENT_START_LOCAL is 5:00 PM on Oct 3, 2026, in America/Chicago.
        # Oct 3 is within Central Daylight Time (CDT, UTC-5), so this must
        # convert to 10:00 PM UTC.
        self.assertEqual(config.event_start_utc(), datetime(2026, 10, 3, 22, 0))

    def test_checkin_opens_at_utc_gap_equals_lead_hours(self):
        gap = config.event_start_utc() - config.checkin_opens_at_utc()
        self.assertEqual(gap, timedelta(hours=config.CHECKIN_LEAD_HOURS))

    def test_checkin_opens_at_text_is_non_empty_human_readable_string(self):
        text = config.checkin_opens_at_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)
        # Should mention the event day/year somewhere in the rendered text.
        self.assertIn("2026", text)

    def test_event_start_utc_never_raises_when_tz_database_missing(self):
        with patch.object(config, "ZoneInfo", None):
            result = config.event_start_utc()
        self.assertIsInstance(result, datetime)

    def test_checkin_opens_at_utc_never_raises_when_tz_database_missing(self):
        with patch.object(config, "ZoneInfo", None):
            result = config.checkin_opens_at_utc()
        self.assertIsInstance(result, datetime)

    def test_checkin_opens_at_text_never_raises_when_tz_database_missing(self):
        with patch.object(config, "ZoneInfo", None):
            result = config.checkin_opens_at_text()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
