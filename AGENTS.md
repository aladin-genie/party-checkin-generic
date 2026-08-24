# DFW Yakshagana Havyasis — Party Check-In Agent Notes

## ⚠️ Read this first

`.streamlit/secrets.toml` in a local checkout may contain the **production** Supabase
`DATABASE_URL` and **real Gmail SMTP credentials**. Streamlit loads secrets from
`./.streamlit/secrets.toml` relative to the **current working directory**, so running
`streamlit run streamlit_app.py` from the project root connects to the live guest list and
sends real email.

**To exercise the UI safely, run the app from a different working directory** that has its own
`.streamlit/secrets.toml` pointing at `sqlite:///local.db` with `MAIL_USERNAME` blank:

```bash
mkdir -p /tmp/pc-sandbox/.streamlit
cat > /tmp/pc-sandbox/.streamlit/secrets.toml <<'EOF'
DATABASE_URL = "sqlite:///local_e2e.db"
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
ADMIN_PASSWORD = "testadmin123"
ZELLE_INFO = "test-zelle@example.com"
EOF
cd /tmp/pc-sandbox && python -m streamlit run /path/to/party-checkin/streamlit_app.py --server.port 8599
```

The `tests/e2e` suite does exactly this automatically.

## Live App
- **Streamlit Cloud:** see Streamlit Cloud dashboard (URL kept out of this public repo — it was getting hit by
  crawler/bot traffic every few minutes after being indexed from here, inflating the visitor stats)
- **GitHub repo:** your-org/party-checkin-generic (branch `main`, entry `streamlit_app.py`)
- **Streamlit Cloud account:** yvh1225@gmail.com
- **Supabase project:** see Streamlit Cloud secrets (`DATABASE_URL`)
- **Python version:** 3.12 (set in Streamlit Cloud → Advanced settings)

## Required Streamlit Cloud Secrets
`DATABASE_URL` (Supabase **Pooler** URL), `ADMIN_PASSWORD`, `MAX_TOTAL_TICKETS`, `ZELLE_INFO`,
`SECRET_KEY`, `APP_URL`, and the mail block (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`,
`MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`).

`ADMIN_PASSWORD` is **mandatory** — `verify_admin_password` fails closed, so an unset secret
locks everyone out of the admin dashboard rather than letting everyone in.

## Code Layout
| File | Rule |
|------|------|
| `config.py` | The only place that reads config secrets and the only place event date/venue/name strings, pricing/discount tiers, and Home-page photo/sponsor content live. Never hardcode them elsewhere. |
| `utils.py` | Models + service layer + validation + email. **No Streamlit UI code.** |
| `theme.py` | All CSS and HTML component builders. Builders return HTML strings and `html.escape()` their inputs. |
| `streamlit_app.py` | Pages and navigation only. Must not open DB sessions or touch the ORM — call a service function in `utils.py` instead. |

## Local Development
- Tests: `python -m unittest test_party_checkin -v`
- E2E: `python -m pytest tests/e2e -v` (needs `pytest`, `playwright`, `playwright install chromium`)
- Do **not** commit `.streamlit/secrets.toml`.

## Behavior worth knowing before you change things
- **Register is the landing page, not Home.** The bare app URL resolves to
  `config.LANDING_PAGE` ("Register") — that URL is the link the organiser sends out. A
  successful submit calls `_finish_registration()`, which flips `st.session_state["page"]` to
  Home and sets `just_registered`; Home then leads with
  `_render_registration_confirmation()`. There is no success screen on the Register page any
  more. E2E tests must pass an explicit page to `goto()` if they want Home.
- **Every SEAT has its own price — this is NOT a per-ticket group discount.**
  `config.SEAT_TIERS` prices seat 1–25 at $50, 26–75 at $25, 76–100 at $10, boundaries
  INCLUSIVE. A booking of N seats pays the SUM of seats 1..N, so 26 seats costs
  $1,250 + $25 = **$1,275**, NOT 26 × $25. Never use `config.ticket_price_dollars()` to quote
  or total anything — that's only the base (seat-1) price. Use `seat_price_cents()` /
  `ticket_price_cents_for()` (marginal price of the next seat) / `booking_total_cents()` /
  `booking_savings_cents()`.
  **Copy rule:** never write "N tickets — $X each" anywhere. A guest reads that as N × $X and
  underpays; that exact wording shipped once in `theme.price_tier_table()` and quoted $650 for
  a booking the app charged $1,275 for, on the same screen as the Zelle handle. Say
  "Seats 26–75 · $X per seat" and always show the real total alongside.
  `config.MAX_TICKETS_PER_REGISTRATION` (100) must stay ≥ the largest tier minimum (76) or that
  tier can't be bought; `test_top_discount_tier_is_actually_bookable` enforces it. Money is
  computed in **integer cents** — `get_stats()["revenue"]` sums per-booking via
  `_expected_revenue_cents()` rather than `tickets × base_price`, which would over-report
  every group.
- **`config.PHOTOS` / `config.SPONSORS` are hand-edited content**, so `utils` treats them as
  untrusted: `resolve_image_src()` is an allowlist (https / `data:image/` / local file only,
  any other scheme dropped), local files are inlined as data URIs relative to the *project
  dir* not the cwd, and unresolvable entries are skipped rather than rendered. Keep it that
  way — these values go straight into `src`/`href` attributes. Sponsor **ordering** is a
  config question (`config.SPONSOR_TIERS`) resolved in `utils.sponsor_list()`;
  `theme.sponsor_wall()` just walks that order and starts a new heading when the tier
  changes, so grouping can't disagree with the sort.
- **The app ships with a dark, event-neutral theme.** Palette tokens live in `theme.py` `:root`
  (`--leather`, `--tan`, `--gold`, `--rust`, `--turquoise`); the two accent tokens were renamed
  from `--violet`/`--cyan`, and `theme._STAT_ACCENTS` must stay in step with them or
  `stat_tiles()` silently drops the accent and the tile renders grey
  (`test_stat_accents_match_the_themed_tokens` catches it). Tunga is display-only (hero +
  brand bar), Bitter carries headings, Inter carries body — don't put Tunga on body copy, it
  has no bold weight and is barely legible at small sizes. The ground stays DARK so it reads
  well on phones in a dim hall.
- **`config.EVENT_FLYER` is set and the artwork exists** (`assets/prasanga-flyer.webp`). It
  renders on Home via `theme.flyer_card()` AND behind a collapsed expander on Register.
  `utils.event_flyer_src()` still returns "" for a missing/blank path and both call sites then
  render nothing, so blanking it is a safe way to drop the flyer.
- **Local images are base64-inlined into the page HTML**, which Streamlit re-sends on every
  rerun, so asset weight is page weight. Keep them WebP and no larger than they render:
  the flyer is capped at `max-height: 70vh`, so ~1300px tall is the useful maximum. The flyer
  was once listed in BOTH `config.EVENT_FLYER` and `config.PHOTOS[0]`, which inlined the same
  ~717KB JPEG twice and pushed Home to 2.5MB of HTML per rerun. Don't reintroduce that — the
  flyer is rendered by `flyer_card()`; `PHOTOS` is the gallery and should not repeat it.
- **`config.SPONSORS` ships empty** so the Home page shows a "coming soon" placeholder until
  real sponsor logos are added. When you do add stand-ins, keep them unmistakably fake — never
  invent a plausible company name a guest could take for a real backer. See `assets/README.md`.
- **Guest-name storage is derived, not fixed.** `utils.GUEST_NAMES_MAX_CHARS`
  (= `MAX_GUEST_NAMES × (MAX_NAME_LENGTH + 1)`) sizes three things that must agree: the
  `plus_one_name` columns, the `ALTER … TYPE VARCHAR(n)` in `init_db()`, and the Register
  form's `max_chars`. Never hardcode a width there — a fixed 1000 silently truncated the tail
  of a large booking's guest list when the ticket cap was raised, losing real people off the
  door list with no error.
- **Timestamps are stored naive UTC and MUST be converted before display.**
  `_utc_now()` writes `checkin_time` / `created_at` / `visited_at` as naive UTC. Use
  `utils.format_event_local_dt()` (or `utils.to_event_local()`) for anything a human reads —
  door staff, admin charts, the CSV export. `utils.format_dt()` is deliberately RAW: its only
  correct caller is the admin backup caption, which labels itself "UTC". Getting this wrong is
  not cosmetic: showing a 6:05 PM CDT check-in as "11:05 PM" misleads the door, and bucketing a
  local event day against UTC values dropped every check-in after 7 PM local off the event-day
  chart. To filter a stored column by a LOCAL day, convert the day's bounds to UTC with
  `utils._local_day_utc_bounds()` — you cannot push a per-row conversion into the WHERE clause.
  Known gap: the raw Postgres reporting views in `utils._reporting_view_sql()` still bucket on
  UTC dates (`created_at::date`, `CURRENT_DATE`); they are organiser-run SQL, not app UI.
- **Check-in is gated by an event-time window.** `utils.check_in_by_code()` refuses outside it
  and returns `status="not_open"`. Mode is persisted in the `app_settings` table
  (`checkin_mode` = `auto` | `open` | `closed`, default `auto`). Tests must call
  `utils.set_checkin_mode(utils.CHECKIN_MODE_OPEN)` in `setUp` — otherwise every check-in test
  fails, because the real window doesn't open until the configured event date. Admin-initiated
  check-ins pass `bypass_window=True`.
- **Registration email is fire-and-forget** (`utils.send_qr_email_async`). It snapshots the SMTP
  secrets on the calling thread; the worker must never touch `st.*`. Don't assume a synchronous
  result. `send_qr_email()` stays synchronous for the Resend buttons.
- **`plus_one_name` holds newline-joined names**, not one. The column is `VARCHAR(1000)` and
  `init_db()` widens it on Postgres. Read it via `utils.guest_names_list()` /
  `utils.guest_name_count()` — never `.split()` it inline.
- **Guest names are required and counted against the ticket count.** One ticket per person and
  the booker holds the first, so a booking of N tickets must name exactly N-1 others
  (`utils.additional_guests_expected`). `validate_registration()` enforces it and takes
  `ticket_count` for that reason; it rejects too few names, too many, and any name on a
  1-ticket booking. `utils.MAX_GUEST_NAMES` is derived as
  `config.MAX_TICKETS_PER_REGISTRATION - 1` so the selector and the name list can't disagree.
  Rows registered before this rule can still be short — `get_stats()["unnamed_tickets"]` counts
  them, and `utils.party_size()` tolerates them, so don't assume names == tickets-1 when
  *reading*.
- **`st.data_editor` paints cells on a canvas** with no accessibility mirror, so E2E tests
  cannot read cell text. Assert on the app's own "N of M guests shown" caption instead, and
  cover mutations through `utils.apply_guest_changes()` at the service level.
- **Never call `st.success()` immediately before `st.rerun()`** — the rerun discards the frame
  and the message is never painted. Use `_set_flash()` / `_render_flash()`.
- **Streamlit checkboxes can't be driven by Playwright's `.check()`** (the real input is
  zero-width). Click the visible `<label>` and assert on `aria-checked`.

## Known Pitfalls
- **Streamlit re-runs the whole script on every interaction.** Anything expensive at module
  scope runs on every click. `init_db()` is therefore wrapped in `ensure_db_ready()`
  (`@st.cache_resource`), and stats reads are wrapped in `@st.cache_data(ttl=10)` in
  `streamlit_app.py`. Call `st.cache_data.clear()` after any mutation or the numbers go stale.
- Supabase direct `db.*.supabase.co` host may not resolve; use the **Pooler** host.
- `datetime.utcnow()` is deprecated; use `_utc_now()` in `utils.py`.
- The registration ticket count must be rendered **outside** the `st.form(...)` block so the
  live total updates.
- `checkin_time` can be NULL while `checked_in` is true. Never call `.strftime()` on it
  directly — use `utils.format_dt()`.
- Python 3.14 cannot import `altair`, so `st.bar_chart` breaks there. Develop on 3.12.
- The ticket price is `config.TICKET_PRICE_CENTS`, a **constant, not a secret**. `get_secret()`
  gives `st.secrets` precedence over code defaults, so a stale `TICKET_PRICE_CENTS` left in the
  Streamlit Cloud dashboard used to silently override a shipped price change — the $20 → $30
  rise deployed fine and the live site kept charging $20. Change the price in `config.py` and
  redeploy. Delete `TICKET_PRICE_CENTS` from Cloud secrets if it is still there; it is ignored.
- Streamlit is pinned to 1.40.0. `st.pills`, `st.segmented_control`, `st.badge`, and
  `st.metric(border=...)` do **not** exist in it.

## Common Verification Flow
1. Run unit tests, then the E2E suite.
2. Push to `main`.
3. Streamlit Cloud → **Manage app** → **Reboot app** (or wait for auto-deploy).
4. Verify: no DB warning banner; hero date/venue and Zelle info correct; ticket count updates
   the total live; admin login works and the tabs render.
5. Delete any test registrations you created.
