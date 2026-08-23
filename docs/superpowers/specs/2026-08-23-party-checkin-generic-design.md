# Party Check-In Generic — Design Spec

## Goal

Create a reusable, generic party check-in app by cloning the existing `party-checkin-master` Streamlit project, stripping the Dallas Boys Party 2026 branding, and adapting the pricing model, payment destination, and sponsor features for a new generic event.

## Context

The source project (`/Users/yash/Downloads/party-checkin-master/`) is a working Streamlit + Supabase event-registration app with the following proven architecture:

| File | Responsibility |
|------|----------------|
| `config.py` | Event details, pricing, secrets access |
| `utils.py` | DB models, service layer, QR/email, validation |
| `theme.py` | CSS + HTML component builders |
| `streamlit_app.py` | Pages and navigation only |
| `test_party_checkin.py` / `test_config.py` | Unit tests |
| `tests/e2e/` | Playwright end-to-end tests |

It already uses Zelle (not PayPal) for payments, QR email, self check-in, admin dashboard, CSV export, photos/sponsors wall, and tiered group discounts.

## Requirements from Request

1. Clone everything from `party-checkin-master` into a new project `party-checkin-generic`.
2. New Supabase project: `party-checkin-generic` (credentials provided separately).
3. New Streamlit Community Cloud app on `https://share.streamlit.io/` under `yvh1225@gmail.com`.
4. Payment via **Zelle** to `dfwygana@gmail.com` (not PayPal).
5. Pricing tiers:
   - 1–25 seats: $50 each
   - 26–75 seats: $25 each
   - 76+ seats: $10 each
6. Sponsor logo space needed on the Home page.

## Assumptions (Documented Because Requirements Are Ambiguous)

- **Pricing interpretation:** The existing app prices per ticket within a single registration. The new tiers are interpreted as per-ticket prices:
  - 1–25 tickets → $50/ticket
  - 26–75 tickets → $25/ticket
  - 76+ tickets → $10/ticket
- **Max tickets per registration:** Must be raised from 50 to at least 100 so the 76+ tier is reachable. This design sets `MAX_TICKETS_PER_REGISTRATION = 100`.
- **Generic branding:** Event name, date, venue, theme, and flyer are replaced with placeholder/generic values so the app works out of the box but clearly needs event-specific details before going live.
- **Payment method:** The source app already uses Zelle, so the change is updating the Zelle destination email and removing any leftover PayPal/Stripe references.
- **Deployment scope:** The code can be prepared locally. Creating the Supabase tables and deploying to Streamlit Cloud require credentials and browser/API access that cannot be safely automated from this session; explicit setup instructions will be provided.

## Approaches Considered

### Option A: Hard fork with in-place edits (recommended)

Copy the entire source repo into the new directory, then edit `config.py`, `README.md`, `.streamlit/secrets.toml.example`, and tests in place. Keep the file layout identical so future upstream bug fixes can be cherry-picked.

- **Pros:** Fastest, lowest risk, preserves proven architecture, tests still run.
- **Cons:** Carries over Dallas-specific comments and history unless scrubbed.

### Option B: Refactor into a template engine

Extract all event-specific strings into a separate `event.yaml` or `.env` file and make `config.py` read from it.

- **Pros:** Easier to reuse for future events without code edits.
- **Cons:** Larger change, breaks existing tests, introduces new failure modes, over-engineered for a single clone.

### Option C: Minimal strip-and-replace

Copy only `streamlit_app.py`, `utils.py`, `theme.py`, `config.py`, and `requirements.txt`; drop tests, README, and archive.

- **Pros:** Very small footprint.
- **Cons:** Loses tests, deployment guidance, and safety rails; not maintainable.

**Recommendation:** Option A. It satisfies the request with minimal risk and keeps the working test suite.

## Architecture

Same as the source project:

```
Guests / Staff / Admin
        |
   Streamlit Cloud (free tier)
        |
   Supabase PostgreSQL (free tier)
```

Changes are confined to:
- `config.py` — event details, pricing tiers, Zelle info, default URLs.
- `README.md` — generic instructions and new pricing table.
- `.streamlit/secrets.toml.example` — updated defaults and comments.
- `test_config.py` / `test_party_checkin.py` — update price-tier assertions and max-ticket expectations.
- `AGENTS.md` — update references to the old event and credentials.

## Data Model

No schema changes required. The existing tables (`guests`, `checkin_logs`, `submission_logs`, `page_visits`, `app_settings`) plus auto-created Postgres views are sufficient. On first run, `utils.init_db()` creates tables and widens `plus_one_name` to `VARCHAR(2000)` to accommodate the raised 100-ticket cap.

## Detailed Changes

### 1. Event identity (`config.py`)

- `EVENT_NAME` → `"Generic Party"`
- `EVENT_TAGLINE` → `"Your Event Tagline"`
- `EVENT_DATE` → placeholder far-future date (e.g., 2027-01-01)
- `EVENT_TIME_TEXT` → `"TBD"`
- `EVENT_DATE_TEXT` / `EVENT_DATE_SHORT` → derived from `EVENT_DATE`
- `EVENT_THEME` → `"Your Theme"`
- `EVENT_THEME_NOTE` → `"Dress code TBD"`
- `EVENT_TAGLINE_LOCAL` → `""`
- `VENUE_NAME` → `"Your Venue"`
- `VENUE_ADDRESS` → `"Venue address TBD"`
- `APP_VERSION` → `"1.0-generic"`
- `_DEFAULT_APP_URL` → `"https://party-checkin-generic.streamlit.app"`
- `EVENT_FLYER` → `"assets/flyer.jpg"` (kept; file still expected to be added later)
- `PHOTOS` and `SPONSORS` → empty lists, so Home shows "coming soon" placeholders until populated.

### 2. Pricing (`config.py`)

- `TICKET_PRICE_CENTS = 5000` ($50.00)
- `GROUP_DISCOUNT_TIERS = ((26, 2500), (76, 4000))`
  - 26+ tickets: $2,500 off per ticket → $25/ticket
  - 76+ tickets: $4,000 off per ticket → $10/ticket
- `MAX_TICKETS_PER_REGISTRATION = 100`

Resulting tiers:

| Tickets | Price Each | Example Total |
|---------|------------|---------------|
| 1–25    | $50.00     | 10 → $500.00  |
| 26–75   | $25.00     | 50 → $1,250.00 |
| 76–100  | $10.00     | 100 → $1,000.00 |

### 3. Payment destination (`config.py`)

- `_DEFAULT_ZELLE = "dfwygana@gmail.com"`
- `_PLACEHOLDER_ZELLE` remains as a guard string.

### 4. Secrets template (`.streamlit/secrets.toml.example`)

- Update `APP_URL` placeholder to `https://party-checkin-generic.streamlit.app`
- Update `ZELLE_INFO` default to `dfwygana@gmail.com`
- Remove `TICKET_PRICE_CENTS` from example (price is now a code constant)
- Remove Stripe keys from example (not used)
- Keep admin password, mail, and `MAX_TOTAL_TICKETS` examples.

### 5. Documentation (`README.md`)

- Replace Dallas Boys Party 2026 details with generic placeholders.
- Update pricing table.
- Update Zelle email.
- Update repo/URL references.
- Keep architecture, local development, testing, and troubleshooting sections.

### 6. Tests

- Update `test_top_discount_tier_is_actually_bookable` for 100-ticket max.
- Update price-tier assertions in `test_config.py` to match 1–25/26–75/76+ tiers.
- Update expected per-ticket prices and totals in `test_party_checkin.py`.
- Ensure `test_configured_sponsor_logos_and_photos_all_resolve` passes with empty `PHOTOS`/`SPONSORS`.

### 7. Sponsor logo space

The Home page already renders a tiered sponsor wall driven by `config.SPONSORS` and `config.SPONSOR_TIERS`. To satisfy "Sponsors logo space needed," we will:
- Keep `SPONSOR_TIERS` unchanged (`Top Sponsor`, `Gold`, `Silver`, `Community`).
- Ship `SPONSORS` empty so the section renders a clean "coming soon" placeholder.
- Document in `README.md` and `assets/README.md` how to drop logos and list sponsors.

## Deployment Notes

The following steps cannot be safely automated in this session and require explicit user action:

1. **Supabase:**
   - Create or open the `party-checkin-generic` project in Supabase.
   - Copy the **Pooler** connection string (`postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`).
   - The app creates tables automatically on first run; no manual SQL is required.
   - Do not commit the connection string to git.

2. **Streamlit Cloud:**
   - Log in to `share.streamlit.io` with `yvh1225@gmail.com`.
   - Create a new app from the `party-checkin-generic` repo, entry point `streamlit_app.py`.
   - Under Advanced settings, set Python version to 3.12.
   - Under Secrets, paste the contents of `.streamlit/secrets.toml` with real values.

3. **Email:**
   - Provide a Gmail address and app password (or another SMTP server) for QR-code emails.
   - Leave `MAIL_USERNAME` blank to disable email during testing.

## Security & Credential Handling

- The source project's `.streamlit/secrets.toml` contains production credentials. It must **not** be copied into the new project.
- Only `.streamlit/secrets.toml.example` (with placeholder values) will be created in the new repo.
- The new project's `.gitignore` must exclude `.streamlit/secrets.toml`.
- Supabase and Streamlit credentials provided by the user will not be written to disk.

## Testing Plan

1. Run unit tests locally against SQLite:
   ```bash
   python -m unittest test_party_checkin -v
   python -m unittest test_config -v
   ```
2. Run E2E suite in a sandbox directory:
   ```bash
   python -m pytest tests/e2e -v
   ```
3. Manual smoke checks:
   - Registration page shows correct pricing tiers.
   - Zelle info shows `dfwygana@gmail.com`.
   - Home page shows sponsor "coming soon" placeholder.
   - Admin login works with configured password.

## Open Questions / Decisions Made

- Pricing tier overlap at exactly 25 tickets: the lower bound of the next tier is treated as **26**, matching the existing app's inclusive-boundary convention.
- `MAX_TOTAL_TICKETS` default: kept at 225 unless overridden by secret.
- Event theme/visuals: kept as generic placeholders; user must update `config.py` and `assets/` before launch.

## Acceptance Criteria

- [ ] All source files copied to `party-checkin-generic`.
- [ ] `config.py` reflects generic event, new pricing, and new Zelle email.
- [ ] `.streamlit/secrets.toml.example` updated and no real secrets committed.
- [ ] Unit tests pass.
- [ ] README.md updated for generic use.
- [ ] Sponsor wall renders correctly (empty state).
- [ ] Written deployment instructions provided for Supabase + Streamlit Cloud.
