# DFW Yakshagana Havyasis — Party Check-In

Event registration and check-in for **DFW Yakshagana Havyasis**, built with **Streamlit** and hosted free on Streamlit Community Cloud. Zelle payments, emailed QR codes, self check-in with audio announcements, and an admin dashboard.

- **Event:** DFW Yakshagana Havyasis · date TBD
- **Venue:** DFW Metroplex · address TBD
- **Theme:** Yakshagana · traditional attire encouraged
- **Live app:** see Streamlit Cloud dashboard (URL kept out of this public repo to avoid crawler/bot traffic)
- **Repo:** your-org/party-checkin-generic (branch `main`)
- **Database:** Supabase PostgreSQL
- **Payment:** Zelle → `dfwygana@gmail.com` · $50 per ticket (1–25), $25 per ticket (26–75), $10 per ticket (76+)

---

## Architecture

```
                        INTERNET
                            |
                    [ Your Guests ]
                            |
              party-checkin-…streamlit.app
                            |
                +-----------+----------+
                |                      |
         [ Streamlit Cloud ]     [ Supabase ]
         Runs the app             Stores data
         FREE tier                FREE tier
```

The code is layered so that business logic is testable without a browser:

| File | Responsibility |
|------|----------------|
| `config.py` | Single source of truth for event details (name, date, venue) and secret access. Nothing else reads `st.secrets` for config. |
| `utils.py` | Database models, the service layer (register / check-in / band / delete / lookups / reporting), QR generation, email, validation. No Streamlit UI. |
| `theme.py` | The design system: CSS custom-property tokens plus HTML component builders (hero, stat tiles, payment card, stepper, …). |
| `streamlit_app.py` | Pages and navigation only. Renders `theme` components and calls `utils` service functions — it never touches the ORM or opens a DB session. |
| `test_party_checkin.py` | Unit tests for the service layer, validation, and security behavior. |
| `tests/e2e/` | Playwright end-to-end tests that drive the real UI. |

**Why it is layered this way:** Streamlit re-executes the entire script on every user interaction. Anything expensive left at module scope or inline in a page runs on every single click. Keeping DB work behind cached service calls is what keeps the app responsive against a remote Postgres.

---

## Features

| Feature | Description |
|---------|-------------|
| **Zelle Payments** | Guests pay via Zelle, then submit their transaction reference |
| **Auto QR Email** | QR code is emailed after registration, on a background thread so the guest isn't held up by the SMTP round-trip |
| **Bulk registration** | One person can buy up to 100 tickets and list every guest's name |
| **Group discounts** | Per-ticket price drops for bigger bookings — $50 (1–25), $25 (26–75), $10 (76+) |
| **My QR lookup** | Guests re-find their QR code by email **or phone number**, or via the link in their email |
| **Self Check-In** | Camera scan, or search by phone / email / ticket ID — always confirmed against the guest's details before anyone is checked in |
| **Check-in window** | Check-in stays locked until 2 hours before the party, with an admin override |
| **Audio Announcement** | Speaks name + ticket count for staff via browser TTS |
| **Wristband Tracking** | Prevents double distribution |
| **Admin Dashboard** | Live stats, a spreadsheet for fast check-in/band/delete, and recent check-ins |
| **Party Buzz** | Public, aggregate-only activity stats and charts on the Home page |
| **CSV Export** | Download the guest list anytime (formula-injection safe) |
| **Submission audit log** | Every form submit — successful or not — is recorded |
| **Photos & sponsors** | Home page photo gallery and tiered sponsor wall, filled in from `config.py` |

### Look & feel

The app ships with a dark, event-neutral theme. Update `config.EVENT_THEME`,
`config.EVENT_THEME_NOTE`, and the assets in `assets/` to match your printed flyer
before the registration link goes out.

| Piece | Where |
|---|---|
| Palette (`--leather`, `--tan`, `--gold`, `--rust`, `--turquoise`) | `theme.py` `:root` tokens |
| Display face **Rye** (western) | Hero title + brand bar only — decorative, so it's used sparingly |
| Heading face **Bitter** (slab serif) | All `h1/h2/h3`, buttons, tier labels |
| Body face **Inter** | Everything else — this is a form filled in on a phone |

The dark ground is deliberate and is *not* the flyer's cream paper: this gets read on phones,
at night, in a ballroom. Contrast for the primary buttons stays dark-on-brass for the same
reason.

`config.EVENT_THEME` / `EVENT_THEME_NOTE` drive the theme badge on the hero and
the Register page's event strip. `config.EVENT_TAGLINE_LOCAL` carries an optional
local-language tagline. All three are optional — blank them and the hero degrades cleanly.

### The event flyer

`config.EVENT_FLYER` points at `assets/flyer.png`, which **does not exist yet**. Drop the flyer
artwork there and it appears on its own: full-width on Home, and behind a collapsed
"📜 See the party flyer" expander on Register (collapsed so a tall poster never sits between a
guest and the form they're trying to submit). Until then both call sites render nothing.

### The registration link is the front door

The bare app URL — the link the organiser sends out — **opens on the registration form**,
not on Home (`config.LANDING_PAGE`). The form starts at **step 1 of 3** ("Pay via Zelle"),
and submitting it **redirects to Home**, where the guest's confirmation sits at the top of
the page followed by the photos, sponsors, ticket count, and party stats.

Home is still reachable directly at `…/?page=Home`, from the sidebar, and from the 🏠 Home
button in every page header. Changing `LANDING_PAGE` in `config.py` is all it takes to point
the front door somewhere else.

### Group discounts

The per-ticket price drops as a booking gets bigger. **One registration, one price** — the
tier is decided by the ticket count on that single booking:

| Tickets on one booking | Price each | Total |
|---|---|---|
| 1–25 | $50.00 | e.g. 10 → $500.00 |
| 26–75 | $25.00 | e.g. 50 → $1,250.00 |
| 76–100 | $10.00 | e.g. 100 → $1,000.00 |

**The boundaries are inclusive of the lower bound**: a booking of exactly 26 pays $25,
and exactly 76 pays $10. Guests price their group off that flyer, so the app
has to agree with it at the boundary or somebody Zelles the wrong amount.

The Register page shows the whole table above the ticket selector (with the guest's current
row highlighted), the exact total under it, how much the discount saved, and a hint when the
next tier is within reach.

Tiers live in `config.GROUP_DISCOUNT_TIERS` as **`(minimum tickets, discount per ticket in
cents)`**, applied against `TICKET_PRICE_CENTS`. They're stored as money *off the base* so
that raising the base price moves every tier with it instead of silently turning a discount
into a surcharge. `config.price_tiers()` derives the displayed table from the same constant
the pricing functions use, so the form can't quote a price the app won't charge.

> **`MAX_TICKETS_PER_REGISTRATION` (100) must stay ≥ the largest tier minimum (76)**, or that
> tier is advertised but unbuyable — there's a test that fails if it slips. Because
> `utils.MAX_GUEST_NAMES` is derived from it, a 100-ticket booking must name its other 99
> guests; the name-count rule below applies at every size. `utils.GUEST_NAMES_MAX_CHARS` —
> which sizes both the form's name box and the `plus_one_name` column — is derived from that
> in turn, and `init_db()` widens the column on boot, so raising the cap can't silently
> truncate a big booking's guest list.

Admin → Overview → **Revenue (est.)** prices each booking at its own tier, so it matches what
should actually be in the Zelle history (see the reconciliation queries near the end of this
file).

### Photos & sponsors

The Home page has a **📸 Photos** gallery and a tiered **🤝 Our Sponsors** wall.

> ⚠️ **Both lists are currently empty** — the Home page shows "coming soon" placeholders.
> Add real team photos and sponsor logos before the registration link goes out.
> Everything to change is in `config.PHOTOS` and `config.SPONSORS`.

Sponsors are grouped into labelled tiers, best first, in the order set by
`config.SPONSOR_TIERS` (`Top Sponsor` → `Gold` → `Silver` → `Community`). The **top tier
renders larger**, with a bigger logo and a gold-washed card — that prominence is what a
headline sponsor is paying for. A sponsor whose tier isn't in that list still appears, sorted
to the end under its own heading, so a typo costs position rather than the whole card. Only
`name` is required; a sponsor with no logo yet gets their name set in type.

Filling either in is a data edit — see [`assets/README.md`](assets/README.md). In short: drop
files in `assets/photos/` or `assets/sponsors/`, list them in `config.py`, done. Remote images
must be `https://`; local ones are inlined as data URIs (Streamlit serves no static files), so
keep them under 3 MB. Anything that can't be resolved is skipped rather than rendered as a
broken image — `test_configured_sponsor_logos_and_photos_all_resolve` fails if a configured
path doesn't exist.

With both lists empty, each section shows a "coming soon" placeholder instead of a gap.

### Check-in window

Guests should not be able to check themselves in weeks ahead of the party, so check-in is
**closed by default** and opens automatically **2 hours before the event**. Update
`config.EVENT_DATE` and `config.EVENT_TIMEZONE` to the real event details. Until then the Scanner page shows when it opens instead of an input box.

Admin → Overview → **Check-in Window** overrides this:

| Mode | Behavior |
|------|----------|
| **Auto** (default) | Opens automatically 2 hours before the event |
| **Open now** | Forces it open — use for a rehearsal or an early start |
| **Closed** | Forces it shut |

The setting lives in the database, so it applies to everyone and survives restarts. The rule is
enforced in the service layer, not just hidden in the UI. Admin check-ins made from the Guests
spreadsheet always bypass the window, so an organiser can admit someone by hand at any time.

### Door flow: find first, then confirm

A search on the Scanner page **never checks anyone in**. It resolves a QR code,
phone number, email, or ticket ID to one guest and puts that guest on screen —
name, email, phone, ticket count, and how many wristbands they are owed (one per
ticket) — with their current check-in status. Only the explicit **Confirm & Check
In** press records anything.

That split exists because phone is the search staff actually reach for: guests
routinely can't remember which of their email addresses the QR code went to, but
they always know their own number. A phone number identifies a *booking*, though,
not a person — it can be mistyped, and a couple may register separately from one
number — so it is a way to locate someone, never proof of who they are. The
confirm step is keyed by guest id, not by the code that was searched, so
re-running the search can't admit a different booking than the one staff just
read back.

> The confirmation card shows a guest's email and phone to anyone using the
> Scanner page, which is unauthenticated. That is deliberate — staff need it to
> confirm identity — but if the page is ever reachable beyond the door, put it
> behind the admin password or mask those two fields.

### Admin Guests spreadsheet

The Guests tab is an editable grid: tick **Checked In**, **Band Given**, and/or **Delete**
across as many rows as you like, then press **Save changes** once. Deletions require an explicit
confirmation step. Identity columns are read-only so they can't be edited by accident.

---

## App URLs

| Page | Who uses it | URL |
|------|-------------|-----|
| **Register** ← *the link you send* | Guests | (bare app URL — see Streamlit Cloud dashboard) |
| **Home** | Everyone | …/?page=Home |
| **My QR** | Guests | …/?page=My%20QR |
| **Scanner** | Check-in staff | …/?page=Scanner |
| **Admin** | Organiser | …/?page=Admin |

The bare URL and `…/?page=Register` are the same page — share whichever reads better.

---

## Guest Flow

```
  Organiser shares the registration link
          |
  Guest opens it — the link lands ON the registration form (step 1)
          |
  Guest picks a ticket count; the form quotes their group price + total
          |
  Guest Zelles that total
          |
  Guest registers (name, email, phone, tickets, every guest's name,
                   Zelle reference, accepts T&Cs)
          |
  Redirected to Home: confirmation on top, then photos, sponsors, stats
          |
  QR code is emailed to the guest
          |
   ── Night of the party ──
          |
  Guest shows QR  →  staff scan at Scanner
     ...or can't find the email → staff search by phone number
          |
  Scanner shows WHO was found (name, email, phone, tickets, wristbands)
          |
  Staff confirm it's them → "Confirm & Check In"
          |
  Audio: "Welcome Sarah! 2 tickets."
          |
  Staff hand over the wristbands → "Mark N Wristbands Given"
```

---

## Required Streamlit Cloud Secrets

**Streamlit Cloud → App → ⋮ → Settings → Secrets:**

```toml
SECRET_KEY = "your-long-random-secret-key-here"
# Use the Supabase Pooler connection string, NOT the direct db.*.supabase.co host.
DATABASE_URL = "postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"

# Email (Gmail SMTP) — required for QR-code emails
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = "587"
MAIL_USERNAME = "your-sender@gmail.com"
MAIL_PASSWORD = "your-gmail-app-password"   # NOT your normal Gmail password
MAIL_DEFAULT_SENDER = "your-sender@gmail.com"

ADMIN_PASSWORD = "choose-a-strong-password"
MAX_TOTAL_TICKETS = "225"                    # hard ticket cap; "0" disables it
ZELLE_INFO = "dfwygana@gmail.com"
APP_URL = "https://party-checkin-generic.streamlit.app"
```

> ⚠️ **`ADMIN_PASSWORD` is mandatory.** The admin dashboard exposes guest PII and can delete
> records, so password verification **fails closed**: if the secret is missing, nobody can log
> in and the page says so explicitly. (It used to do the opposite — an unset password let
> *anyone* straight in.)

> **Never commit `.streamlit/secrets.toml`** — it is `.gitignore`d. The copy in a local
> checkout may hold production database and SMTP credentials.

Set **Python 3.12** under Streamlit Cloud → Advanced settings. `requirements.txt` is pinned
against that version.

---

## Local Development

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it
streamlit run streamlit_app.py
```

Open `http://localhost:8501`. With the example secrets it uses local SQLite — no Supabase needed.

> **Careful:** if your local `.streamlit/secrets.toml` contains the *production* `DATABASE_URL`
> and real SMTP credentials, running the app locally writes to the live guest list and sends
> real email. Point `DATABASE_URL` at `sqlite:///party_guests.db` and blank out `MAIL_USERNAME`
> before doing local UI work.

---

## Testing

**Unit tests** — service layer, validation, security, CSV/email escaping:

```bash
python -m unittest test_party_checkin -v
```

**End-to-end tests** — drive the real UI in a headless browser:

```bash
pip install pytest playwright && playwright install chromium
python -m pytest tests/e2e -v
```

The E2E suite launches its own Streamlit instance against a throwaway SQLite database with
SMTP disabled, so it never touches production data or sends mail.

Coverage includes: registration (valid, per-field validation errors, duplicate email),
check-in by QR / email / ID, double check-in, wristband tracking, admin auth (including
lockout after repeated failures), CSV export, QR generation and uniqueness, input
sanitization, CSV-injection and XSS escaping, and Postgres URL normalization.

---

## Input Validation Reference

| Field | Rules |
|-------|-------|
| **Full Name** | Letters and spaces only; 2–100 characters |
| **Email** | Standard email format; must be unique |
| **Phone** | Required; US numbers only (a `+` country code other than `+1` is rejected, as is an area code starting with 0 or 1). The field starts at `+1-` and formats itself to `+1-XXX-XXX-XXXX` as the guest types; `sanitize_phone()` re-normalizes server-side, so the mask is cosmetic and validation is identical without it |
| **Number of Tickets** | 1–50 per registration. Decides both the per-ticket price (see Group discounts) and how many guest names are required |
| **Additional Guest Names** | Required whenever more than one ticket is booked, and the count must match: **exactly `tickets - 1` names**, since the person registering holds the first ticket. One per line or comma-separated; letters and spaces only. A 1-ticket booking must leave it empty — everyone attending needs their own ticket |
| **Zelle Reference** | Required; 8–30 characters; letters, digits, hyphens |
| **Terms** | Must accept "I/We Agree" |

---

## Party Day Checklist

**1 hour before:**
- [ ] Open the app to wake it from free-tier sleep
- [ ] Log in to **Admin**; verify the guest list and Zelle references
- [ ] Open **Scanner** on the check-in tablet and test the camera

**At the door:**
- [ ] **Scanner** open on the check-in tablet, camera facing guests
- [ ] **Admin** open on the organiser's phone for a live view
- [ ] Volume up for audio announcements

**After:**
- [ ] Download the CSV from **Admin**

---

## Database Schema

Everything lives in one Supabase PostgreSQL database. Tables are created automatically on
first boot, and the migrations are additive and idempotent — no manual SQL is ever required.
To inspect it yourself: **supabase.com → your project → Table Editor** (browse) or **SQL
Editor** (query).

### `guests` — one row per registration

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | Primary key |
| `name` | varchar(100) | Letters and spaces only; validated on entry |
| `email` | varchar(120) | **Unique** — one registration per address |
| `phone` | varchar(30) | Required at registration; stored normalized as `+1-XXX-XXX-XXXX`, and a second lookup key alongside email. Rows created before it became mandatory keep `""` |
| `ticket_count` | integer | 1–50. Also decides the per-ticket price — see Group discounts |
| `plus_one_name` | varchar(1000) | Additional guest names, **newline-separated**. Registration requires exactly `ticket_count - 1` of them — one ticket per person, and the booker holds the first. Rows created before that rule may hold fewer |
| `zelle_ref` | varchar(100) | Payment reference, uppercased; cross-check against your bank |
| `qr_code` | varchar(200) | **Unique**; format `PARTY<year>-YYYYMMDD-<random>` |
| `checked_in` | boolean | Set at the door |
| `band_given` | boolean | Wristband handed out |
| `checkin_time` | timestamp | UTC. May be NULL even when `checked_in` is true |
| `created_at` | timestamp | UTC registration time |

Indexes: unique on `email` and `qr_code`; plain indexes on `checked_in` and `created_at`.

### `checkin_logs` — audit trail of door actions

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | Primary key |
| `guest_id` | integer | → `guests.id` |
| `action` | varchar(50) | `checkin` or `band_given` |
| `timestamp` | timestamp | UTC |
| `device_info` | varchar(200) | e.g. `Streamlit Scanner`, `Admin Dashboard` |

### `submission_logs` — every registration attempt, successful or not

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | Primary key |
| `name`, `email`, `phone`, `ticket_count`, `plus_one_name`, `zelle_ref` | — | What was submitted |
| `status` | varchar(50) | `registered`, `validation_error`, `duplicate_email`, `db_error`, `email_failed` |
| `errors` | varchar(500) | Why it failed |
| `guest_id` | integer | Set when the attempt succeeded |
| `created_at` | timestamp | UTC |

Use this to see how many people *tried* to register and where they got stuck.

### `page_visits` — anonymous traffic counter

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | Primary key |
| `visitor_token` | varchar(64) | Random per-session token — **not** tied to any identity |
| `page` | varchar(50) | Home / Register / My QR / Scanner / Admin |
| `visited_at` | timestamp | UTC |

### `app_settings` — organiser-wide switches

| Column | Type | Notes |
|--------|------|-------|
| `key` | varchar(50) | Primary key. Currently only `checkin_mode` |
| `value` | varchar(200) | For `checkin_mode`: `auto`, `open`, or `closed` |
| `updated_at` | timestamp | UTC |

### Handy queries for the Supabase SQL Editor

```sql
-- Who has not arrived yet?
SELECT name, email, ticket_count, zelle_ref
FROM guests WHERE NOT checked_in ORDER BY name;

-- Money owed vs collected (cross-check against your Zelle history).
-- Priced per booking, because group discounts depend on each booking's own
-- size -- SUM(ticket_count) * 30 would over-report every group.
SELECT COUNT(*) AS guests,
       SUM(ticket_count) AS tickets,
       SUM(ticket_count * CASE WHEN ticket_count >= 20 THEN 28
                               WHEN ticket_count >= 10 THEN 29
                               ELSE 30 END) AS expected_dollars
FROM guests;

-- What each booking should have paid, biggest first
SELECT name, email, ticket_count,
       CASE WHEN ticket_count >= 20 THEN 28
            WHEN ticket_count >= 10 THEN 29
            ELSE 30 END AS price_each,
       ticket_count * CASE WHEN ticket_count >= 20 THEN 28
                           WHEN ticket_count >= 10 THEN 29
                           ELSE 30 END AS total_owed,
       zelle_ref
FROM guests ORDER BY ticket_count DESC, name;

-- Everyone who listed extra guests, one name per line
SELECT name, ticket_count, plus_one_name FROM guests
WHERE COALESCE(plus_one_name, '') <> '';

-- Registrations that failed, and why
SELECT created_at, email, status, errors
FROM submission_logs WHERE status <> 'registered'
ORDER BY created_at DESC;

-- Is the door open right now?
SELECT * FROM app_settings WHERE key = 'checkin_mode';

-- Data-integrity spot checks (all should return 0)
SELECT COUNT(*) FROM (SELECT email FROM guests GROUP BY email HAVING COUNT(*) > 1) d;
SELECT COUNT(*) FROM guests WHERE qr_code IS NULL OR qr_code = '';
SELECT COUNT(*) FROM guests WHERE checked_in AND checkin_time IS NULL;
```

> All timestamps are stored in **UTC**, not Central time. The event is 5:30 PM CDT =
> 22:30 UTC, so an event-evening check-in shows as the *following* date in UTC after 7 PM local.

---

## Backing up & resetting after testing

When you're done testing and want a clean slate for the real event:

**Admin → scroll to the bottom → ⚠️ Danger Zone → 📦 Prepare backup → ⬇ Download full backup
(ZIP) → type `RESET` → Permanently delete all data.**

### Back up first

**Prepare backup** snapshots every table and offers it two ways:

- **⬇ Download full backup (ZIP)** — `guests.csv`, `checkin_logs.csv`, `page_visits.csv`,
  `submission_logs.csv`, `app_settings.csv`, plus a `README.txt` describing each file.
- **⬇ `<table>.csv`** — the same files individually, for when you're on a phone that can't
  open a ZIP.

Headers are the real database column names (raw `id`s, ISO-8601 UTC timestamps,
`true`/`false`), so a backup can be loaded straight back into the same schema — unlike the
Guests tab's ⬇ Download CSV, which is the prettified human export. Text fields starting with
`=`, `+`, `-`, or `@` are escaped, so opening a backup in Excel can't execute anything.

The prepared archive stays downloadable after the reset runs — once the tables are empty it's
the only copy left.

### Then reset

This empties `guests`, `checkin_logs`, `page_visits`, and `submission_logs`, and puts the
check-in mode back to `auto`. It does **not** drop any table, so the app keeps working
immediately afterwards.

> **This cannot be undone.** The button stays disabled until you type `RESET` exactly, in
> capitals, and the page warns you if you haven't prepared a backup in this session.

---

## Submission Tracking & Supabase Views

Every registration submit is written to `submission_logs` with a status of `validation_error`,
`duplicate_email`, `db_error`, or `registered`.

These reporting views are created automatically on Postgres at startup:

| View | Purpose |
|------|---------|
| `vw_registrations_summary` | Totals: guests, tickets, checked-in, bands, pending, admitted |
| `vw_registrations_by_day` | Registrations grouped by date |
| `vw_checkins_by_hour` | Event-day check-ins grouped by hour |
| `vw_site_activity_summary` | Total/today visits and unique visitors |
| `vw_submissions_summary` | Submission counts grouped by status |
| `vw_submissions_recent` | Last 100 submission attempts |

The same list — tables and views, with a one-line description each — is shown in the app under
**Admin → Danger Zone → Tables & views to query**, and in the `README.txt` inside every backup
ZIP, so you don't need this file open to know what to query.

---

## Troubleshooting

**App is slow to load**
Normal on the free tier — it was asleep. Open it a few minutes before guests arrive.

**"Running on a temporary local database" warning**
`DATABASE_URL` is missing or unreachable, and the app fell back to SQLite. Use the Supabase
**Pooler** string (`aws-0-*.pooler.supabase.com:6543`), not the direct `db.*.supabase.co` host.

**Nobody can log in to Admin**
`ADMIN_PASSWORD` is not set in secrets. Verification fails closed by design — set the secret
and reboot the app.

**Supabase project paused**
supabase.com → your project → Restore (~30 seconds). Happens after 7 days idle. A scheduled
GitHub Actions job (`.github/workflows/keep-supabase-alive.yml`) now pings the database twice a
week to prevent this — restoring is only needed if that job's `SUPABASE_DB_URL` secret is missing
or the DB password rotated. Check **Actions** tab on GitHub for job run history.

**Guest registered but got no QR email**
Confirm the registration in **Admin**, ask them to check spam, then use the **Resend QR Email**
button. Verify `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_DEFAULT_SENDER` are set and that
`MAIL_PASSWORD` is a Gmail *app password*.

**QR code not scanning**
Good lighting, steady camera, fill the frame. Fall back to manual entry — the Scanner accepts
the QR string, the guest's email, or their numeric ID.

**Camera not working on tablet/phone**
Some mobile browsers block camera access in embedded frames. Use Chrome on Android or grant
permission in iOS Settings → Safari → Camera.

**Charts fail to render locally**
`altair` (which `st.bar_chart` renders through) does not import on Python 3.14. Use Python 3.12.

---

## License

MIT — use it for your parties!
