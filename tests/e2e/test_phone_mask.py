"""Flow 12: the live +1-XXX-XXX-XXXX mask on the Register page's phone field.

The mask is client-side JavaScript reaching out of a Streamlit component
iframe into the parent document (utils.phone_input_mask_js), which is exactly
the kind of thing that breaks silently on a Streamlit upgrade — so it is
asserted here against a real browser, not just unit-tested as a string.
"""
import pytest
from playwright.sync_api import expect

from .helpers import fill_registration_form, goto, submit_registration

PHONE_FIELD = "Phone Number *"


def _phone_input(page):
    return page.get_by_label(PHONE_FIELD)


def test_phone_field_is_prefilled_with_the_country_code(page, base_url, reset_db):
    goto(page, base_url, "Register")
    expect(_phone_input(page)).to_have_value("+1-", timeout=10000)


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("555", "+1-555"),
        ("5551", "+1-555-1"),
        ("5551234", "+1-555-123-4"),
        ("5551234567", "+1-555-123-4567"),
        # Extra digits past a full US number are dropped, not appended
        ("55512345678999", "+1-555-123-4567"),
        # A pasted-style country code is absorbed, not treated as digit one
        ("15551234567", "+1-555-123-4567"),
    ],
    ids=["area", "partial", "mid", "full", "overflow", "with-country-code"],
)
def test_phone_mask_formats_digits_as_they_are_typed(page, base_url, reset_db, typed, expected):
    goto(page, base_url, "Register")
    field = _phone_input(page)
    expect(field).to_have_value("+1-", timeout=10000)

    # press_sequentially types one key at a time, so this exercises the real
    # per-keystroke path rather than a single programmatic value set.
    field.click()
    field.press_sequentially(typed, delay=30)

    expect(field).to_have_value(expected, timeout=5000)


def test_phone_mask_restores_the_prefix_when_the_field_is_cleared(page, base_url, reset_db):
    goto(page, base_url, "Register")
    field = _phone_input(page)
    expect(field).to_have_value("+1-", timeout=10000)

    field.click()
    field.press_sequentially("5551234567", delay=30)
    expect(field).to_have_value("+1-555-123-4567", timeout=5000)

    field.fill("")
    expect(field).to_have_value("+1-", timeout=5000)


def test_phone_mask_leaves_a_non_us_country_code_alone(page, base_url, reset_db):
    """Reshaping "+44 20 7946 0958" into a plausible-looking US number would
    hide the problem; the mask keeps its hands off so the server can reject
    it as non-US."""
    goto(page, base_url, "Register")
    field = _phone_input(page)
    expect(field).to_have_value("+1-", timeout=10000)

    field.click()
    field.press_sequentially("+44 20 7946 0958", delay=30)
    # Typed verbatim, digits ungrouped — no US number was invented from it.
    expect(field).to_have_value("+1-+44 20 7946 0958", timeout=5000)

    fill_registration_form(
        page, name="Non Us Guest", email="non.us.guest@example.com",
        phone="", zelle_ref="ZELLE-NONUS001", tickets=1, agree=True,
    )
    submit_registration(page)

    expect(page.get_by_text("valid 10-digit US phone number", exact=False)).to_be_visible(timeout=10000)
    assert reset_db.get_guest_by_email("non.us.guest@example.com") is None


def test_masked_number_registers_and_is_stored_normalized(page, base_url, reset_db):
    goto(page, base_url, "Register")
    field = _phone_input(page)
    expect(field).to_have_value("+1-", timeout=10000)

    field.click()
    field.press_sequentially("5559876543", delay=30)
    expect(field).to_have_value("+1-555-987-6543", timeout=5000)

    email = "masked.guest@example.com"
    fill_registration_form(
        page, name="Masked Guest", email=email, phone="",
        zelle_ref="ZELLE-MASKED001", tickets=1, agree=True,
    )
    submit_registration(page)

    # A successful submit lands on Home with the confirmation card on top.
    expect(page.get_by_text("You're in, Masked Guest", exact=False)).to_be_visible(timeout=15000)
    assert reset_db.get_guest_by_email(email)["phone"] == "+1-555-987-6543"
