# Party Check-In Generic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clone `party-checkin-master` into `party-checkin-generic`, adapt event details, pricing tiers, and Zelle payment destination, and verify the app runs with the new settings.

**Architecture:** Hard fork of the proven Streamlit + Supabase app. All event-specific changes live in `config.py` and `README.md`; `utils.py`, `theme.py`, and `streamlit_app.py` remain unchanged. The database schema is created automatically on first run.

**Tech Stack:** Python 3.12, Streamlit 1.40.0, SQLAlchemy 2.0, Supabase PostgreSQL, Zelle (manual payment).

---

## File Structure

| File | Responsibility in this plan |
|------|----------------------------|
| `config.py` | Event name/date/venue, pricing tiers, Zelle default, app URL |
| `README.md` | Generic setup/pricing/deployment docs |
| `.streamlit/secrets.toml.example` | Safe template for Streamlit secrets |
| `test_config.py` | Unit tests for config helpers and pricing tiers |
| `test_party_checkin.py` | Service-layer tests that reference ticket prices |
| `assets/README.md` | Sponsor/logo onboarding (update references only) |
| `AGENTS.md` | Agent notes (update references only) |
| `streamlit_app.py` | No changes |
| `utils.py` | No changes |
| `theme.py` | No changes |

---

### Task 1: Copy Source Project Into New Directory

**Files:**
- Create: all files in current working directory (project root)
- Exclude: `.git/`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.streamlit/secrets.toml`, `.DS_Store`, `archive/`

- [ ] **Step 1: Copy source files with exclusions**

```bash
SOURCE="/Users/yash/Downloads/party-checkin-master"
DEST="/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic"

rsync -av --exclude='.git' --exclude='venv' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='.streamlit/secrets.toml' \
  --exclude='.DS_Store' --exclude='archive' \
  "$SOURCE/" "$DEST/"
```

Expected: all source files copied except excluded directories/files.

- [ ] **Step 2: Remove any stale secrets from copied files**

```bash
grep -R "dallashudugaru@gmail.com\|postgres.zqpdpbyxohqthoikzotv\|mbik odvh oiax fuaa\|dbp-nY5Dapfh5otlx2T9MPFA" "$DEST" --include="*.py" --include="*.toml" --include="*.md" || echo "No leaked secrets found"
```

Expected: the grep returns no matches (or only the safe example file after it is rewritten in Task 2).

- [ ] **Step 3: Initialize new git repo**

```bash
cd "$DEST"
git init -b main
git add .
git commit -m "feat: initial clone from party-checkin-master"
```

Expected: new repo created with one commit.

---

### Task 2: Create Safe Secrets Template

**Files:**
- Create: `.streamlit/secrets.toml.example`
- Delete: existing `.streamlit/secrets.toml` (if copied)

- [ ] **Step 1: Delete copied production secrets file**

```bash
rm -f "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic/.streamlit/secrets.toml"
```

Expected: secrets.toml no longer exists.

- [ ] **Step 2: Write safe example secrets file**

```toml
# Party Check-In Generic — Streamlit Secrets (local example)
# DO NOT commit the real .streamlit/secrets.toml to version control!
# On Streamlit Community Cloud, set these via Dashboard → Settings → Secrets.

SECRET_KEY = "your-long-random-secret-key-here"

# Local development: SQLite. Production: the Supabase POOLER connection string.
DATABASE_URL = "sqlite:///party_guests.db"

# Public URL of the deployed app — used for the "view your QR" link in emails.
APP_URL = "https://party-checkin-generic.streamlit.app"

# Email (Gmail SMTP example).
# Leave MAIL_USERNAME/MAIL_PASSWORD blank to disable outgoing email entirely.
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = "587"
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
MAIL_DEFAULT_SENDER = "your-email@gmail.com"

# Admin password for the dashboard. REQUIRED.
ADMIN_PASSWORD = "change-me"

# Hard cap on tickets sold across all guests. "0" = no cap.
MAX_TOTAL_TICKETS = "225"

# Zelle payment info shown to guests on the registration page.
ZELLE_INFO = "dfwygana@gmail.com"
```

Expected: `.streamlit/secrets.toml.example` exists with the content above.

- [ ] **Step 3: Verify .gitignore excludes secrets.toml**

```bash
grep "secrets.toml" "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic/.gitignore"
```

Expected: output contains `.streamlit/secrets.toml`.

- [ ] **Step 4: Commit**

```bash
cd "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic"
git add .gitignore .streamlit/secrets.toml.example
git commit -m "chore: replace secrets with safe example template"
```

---

### Task 3: Adapt config.py for Generic Event

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Replace event details block (lines 49–70)**

Old:
```python
EVENT_NAME = "Dallas Boys Party"
EVENT_TAGLINE = "12th Year of Togetherness"
EVENT_DATE = datetime(2026, 10, 9)
EVENT_TIME_TEXT = "5:30 PM onwards"
EVENT_DATE_TEXT = "Friday, October 9, 2026"
EVENT_DATE_SHORT = "Fri, Oct 9, 2026"

EVENT_THEME = "Texas Cowboys"
EVENT_THEME_NOTE = "Boots, hats, and denim encouraged"

EVENT_TAGLINE_LOCAL = "ನಮ್ಮ ಹುಡುಗರು, ನಮ್ಮ ಪಾರ್ಟಿ"

VENUE_NAME = "Elegance Ballroom & Event Center"
VENUE_ADDRESS = "8740 Ohio Dr A1, Plano, TX 75024"

APP_VERSION = "3.0"

_DEFAULT_APP_URL = "https://party-checkin-hqedxmr3wfmtsdfxr9zjlq.streamlit.app"
```

New:
```python
EVENT_NAME = "Generic Party"
EVENT_TAGLINE = "Your Event Tagline"
EVENT_DATE = datetime(2027, 1, 1)
EVENT_TIME_TEXT = "TBD"
EVENT_DATE_TEXT = "Friday, January 1, 2027"
EVENT_DATE_SHORT = "Fri, Jan 1, 2027"

EVENT_THEME = "Your Theme"
EVENT_THEME_NOTE = "Dress code TBD"

EVENT_TAGLINE_LOCAL = ""

VENUE_NAME = "Your Venue"
VENUE_ADDRESS = "Venue address TBD"

APP_VERSION = "1.0-generic"

_DEFAULT_APP_URL = "https://party-checkin-generic.streamlit.app"
```

- [ ] **Step 2: Empty photos and sponsors (lines 104–155)**

Old:
```python
PHOTOS = [
    {"src": "assets/photos/2025-the-whole-crew.jpg",
     "caption": "The whole crew, one frame — 12 years in"},
    # ...
]

SPONSORS = [
    {"name": "Placeholder Top Sponsor", ...},
    # ...
]
```

New:
```python
PHOTOS = []

SPONSORS = []
```

- [ ] **Step 3: Update base ticket price and discount tiers (lines 170–215)**

Old:
```python
TICKET_PRICE_CENTS = 3000

GROUP_DISCOUNT_TIERS = (
    (10, 100),
    (20, 200),
)
```

New:
```python
TICKET_PRICE_CENTS = 5000

GROUP_DISCOUNT_TIERS = (
    (26, 2500),   # 26+ tickets: $25.00 off each → $25/ticket
    (76, 4000),   # 76+ tickets: $40.00 off each → $10/ticket
)
```

- [ ] **Step 4: Raise max tickets per registration (line 361)**

Old:
```python
MAX_TICKETS_PER_REGISTRATION = 50
```

New:
```python
MAX_TICKETS_PER_REGISTRATION = 100
```

- [ ] **Step 5: Update default Zelle info (line 364)**

Old:
```python
_DEFAULT_ZELLE = "dallashudugaru@gmail.com"
```

New:
```python
_DEFAULT_ZELLE = "dfwygana@gmail.com"
```

- [ ] **Step 6: Update check-in timezone/location (line 418)**

Old:
```python
EVENT_TIMEZONE = "America/Chicago"
```

New:
```python
EVENT_TIMEZONE = "America/Chicago"  # TODO: update to venue timezone
```

- [ ] **Step 7: Commit**

```bash
git add config.py
git commit -m "feat: generic event config, new pricing tiers, new Zelle email"
```

---

### Task 4: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace title and event block (top of file)**

Old header:
```markdown
# Party Check-In System

Event registration and check-in for **Dallas Boys Party 2026**, built with **Streamlit** and hosted free on Streamlit Community Cloud. Zelle payments, emailed QR codes, self check-in with audio announcements, and an admin dashboard. Sized for 200+ guests.

- **Event:** Friday, October 9, 2026 · 5:30 PM onwards
- **Venue:** Elegance Ballroom & Event Center, 8740 Ohio Dr A1, Plano, TX 75024
- **Theme:** 12th Year of Togetherness · dress theme **Texas Cowboys**
```

New header:
```markdown
# Party Check-In Generic

Generic event registration and check-in, built with **Streamlit** and hosted free on Streamlit Community Cloud. Zelle payments, emailed QR codes, self check-in with audio announcements, and an admin dashboard.

- **Event:** Your event name · date TBD
- **Venue:** Your venue · address TBD
- **Theme:** Your theme · dress code TBD
- **Payment:** Zelle → `dfwygana@gmail.com`
```

- [ ] **Step 2: Update payment line**

Old:
```markdown
- **Payment:** Zelle → `dallashudugaru@gmail.com` · $30 per ticket, $29 for 10+, $28 for 20+ · 225 tickets total
```

New:
```markdown
- **Payment:** Zelle → `dfwygana@gmail.com` · $50 per ticket (1–25), $25 per ticket (26–75), $10 per ticket (76+) · up to 100 tickets per registration
```

- [ ] **Step 3: Update group discount table**

Old table:
```markdown
| Tickets on one booking | Price each | Total |
|---|---|---|
| 1–9 | $30.00 | e.g. 9 → $270.00 |
| 10–19 | $29.00 | e.g. 10 → $290.00 |
| 20–50 | $28.00 | e.g. 20 → $560.00 |
```

New table:
```markdown
| Tickets on one booking | Price each | Total |
|---|---|---|
| 1–25 | $50.00 | e.g. 10 → $500.00 |
| 26–75 | $25.00 | e.g. 50 → $1,250.00 |
| 76–100 | $10.00 | e.g. 100 → $1,000.00 |
```

- [ ] **Step 4: Update required secrets example**

Old:
```toml
ZELLE_INFO = "dallashudugaru@gmail.com"
```

New:
```toml
ZELLE_INFO = "dfwygana@gmail.com"
```

- [ ] **Step 5: Update repo references**

Replace `aladin-genie/party-checkin` with `your-org/party-checkin-generic` (or remove if repo not yet created).

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: generic README and new pricing table"
```

---

### Task 5: Update Agent Notes and Assets README

**Files:**
- Modify: `AGENTS.md`
- Modify: `assets/README.md`

- [ ] **Step 1: Update AGENTS.md event references**

Replace:
- `Dallas Boys Party 2026` → `Generic Party`
- `dallashudugaru@gmail.com` → `dfwygana@gmail.com`
- `Texas Cowboys` → `Your Theme`

Keep all architecture, security, and testing notes intact.

- [ ] **Step 2: Update assets/README.md sponsor instructions**

Ensure it still describes dropping sponsor logos into `assets/sponsors/` and listing them in `config.py`. No functional code changes.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md assets/README.md
git commit -m "docs: update agent notes and asset instructions for generic event"
```

---

### Task 6: Update Tests for New Pricing

**Files:**
- Modify: `test_config.py`
- Modify: `test_party_checkin.py`

- [ ] **Step 1: Update price-tier tests in test_config.py**

Find assertions tied to `3000`, `2900`, `2800`, `50`, `20`, `10`, and replace with values for the new tiers:

```python
# Example expected assertions (verify exact test names after reading file)
assert config.ticket_price_cents_for(1) == 5000
assert config.ticket_price_cents_for(25) == 5000
assert config.ticket_price_cents_for(26) == 2500
assert config.ticket_price_cents_for(75) == 2500
assert config.ticket_price_cents_for(76) == 1000
assert config.ticket_price_cents_for(100) == 1000

assert config.booking_total_cents(10) == 50000
assert config.booking_total_cents(50) == 125000
assert config.booking_total_cents(100) == 100000
```

- [ ] **Step 2: Update max-ticket test**

Ensure any assertion that `MAX_TICKETS_PER_REGISTRATION >= largest tier minimum` now uses 100 and 76.

- [ ] **Step 3: Update service-layer tests in test_party_checkin.py**

Search for hardcoded prices like `3000`, `2900`, `2800`, `30`, `29`, `28`, and update to new equivalents where they reflect expected totals. Tests that only test shape (e.g., revenue > 0) may not need changes.

- [ ] **Step 4: Run unit tests and fix failures**

```bash
cd "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic"
python -m unittest test_config -v
python -m unittest test_party_checkin -v
```

Expected: all tests pass. If failures remain, adjust test expectations and re-run.

- [ ] **Step 5: Commit**

```bash
git add test_config.py test_party_checkin.py
git commit -m "test: update price-tier and capacity assertions for generic pricing"
```

---

### Task 7: Run E2E Smoke Test

**Files:**
- None (verification only)

- [ ] **Step 1: Create sandbox secrets for E2E**

```bash
SANDBOX="/tmp/pc-generic-sandbox"
mkdir -p "$SANDBOX/.streamlit"
cat > "$SANDBOX/.streamlit/secrets.toml" <<'EOF'
DATABASE_URL = "sqlite:///local_e2e.db"
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
ADMIN_PASSWORD = "testadmin123"
ZELLE_INFO = "dfwygana@gmail.com"
SECRET_KEY = "test-secret"
APP_URL = "http://localhost:8599"
EOF
```

- [ ] **Step 2: Run E2E tests**

```bash
cd "$SANDBOX"
python -m pytest "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic/tests/e2e" -v
```

Expected: tests pass or any failures are documented as pre-existing / unrelated to the generic clone.

- [ ] **Step 3: Clean up sandbox**

```bash
rm -rf "$SANDBOX"
```

---

### Task 8: Manual UI Smoke Test

**Files:**
- None (verification only)

- [ ] **Step 1: Start app locally with SQLite**

```bash
SANDBOX="/tmp/pc-generic-ui"
mkdir -p "$SANDBOX/.streamlit"
cat > "$SANDBOX/.streamlit/secrets.toml" <<'EOF'
DATABASE_URL = "sqlite:///ui_test.db"
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
ADMIN_PASSWORD = "testadmin123"
ZELLE_INFO = "dfwygana@gmail.com"
SECRET_KEY = "ui-test-secret"
APP_URL = "http://localhost:8501"
EOF

cd "$SANDBOX"
python -m streamlit run "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic/streamlit_app.py" --server.port 8502 &
APP_PID=$!
sleep 8
```

- [ ] **Step 2: Verify landing page loads**

Open `http://localhost:8502` in a browser or use `curl`:

```bash
curl -s http://localhost:8502 | head -20
```

Expected: page returns HTML, contains "Generic Party" or registration form.

- [ ] **Step 3: Stop app**

```bash
kill $APP_PID
rm -rf "$SANDBOX"
```

---

### Task 9: Write Deployment Instructions

**Files:**
- Create: `DEPLOY.md`

- [ ] **Step 1: Create deployment guide**

```markdown
# Deploying Party Check-In Generic

## 1. Supabase

1. Open https://supabase.com and sign in.
2. Create/open project `party-checkin-generic`.
3. Go to Project Settings → Database → Connection string → URI.
4. Copy the **Pooler** connection string (`postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`).
5. Paste it into Streamlit secrets (next section). Tables are created automatically when the app first runs.

## 2. Streamlit Cloud

1. Go to https://share.streamlit.io/ and sign in with `yvh1225@gmail.com`.
2. Click **New app** → select this repo (`party-checkin-generic`) → set main file to `streamlit_app.py`.
3. Advanced settings → Python version **3.12**.
4. Secrets → paste the contents of `.streamlit/secrets.toml.example` with real values:
   - `DATABASE_URL` = Supabase Pooler string
   - `ADMIN_PASSWORD` = strong password
   - `ZELLE_INFO` = `dfwygana@gmail.com`
   - `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_DEFAULT_SENDER` = Gmail SMTP credentials (or blank to disable email)
   - `APP_URL` = the deployed Streamlit URL
5. Deploy.

## 3. Post-Deploy Checklist

- [ ] Open the app, confirm no "temporary local database" warning.
- [ ] Confirm registration page shows pricing: $50 (1–25), $25 (26–75), $10 (76+).
- [ ] Confirm Zelle info shows `dfwygana@gmail.com`.
- [ ] Log in to Admin with the configured password.
- [ ] Register a test guest and verify the QR code appears.
- [ ] Download CSV backup, then reset test data before the real event.

## 4. Before the Real Event

- Update `config.py` with real event name, date, venue, theme, photos, and sponsors.
- Add real flyer to `assets/flyer.jpg`.
- Add real photos to `assets/photos/` and list them in `config.PHOTOS`.
- Add real sponsor logos to `assets/sponsors/` and list them in `config.SPONSORS`.
- Re-deploy.
```

- [ ] **Step 2: Commit**

```bash
cd "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic"
git add DEPLOY.md
git commit -m "docs: add deployment instructions for Supabase and Streamlit Cloud"
```

---

### Task 10: Final Verification and Summary

**Files:**
- None (verification only)

- [ ] **Step 1: Run full unit test suite**

```bash
cd "/Users/yash/Downloads/:Users:yash:Downloads:party-checkin-generic"
python -m unittest test_config test_party_checkin -v
```

Expected output ends with `OK`.

- [ ] **Step 2: Confirm no secrets in repo**

```bash
grep -R "dfwygana@gmail.com" . --include="*.py" --include="*.toml" --include="*.md" | grep -v "secrets.toml.example" | grep -v "DEPLOY.md" | grep -v "README.md" || echo "Clean"
```

Expected: only example/docs files mention the email.

- [ ] **Step 3: Final commit / status**

```bash
git status
git log --oneline -5
```

Expected: working tree clean; log shows clone + config + docs + tests commits.

---

## Self-Review Checklist

- [ ] Spec coverage: clone, config, secrets template, README, tests, deployment docs all have tasks.
- [ ] Placeholder scan: no TBD/TODO in final code (the single `# TODO: update to venue timezone` comment is acceptable and visible).
- [ ] Type consistency: `MAX_TICKETS_PER_REGISTRATION` (100) matches largest tier minimum (76).
- [ ] Credential safety: production `secrets.toml` excluded; only example file contains placeholders.
