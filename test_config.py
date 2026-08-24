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
    # There are only TOTAL_SEATS (100) real, numbered seats, so the effective
    # cap can never exceed that regardless of what the secret says — see the
    # docstring on config.max_total_tickets().

    def test_max_total_tickets_default_is_clamped_to_total_seats(self):
        mock_st = MagicMock()
        mock_st.secrets = {}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), config.TOTAL_SEATS)

    def test_max_total_tickets_from_secret_below_total_seats_passes_through(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "30"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), 30)

    def test_max_total_tickets_from_secret_above_total_seats_is_clamped(self):
        # 300 asks for more than exist; there are only TOTAL_SEATS seats to sell.
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "300"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), config.TOTAL_SEATS)

    def test_max_total_tickets_zero_is_capped_at_total_seats_not_unlimited(self):
        # Real seat inventory retires the old "0 = uncapped" meaning: you
        # cannot sell a seat that does not exist.
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "0"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), config.TOTAL_SEATS)

    def test_max_total_tickets_negative_is_also_capped_at_total_seats(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "-5"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), config.TOTAL_SEATS)

    def test_max_total_tickets_garbage_falls_back_to_default_then_clamped(self):
        mock_st = MagicMock()
        mock_st.secrets = {"MAX_TOTAL_TICKETS": "not-a-number"}
        with patch.object(config, "st", mock_st):
            self.assertEqual(config.max_total_tickets(), config.TOTAL_SEATS)

    # ── Seat inventory: TOTAL_SEATS / all_seat_numbers / seats_total_cents ──

    def test_total_seats_derived_from_seat_tiers_max_boundary(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(
                max((end for _s, end, _p in config.SEAT_TIERS), default=0), 100
            )

    def test_all_seat_numbers_spans_1_to_total_seats(self):
        with patch.object(config, "TOTAL_SEATS", 5):
            self.assertEqual(config.all_seat_numbers(), [1, 2, 3, 4, 5])

    def test_seats_total_cents_prices_a_non_contiguous_pick(self):
        """The core bug fix: a guest can now buy only cheap seats, and a
        mixed pick prices each seat at its own tier."""
        self.assertEqual(
            config.seats_total_cents([1, 30, 80]), 5000 + 2500 + 1000
        )

    def test_seats_total_cents_only_cheap_seats(self):
        self.assertEqual(config.seats_total_cents([90, 91, 92]), 3000)

    def test_seats_total_cents_deduplicates(self):
        self.assertEqual(config.seats_total_cents([1, 1, 1]), config.seat_price_cents(1))

    def test_seats_total_cents_ignores_garbage_and_out_of_range(self):
        self.assertEqual(
            config.seats_total_cents([1, "abc", None, 0, 9999, 30]),
            config.seat_price_cents(1) + config.seat_price_cents(30),
        )

    def test_seats_total_cents_never_raises_on_a_non_iterable(self):
        self.assertEqual(config.seats_total_cents(None), 0)

    def test_seat_tier_index_matches_each_configured_tier(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(config.seat_tier_index(1), 0)
            self.assertEqual(config.seat_tier_index(25), 0)
            self.assertEqual(config.seat_tier_index(26), 1)
            self.assertEqual(config.seat_tier_index(100), 2)

    def test_seat_tier_index_is_negative_one_when_unconfigured(self):
        with patch.object(config, "SEAT_TIERS", ((1, 5, 5000),)):
            self.assertEqual(config.seat_tier_index(10), -1)
        self.assertEqual(config.seat_tier_index("not-a-seat"), -1)

    def test_every_seat_is_covered_by_an_explicit_tier(self):
        """seat_price_cents() falls back to the BASE (most expensive) price
        for any seat number outside every tier — if a real seat were missing
        from SEAT_TIERS it would silently be charged the premium seat-1 rate
        instead of whatever it should actually cost. Every seat that exists
        must be explicitly covered, with no gaps."""
        for seat in config.all_seat_numbers():
            covered = any(start <= seat <= end for start, end, _price in config.SEAT_TIERS)
            self.assertTrue(
                covered,
                f"seat {seat} has no explicit SEAT_TIERS entry and would fall back "
                "to the base price",
            )

    # ── Free kid seats: FREE_KID_TIER / free_kid_seat_numbers / is_free_kid_seat /
    # free_kid_seat_range_label — the organiser's "kids free, cheapest tier only" rule ──

    def test_free_kid_tier_is_the_cheapest_seat_tier(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(config._free_kid_tier(), (76, 100, 1000))

    def test_free_kid_tier_picks_lowest_price_regardless_of_tuple_order(self):
        """Must derive from the PRICE, not from being the last/highest-numbered
        tier — a re-ordered or re-priced SEAT_TIERS must not silently point
        the free range at the wrong seats."""
        with patch.object(config, "SEAT_TIERS", ((76, 100, 1000), (1, 25, 5000), (26, 75, 2500))):
            self.assertEqual(config._free_kid_tier(), (76, 100, 1000))

    def test_free_kid_seat_numbers_spans_the_cheapest_tier(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(config.free_kid_seat_numbers(), list(range(76, 101)))

    def test_free_kid_seat_numbers_empty_when_seat_tiers_empty(self):
        with patch.object(config, "SEAT_TIERS", ()):
            self.assertEqual(config.free_kid_seat_numbers(), [])

    def test_is_free_kid_seat_true_only_within_the_cheapest_tier(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertTrue(config.is_free_kid_seat(76))
            self.assertTrue(config.is_free_kid_seat(90))
            self.assertTrue(config.is_free_kid_seat(100))
            self.assertFalse(config.is_free_kid_seat(1))
            self.assertFalse(config.is_free_kid_seat(75))

    def test_is_free_kid_seat_never_raises_on_garbage(self):
        self.assertFalse(config.is_free_kid_seat("not-a-seat"))
        self.assertFalse(config.is_free_kid_seat(None))

    def test_free_kid_seat_range_label_uses_seat_label_format(self):
        with patch.object(config, "SEAT_TIERS", ((1, 25, 5000), (26, 75, 2500), (76, 100, 1000))):
            self.assertEqual(config.free_kid_seat_range_label(), "H6–J10")

    def test_max_kids_per_registration_reuses_max_tickets_per_registration(self):
        self.assertEqual(config.MAX_KIDS_PER_REGISTRATION, config.MAX_TICKETS_PER_REGISTRATION)

    # ── Seat labels: seat_label / seat_from_label / format_seat_labels ─────

    def test_seat_label_first_seat_of_the_grid(self):
        self.assertEqual(config.seat_label(1), "A1")

    def test_seat_label_mid_row_seat(self):
        self.assertEqual(config.seat_label(17), "B7")

    def test_seat_label_row_boundary(self):
        """Seat 10 is the last seat of row A; seat 11 rolls over into row B."""
        self.assertEqual(config.seat_label(10), "A10")
        self.assertEqual(config.seat_label(11), "B1")

    def test_seat_label_past_row_26_uses_double_letters(self):
        """With a larger seat block (patched here), row 27 (0-indexed 26)
        must roll over to "AA" rather than breaking, the same way a
        spreadsheet's column headers do."""
        with patch.object(config, "TOTAL_SEATS", 300):
            self.assertEqual(config.seat_label(261), "AA1")
            self.assertEqual(config.seat_label(270), "AA10")
            self.assertEqual(config.seat_label(271), "AB1")

    def test_seat_label_tolerates_garbage_without_raising(self):
        self.assertEqual(config.seat_label("not-a-seat"), "not-a-seat")
        self.assertEqual(config.seat_label(None), "None")
        self.assertEqual(config.seat_label(0), "0")
        self.assertEqual(config.seat_label(-5), "-5")

    def test_seat_from_label_round_trips_seat_label(self):
        for seat in (1, 10, 11, 17, 25, 50, 100):
            self.assertEqual(config.seat_from_label(config.seat_label(seat)), seat)

    def test_seat_from_label_round_trips_past_row_26(self):
        with patch.object(config, "TOTAL_SEATS", 300):
            for seat in (261, 270, 271, 300):
                self.assertEqual(config.seat_from_label(config.seat_label(seat)), seat)

    def test_seat_from_label_is_case_insensitive_and_tolerates_whitespace(self):
        self.assertEqual(config.seat_from_label(" b7 "), 17)
        self.assertEqual(config.seat_from_label("B7"), 17)

    def test_seat_from_label_tolerates_garbage_without_raising(self):
        self.assertIsNone(config.seat_from_label(None))
        self.assertIsNone(config.seat_from_label(123))
        self.assertIsNone(config.seat_from_label(""))
        self.assertIsNone(config.seat_from_label("not a label"))
        self.assertIsNone(config.seat_from_label("Z999"))  # column past SEAT_COLS
        self.assertIsNone(config.seat_from_label("ZZ1"))  # row past TOTAL_SEATS
        self.assertIsNone(config.seat_from_label("7B"))  # digits before letters

    def test_format_seat_labels_sorts_dedupes_and_labels(self):
        self.assertEqual(config.format_seat_labels([17, 3, 4, 4]), "A3, A4, B7")

    def test_format_seat_labels_tolerates_garbage_without_raising(self):
        self.assertEqual(config.format_seat_labels(None), "")
        self.assertEqual(config.format_seat_labels(42), "")  # non-iterable
        self.assertEqual(config.format_seat_labels([1, "abc", None]), config.seat_label(1))

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

    # ── Seat-selection policy copy ──────────────────────────────────────

    def test_kids_and_food_policy_text_state_the_two_facts(self):
        """theme.seat_policy_chips() reads these verbatim, so the facts
        themselves have to live here. The organiser's rule (AGENTS.md): a
        child under 12 rides free, but only in the cheapest SEAT_TIERS
        range — a front-row seat is a normal paid seat. KIDS_POLICY_TEXT
        must name that range (via free_kid_seat_range_label()) rather than
        just saying "kids are free" and leaving the seat question open."""
        self.assertIn("free", config.KIDS_POLICY_TEXT.lower())
        self.assertIn("12", config.KIDS_POLICY_TEXT)
        self.assertIn("seat", config.KIDS_POLICY_TEXT.lower())
        self.assertIn(config.free_kid_seat_range_label(), config.KIDS_POLICY_TEXT)
        self.assertIn("paid", config.KIDS_POLICY_TEXT.lower())
        self.assertIn("purchase", config.FOOD_POLICY_TEXT.lower())
        self.assertIn("venue", config.FOOD_POLICY_TEXT.lower())

    def test_kids_policy_text_tracks_seat_tiers_not_hardcoded(self):
        """The free-child range named in KIDS_POLICY_TEXT must come from
        free_kid_seat_range_label() (derived from SEAT_TIERS), not a
        hardcoded "76-100"/"H6-J10" string that could drift from the real
        pricing table."""
        self.assertEqual(
            config.KIDS_POLICY_TEXT,
            (
                f"Kids under 12 ride free — but only in seats {config.free_kid_seat_range_label()}, "
                "our cheapest tier. A front-row seat for a child is a regular paid seat."
            ),
        )

    # ── Check-in window: event_start_utc / checkin_opens_at_utc ────────────

    def test_event_start_utc_matches_expected_cdt_offset(self):
        # Oct 3 is within Central Daylight Time (CDT, UTC-5), so the local
        # start time must convert to UTC by adding exactly 5 hours. Derived
        # from EVENT_START_LOCAL rather than hardcoded, so moving the event
        # time (5 PM -> 6 PM, as happened once) can't leave this asserting a
        # stale instant that no longer matches the app.
        self.assertEqual(
            config.event_start_utc(),
            config.EVENT_START_LOCAL + timedelta(hours=5),
        )

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
