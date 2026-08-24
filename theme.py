"""
Party Check-In System — Design System

Convention: every component builder below RETURNS an html string. The caller
is responsible for rendering it, e.g.:

    st.markdown(theme.hero(), unsafe_allow_html=True)

The one exception is `inject_css()`, which is a page-setup call rather than a
component — it writes the consolidated <style> block directly via
`st.markdown(..., unsafe_allow_html=True)` and returns None.

All dynamic text passed into these builders is run through `html.escape()`
before interpolation, since callers may pass guest names, emails, Zelle refs,
or other secret-derived config values (e.g. `config.zelle_info()`) into them.
"""

import html

import streamlit as st

import config

# Series color for st.bar_chart / st.line_chart, kept in step with --gold
# so charts match the rest of the palette instead of Streamlit default blue.
CHART_COLOR = "#D4AF37"

# ── Design tokens + consolidated stylesheet ─────────────────────────────────

_CSS = """
<style>
/* Typography: Tunga carries the two brand moments (hero title, brand bar)
   with a Kannada-traditional feel. Bitter, a sturdy slab serif, carries
   headings so they read well on a phone in a dim ballroom. Body copy stays
   Inter for clarity at small sizes. */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Bitter:wght@600;700;800&family=Tunga&family=Noto+Sans+Kannada:wght@400;500;600;700&display=swap');

:root {
    /* ── Colour tokens: Yakshagana ────────────────────────────────────
       Deep maroon, saffron gold, warm orange, and forest green — inspired
       by the vibrant costumes and stage of Yakshagana, Karnataka's
       traditional theatre. The palette stays dark so it reads well on
       phones in a dim ballroom. */
    --gold: #F4B942;           /* saffron / gold ornament */
    --gold-rgb: 244, 185, 66;
    --gold-soft: #FCE8C6;      /* light saffron */
    --gold-soft-rgb: 252, 232, 198;
    --gold-dark: #C78A1E;
    --gold-dark-rgb: 199, 138, 30;
    --leather: #6B1A1A;        /* deep maroon base */
    --leather-rgb: 107, 26, 26;
    --tan: #D67D4A;            /* warm orange accent */
    --tan-rgb: 214, 125, 74;
    --rust: #9E2B25;           /* deep red kireeta */
    --rust-rgb: 158, 43, 37;
    --turquoise: #2E8B57;      /* forest green costume accent */
    --turquoise-rgb: 46, 139, 87;
    --mint: #92FE9D;

    --ink: #1A0A0A;            /* dark maroon-black */
    --surface: #2A1010;
    --surface-2: #3A1816;
    --elevated: rgba(252, 232, 198, 0.05);
    --elevated-strong: rgba(252, 232, 198, 0.10);
    --border: rgba(252, 232, 198, 0.12);
    --border-strong: rgba(252, 232, 198, 0.22);

    --text: #FFF5E6;           /* warm cream, not white */
    --text-rgb: 255, 245, 230;
    --text-dim: rgba(255, 245, 230, 0.68);
    --text-dimmer: rgba(255, 245, 230, 0.48);

    --ok: #22C55E;
    --ok-rgb: 34, 197, 94;
    --ok-bg: rgba(34, 197, 94, 0.12);
    --ok-border: rgba(34, 197, 94, 0.3);

    --warn: #F59E0B;
    --warn-rgb: 245, 158, 11;
    --warn-bg: rgba(245, 158, 11, 0.12);
    --warn-border: rgba(245, 158, 11, 0.3);

    --err: #FF6B6B;
    --err-rgb: 255, 107, 107;
    --err-bg: rgba(255, 107, 107, 0.12);
    --err-border: rgba(255, 107, 107, 0.3);

    --info: #3B82F6;
    --info-rgb: 59, 130, 246;
    --info-bg: rgba(59, 130, 246, 0.12);
    --info-border: rgba(59, 130, 246, 0.3);

    /* Radii */
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 20px;
    --radius-pill: 999px;

    /* Shadows */
    --shadow-sm: 0 4px 14px rgba(0, 0, 0, 0.25);
    --shadow-md: 0 8px 32px rgba(0, 0, 0, 0.35);
    --shadow-lg: 0 10px 40px rgba(0, 0, 0, 0.5);
    --shadow-gold: 0 4px 14px rgba(var(--gold-rgb), 0.25);
    --shadow-gold-lg: 0 0 30px rgba(var(--gold-rgb), 0.2);

    /* Spacing scale */
    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-5: 20px;
    --space-6: 24px;
    --space-8: 32px;
}

/* ── Base typography & background ─────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

/* Deep maroon stage curtain ground: a warm gradient, plus two very faint
   radial pools that suggest temple-lamplight without competing with the
   text on top of it. Pure CSS — no image request, nothing extra to load on
   a phone tethered to ballroom wifi. */
.stApp {
    background:
        radial-gradient(900px 500px at 12% -8%, rgba(var(--leather-rgb), 0.30) 0%, transparent 60%),
        radial-gradient(800px 500px at 88% 6%, rgba(var(--rust-rgb), 0.18) 0%, transparent 62%),
        linear-gradient(135deg, var(--ink) 0%, var(--surface) 55%, var(--surface-2) 100%) !important;
    background-attachment: fixed !important;
}

h1, h2, h3 {
    color: var(--text) !important;
    font-family: 'Bitter', Georgia, serif !important;
    font-weight: 700 !important;
    letter-spacing: 0.2px;
}
/* Page titles come from st.title("<emoji> Text") — a single text node mixing
   a color-emoji glyph with plain text. Gradient text via background-clip:text
   + transparent fill does not compose with color-emoji glyphs in Chromium/
   WebKit: the emoji paints as a solid opaque box in the fill color instead of
   its real glyph. Custom HTML titles (theme.hero(), which puts its emoji and
   text in a <div>, not a bare <h1>) are unaffected and keep the full gradient
   treatment. Bare h1 (Streamlit's st.title output) gets a flat gold instead
   so its emoji renders correctly. */
h1 {
    color: var(--gold) !important;
}

#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}

/* ── Layout / overflow safety ─────────────────────────────────────────── */
html, body {
    overflow-x: hidden !important;
}
.block-container {
    padding: var(--space-6) var(--space-3) var(--space-8) var(--space-3) !important;
    max-width: 100% !important;
    width: 100% !important;
    overflow-x: hidden !important;
}

@media (min-width: 768px) {
    .block-container {
        max-width: 760px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        padding-left: var(--space-5) !important;
        padding-right: var(--space-5) !important;
    }
}

@media (min-width: 1200px) {
    .block-container {
        max-width: 1080px !important;
    }
}

img, pre, code {
    max-width: 100% !important;
}

/* ── Focus rings — keyboard accessibility ─────────────────────────────── */
:focus-visible {
    outline: 3px solid var(--turquoise) !important;
    outline-offset: 2px !important;
    border-radius: 6px !important;
}
button:focus-visible,
.stButton > button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
[role="radio"]:focus-visible,
[role="checkbox"]:focus-visible,
[tabindex]:focus-visible {
    outline: 3px solid var(--turquoise) !important;
    outline-offset: 2px !important;
}

/* ── Motion — only for users who don't prefer reduced motion ──────────── */
@media (prefers-reduced-motion: no-preference) {
    button, .stButton > button {
        transition: transform 0.15s ease, box-shadow 0.15s ease !important;
    }
    button:hover:not([role="tab"]):not([data-testid="stBaseButton-headerNoPadding"]),
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(var(--gold-rgb), 0.4) !important;
    }
    .nav-card {
        transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease !important;
    }
    .nav-card:hover {
        transform: translateY(-2px) !important;
    }
}

/* ── Buttons ───────────────────────────────────────────────────────────── */
/* Excludes Streamlit's own tab controls (button[role="tab"] / [data-baseweb="tab"])
   and the sidebar collapse/expand toggle (data-testid="stBaseButton-headerNoPadding") —
   both are plain <button> elements that would otherwise pick up this gold treatment
   too. They get their own dedicated styling further down. */
/* Gold-accented action buttons: dark-on-gold is the highest contrast
   pairing available here, so these are the buttons a guest has to find on a
   phone in a dim ballroom. The traditional read comes from the slab face
   and the deep maroon edge, not from dropping the contrast. */
button:not([role="tab"]):not([data-testid="stBaseButton-headerNoPadding"]),
.stButton > button {
    min-height: 48px !important;
    font-family: 'Bitter', Georgia, serif !important;
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.02em !important;
    border-radius: var(--radius-md) !important;
    background: linear-gradient(180deg, var(--gold) 0%, var(--gold-dark) 100%) !important;
    color: #2A1A08 !important;
    border: 1px solid rgba(90, 55, 15, 0.55) !important;
    box-shadow: var(--shadow-gold) !important;
}
/* Secondary buttons are deep maroon rather than grey glass. */
button[kind="secondary"], .stButton > button[kind="secondary"] {
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.45) 0%, rgba(var(--leather-rgb), 0.22) 100%) !important;
    color: var(--gold-soft) !important;
    border: 1px solid rgba(var(--tan-rgb), 0.45) !important;
    box-shadow: none !important;
}
/* Disabled buttons (e.g. the Danger Zone delete button before the RESET
   phrase matches) must read as visibly inert, not just refuse clicks —
   otherwise a disabled gold button looks identical to an enabled one. */
button:disabled, .stButton > button:disabled,
button[disabled], .stButton > button[disabled] {
    opacity: 0.4 !important;
    cursor: not-allowed !important;
    box-shadow: none !important;
    transform: none !important;
}
.stDownloadButton > button {
    min-height: 48px !important;
    border-radius: var(--radius-md) !important;
}

/* ── Inputs: dark glass ────────────────────────────────────────────────── */
input, .stTextInput > div > div > input, .stNumberInput > div > div > input,
.stSelectbox > div > div, .stTextArea > div > div > textarea {
    font-size: 1.05rem !important;
    min-height: 48px !important;
    background: var(--elevated-strong) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--radius-md) !important;
}
input::placeholder, .stTextInput > div > div > input::placeholder {
    color: var(--text-dimmer) !important;
}

/* ── Cards / containers: carved wooden panels ─────────────────────────── */
div[data-testid="stContainer"] {
    border-radius: var(--radius-lg) !important;
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.16) 0%, var(--elevated) 100%) !important;
    border: 1px solid rgba(var(--tan-rgb), 0.22) !important;
    box-shadow: var(--shadow-md) !important;
}

/* ── Sticky brand bar ──────────────────────────────────────────────────── */
.brand-bar {
    position: sticky;
    top: 0;
    z-index: 999;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: 10px var(--space-4);
    margin: 0 0 var(--space-5) 0;
    background: rgba(20, 15, 10, 0.94);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(var(--tan-rgb), 0.30);
    /* Gold border along the bottom edge — the temple-frame detail that
       makes the sticky bar read as part of the theme rather than browser
       chrome. */
    border-bottom: 2px solid rgba(var(--gold-rgb), 0.55);
    border-radius: var(--radius-md);
}
.brand-bar-title {
    font-family: 'Tunga', 'Bitter', Georgia, serif;
    font-weight: 400;
    font-size: 0.95rem;
    color: var(--gold-soft);
    display: flex;
    align-items: center;
    gap: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

/* Streamlit renders a fixed sidebar-toggle chevron over the top-left corner
   when the sidebar is collapsed. On narrow viewports the block-container has
   little side padding, so the brand bar needs extra left clearance to avoid
   the title text rendering underneath that control. */
@media (max-width: 767px) {
    .brand-bar {
        padding-left: 52px;
    }
}

/* ── Sidebar collapse / expand controls ───────────────────────────────────
   Streamlit's built-in chevron (collapsed state, floats top-left) and the
   "×" close control (expanded state, inside the sidebar header) are plain
   <button> elements. Give them a subtle ghost treatment instead of the
   gold gradient the general button rule would otherwise apply — they're
   chrome, not calls to action. */
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="stSidebarCollapseButton"] button {
    background: transparent !important;
    color: var(--text-dim) !important;
    border: 1px solid var(--border-strong) !important;
    box-shadow: none !important;
    min-height: 40px !important;
    min-width: 40px !important;
}
[data-testid="stSidebarCollapsedControl"] button:hover,
[data-testid="stSidebarCollapseButton"] button:hover {
    background: var(--elevated) !important;
    color: var(--gold-soft) !important;
    border-color: rgba(var(--gold-rgb), 0.35) !important;
    box-shadow: none !important;
    transform: none !important;
}

/* ── Pills / badges ────────────────────────────────────────────────────── */
/* Temple-festival badges: warm fill, tan edge, and a dashed inner rule
   that reads as hand-stitched border trim. */
.pill, .badge {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.35) 0%, rgba(0, 0, 0, 0.45) 100%);
    border: 1px solid rgba(var(--tan-rgb), 0.55);
    border-radius: var(--radius-pill);
    padding: 7px 15px;
    margin: 4px 4px 0 0;
    color: var(--text);
    font-size: 0.85rem;
    font-weight: 600;
    white-space: nowrap;
    max-width: 100%;
}
.pill::after, .badge::after {
    content: "";
    position: absolute;
    inset: 3px;
    border: 1px dashed rgba(var(--tan-rgb), 0.40);
    border-radius: var(--radius-pill);
    pointer-events: none;
}
.badge-wide {
    white-space: normal;
}
.pill-countdown {
    border-color: rgba(var(--turquoise-rgb), 0.6);
    color: var(--gold-soft);
}
.pill-countdown::after {
    border-color: rgba(var(--turquoise-rgb), 0.35);
}

/* ── Hero banner ───────────────────────────────────────────────────────── */
/* The proscenium banner: maroon wash, gold edge, and a stitched inner
   border like a Yakshagana back curtain. */
.hero-banner {
    position: relative;
    background:
        radial-gradient(600px 220px at 50% 0%, rgba(var(--gold-rgb), 0.16) 0%, transparent 70%),
        linear-gradient(135deg, rgba(var(--leather-rgb), 0.38) 0%, rgba(var(--rust-rgb), 0.20) 100%);
    border: 2px solid rgba(var(--gold-rgb), 0.45);
    border-radius: var(--radius-xl);
    padding: var(--space-6) var(--space-5);
    text-align: center;
    box-shadow: var(--shadow-gold-lg);
    margin-bottom: var(--space-5);
    overflow: hidden;
}
.hero-banner::before {
    content: "";
    position: absolute;
    inset: 6px;
    border: 1px dashed rgba(var(--tan-rgb), 0.45);
    border-radius: calc(var(--radius-xl) - 4px);
    pointer-events: none;
}
.hero-title {
    /* Demoted to a small "presented by" eyebrow line — see the
       .hero-event-name comment below for why. */
    font-family: 'Tunga', 'Bitter', Georgia, serif;
    font-size: 1.05rem;
    font-weight: 400;
    margin: 0 0 6px 0;
    background: linear-gradient(180deg, var(--gold-soft) 0%, var(--gold) 55%, var(--gold-dark) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 0.5px;
    line-height: 1.25;
    /* Tunga is a single-weight Kannada face, so the "carved in temple stone"
       depth comes from a drop-shadow filter rather than a heavier face.
       filter (not text-shadow) because the glyphs are painted with
       background-clip. */
    filter: drop-shadow(0 2px 0 rgba(0, 0, 0, 0.55));
}
/* The actual event name (config.EVENT_SUBTITLE, e.g. "Prasanga — Sri Devi
   Mahathme") — the headline of the banner. A guest arriving from the flyer
   is here for THIS specific performance, not primarily to learn who the
   presenting org is, so it now leads visually: the largest, boldest text
   on the banner, ahead of .hero-title above it. .hero-title used to be
   bigger (2.1rem vs 1.3rem here) despite the docstring's stated intent that
   this line "outrank" everything below it — it never actually outranked
   the org name itself, so the org name (not the performance) was what a
   guest's eye landed on first. Swapped: .hero-title is now a compact
   eyebrow ("presented by DFW Yakshagana Havyasis") and this is the title. */
.hero-event-name {
    font-family: 'Bitter', Georgia, serif;
    font-size: 2rem;
    color: var(--gold);
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: 0.2px;
    margin-bottom: 8px;
    text-shadow: 0 2px 0 rgba(0, 0, 0, 0.45);
}
/* The Kannada line from the event branding. Kannada has taller stacked
   glyphs than Latin, so it gets its own line-height and a dedicated Kannada
   face — Tunga/Bitter have no Kannada coverage at all. */
.hero-subtitle-local {
    font-family: 'Noto Sans Kannada', 'Tunga', 'Inter', sans-serif;
    font-size: 1rem;
    color: var(--tan);
    font-weight: 600;
    line-height: 1.9;
    margin-bottom: var(--space-2);
}
/* The org's mission tagline (config.EVENT_TAGLINE) — demoted to small
   supporting text under the event name and Kannada line, not competing
   with either for attention. */
.hero-tagline {
    font-family: 'Inter', sans-serif;
    font-size: 0.82rem;
    color: var(--text-dim);
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: var(--space-3);
}
/* Event theme badge — the loudest thing after the event name, because it is
   the one instruction a guest has to act on before they arrive. Pill (name)
   and note (dress-code detail) are stacked as separate block elements
   inside a column wrapper rather than crammed into one flex row, so each
   wraps on its own at narrow widths instead of the pill shrink-wrapping
   into a cramped, lopsided two-line badge. */
.hero-theme-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    margin: 0 0 var(--space-3) 0;
}
.hero-theme {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 18px;
    border-radius: var(--radius-pill);
    background: linear-gradient(180deg, rgba(var(--rust-rgb), 0.55) 0%, rgba(var(--rust-rgb), 0.30) 100%);
    border: 1px solid rgba(var(--tan-rgb), 0.65);
    color: var(--text);
    font-family: 'Bitter', Georgia, serif;
    font-weight: 800;
    font-size: 0.95rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    white-space: nowrap;
}
.hero-theme-note {
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    font-size: 0.82rem;
    color: var(--gold-soft);
    opacity: 0.9;
    text-align: center;
    line-height: 1.4;
    max-width: 320px;
}
.hero-badges {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0;
}

@media (max-width: 640px) {
    .hero-title { font-size: 0.85rem !important; }
    .hero-event-name { font-size: 1.5rem !important; }
    .hero-theme { font-size: 0.85rem !important; padding: 6px 14px !important; }
}

/* ── Event strip (Register page) ───────────────────────────────────────── */
/* A horizontal strip that echoes the maroon-and-gold border of a temple
   festival notice. */
/* Wraps to as many lines as it needs on a phone rather than shrinking the
   text — a venue address that has to be squinted at is worse than one that
   takes two lines. */
.event-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
    padding: 10px var(--space-4);
    margin: 0 0 var(--space-4) 0;
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.22) 0%, var(--elevated) 100%);
    border: 1px solid rgba(var(--tan-rgb), 0.28);
    border-left: 3px solid var(--gold);
    border-radius: var(--radius-md);
    font-size: 0.9rem;
    color: var(--text-dim);
}
/* The performance's own name (config.EVENT_SUBTITLE) — a heading ABOVE the
   chip strip, not another chip inside it. See theme.event_strip()'s
   docstring for why: it used to reuse .event-strip-date's plain text-dim
   styling plus a 🎭 duplicated from the dress-theme chip a few items over,
   so it read as one more metadata pill instead of the event's title. */
.event-strip-title {
    font-family: 'Bitter', Georgia, serif;
    font-weight: 800;
    font-size: 1.1rem;
    color: var(--gold);
    text-align: center;
    line-height: 1.3;
    margin: 0 0 var(--space-2) 0;
}
.event-strip-venue { min-width: 0; }
.event-strip-theme {
    font-family: 'Bitter', Georgia, serif;
    font-weight: 800;
    color: var(--gold-soft);
    text-transform: uppercase;
    font-size: 0.8rem;
    letter-spacing: 0.05em;
}

/* ── Section header ────────────────────────────────────────────────────── */
/* A short gold rule under each heading — the repeated motif that runs
   through the whole theme, at section scale. */
.section-header {
    margin: var(--space-6) 0 var(--space-3) 0;
    padding-bottom: 6px;
    border-bottom: 1px solid rgba(var(--tan-rgb), 0.22);
}
.section-header h3 {
    margin: 0 !important;
    font-size: 1.2rem !important;
    color: var(--gold-soft) !important;
}
.section-subtitle {
    color: var(--text-dim);
    font-size: 0.88rem;
    margin: 2px 0 0 0;
}

/* ── Stat tile grid ────────────────────────────────────────────────────── */
/* auto-fill (not auto-fit) so every stat_tiles() call gets the same track
   width regardless of how many tiles are in the group — a 2-tile row (e.g.
   "Traffic") keeps the same tile width as a 6- or 9-tile row above it
   instead of its tracks stretching to fill the leftover space. */
.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: var(--space-3);
    margin: var(--space-3) 0 var(--space-5) 0;
}
.stat-tile {
    position: relative;
    overflow: hidden; /* clip the ::before accent bar to the tile's rounded corners */
    display: flex;
    flex-direction: column;
    background: var(--elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-4) var(--space-5);
    box-shadow: var(--shadow-md);
    min-width: 0;
}
/* Every tile gets a top-edge accent bar — neutral by default, colored per
   `accent` for tiles that opt in (see theme.stat_tiles()). Gives each stat
   a bit of identity instead of a uniform grid of flat grey boxes. */
.stat-tile::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--border-strong);
}
.stat-tile.accent-gold::before { background: linear-gradient(90deg, var(--gold-dark), var(--gold)); }
.stat-tile.accent-ok::before { background: var(--ok); }
.stat-tile.accent-warn::before { background: var(--warn); }
.stat-tile.accent-err::before { background: var(--err); }
.stat-tile.accent-info::before { background: var(--info); }
.stat-tile.accent-rust::before { background: var(--rust); }
.stat-tile.accent-turquoise::before { background: var(--turquoise); }

.stat-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.72rem;
    line-height: 1.3;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-dim);
    margin-bottom: 4px;
    /* Reserve room for a two-line label so the value below always starts at
       the same height, whether this tile's label wraps or not. */
    min-height: 2.6em;
    overflow-wrap: break-word;
}
.stat-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--elevated-strong);
    font-size: 0.82rem;
    text-transform: none;
    letter-spacing: normal;
}
.stat-tile.accent-gold .stat-icon { background: rgba(var(--gold-rgb), 0.18); }
.stat-tile.accent-ok .stat-icon { background: var(--ok-bg); }
.stat-tile.accent-warn .stat-icon { background: var(--warn-bg); }
.stat-tile.accent-err .stat-icon { background: var(--err-bg); }
.stat-tile.accent-info .stat-icon { background: var(--info-bg); }
.stat-tile.accent-rust .stat-icon { background: rgba(var(--rust-rgb), 0.18); }
.stat-tile.accent-turquoise .stat-icon { background: rgba(var(--turquoise-rgb), 0.18); }

.stat-value {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--gold-soft);
    line-height: 1.15;
    overflow-wrap: break-word;
    /* Bottom-align the value (and caption, if any) within the tile so every
       value in a row sits on the same baseline even when tiles are
       grid-stretched to the row's tallest neighbor. */
    margin-top: auto;
}
.stat-tile.accent-ok .stat-value { color: var(--ok); }
.stat-tile.accent-warn .stat-value { color: var(--warn); }
.stat-tile.accent-err .stat-value { color: var(--err); }
.stat-tile.accent-info .stat-value { color: var(--info); }
.stat-tile.accent-rust .stat-value { color: var(--rust); }
.stat-tile.accent-turquoise .stat-value { color: var(--turquoise); }

.stat-caption {
    font-size: 0.78rem;
    color: var(--text-dimmer);
    margin-top: 4px;
}

/* ── Hero stat tile ────────────────────────────────────────────────────── */
/* Reserved for the 1-2 numbers that actually matter operationally on a given
   page (e.g. Checked In / Total Guests) — bigger value, tinted wash, and it
   spans two grid tracks so it visually leads the row instead of blending
   into a uniform grid of identical boxes. */
.stat-tile-hero {
    grid-column: span 2;
    padding: var(--space-5) var(--space-6);
    border-color: var(--border-strong);
}
.stat-tile-hero .stat-label {
    font-size: 0.78rem;
    min-height: 0;
}
.stat-tile-hero .stat-icon {
    width: 26px;
    height: 26px;
    font-size: 0.95rem;
}
.stat-tile-hero .stat-value {
    font-size: 2.5rem;
}
.stat-tile-hero.accent-gold { background: linear-gradient(135deg, rgba(var(--gold-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-ok { background: linear-gradient(135deg, rgba(var(--ok-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-warn { background: linear-gradient(135deg, rgba(var(--warn-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-err { background: linear-gradient(135deg, rgba(var(--err-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-info { background: linear-gradient(135deg, rgba(var(--info-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-rust { background: linear-gradient(135deg, rgba(var(--rust-rgb), 0.16) 0%, var(--elevated) 100%); }
.stat-tile-hero.accent-turquoise { background: linear-gradient(135deg, rgba(var(--turquoise-rgb), 0.16) 0%, var(--elevated) 100%); }

@media (max-width: 380px) {
    /* Even a 2-column layout gets tight under ~380px with tile padding —
       let the hero tile take the full row's single column there instead of
       forcing two 150px tracks to squeeze in. */
    .stat-tile-hero { grid-column: 1 / -1; }
}

/* ── Progress meter (real labelled progress, not a bare st.progress) ────── */
.progress-meter {
    margin: var(--space-2) 0 var(--space-5) 0;
}
.progress-meter-track {
    position: relative;
    height: 14px;
    border-radius: var(--radius-pill);
    background: var(--elevated-strong);
    border: 1px solid var(--border);
    overflow: hidden;
}
.progress-meter-fill {
    height: 100%;
    border-radius: var(--radius-pill);
    background: linear-gradient(90deg, var(--gold-dark) 0%, var(--gold) 60%, var(--gold-soft) 100%);
    box-shadow: 0 0 10px rgba(var(--gold-rgb), 0.45);
    transition: width 0.4s ease;
}
.progress-meter-detail {
    margin-top: 8px;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text);
}

/* ── Ticket capacity (how many tickets are left to sell) ────────────────── */
/* The venue's hard cap, shown on Home and above the Register form. Reuses
   the progress-meter track shape so "how full is the party" reads the same
   way as "how many have checked in". See theme.tickets_remaining(). */
.tickets-left {
    background: var(--elevated);
    border: 1px solid var(--border);
    border-left: 3px solid var(--gold);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    margin: 0 0 var(--space-4) 0;
}
.tickets-left.is-low { border-left-color: var(--warn); }
.tickets-left.is-out { border-left-color: var(--err); }
.tickets-left-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
    margin-bottom: 10px;
}
.tickets-left-count {
    font-size: 1.15rem;
    font-weight: 800;
    color: var(--gold-soft);
}
.tickets-left.is-low .tickets-left-count { color: var(--warn); }
.tickets-left.is-out .tickets-left-count { color: var(--err); }
.tickets-left-count strong { font-size: 1.5rem; }
.tickets-left-of {
    color: var(--text-dimmer);
    font-size: 0.85rem;
    font-weight: 600;
}
.tickets-left-track {
    height: 10px;
    border-radius: var(--radius-pill);
    background: var(--elevated-strong);
    border: 1px solid var(--border);
    overflow: hidden;
}
.tickets-left-fill {
    height: 100%;
    border-radius: var(--radius-pill);
    background: linear-gradient(90deg, var(--gold-dark) 0%, var(--gold) 60%, var(--gold-soft) 100%);
    transition: width 0.4s ease;
}
.tickets-left.is-low .tickets-left-fill {
    background: linear-gradient(90deg, var(--warn) 0%, var(--gold-soft) 100%);
}
.tickets-left-note {
    margin-top: 8px;
    color: var(--text-dim);
    font-size: 0.85rem;
}

/* Full-width refusal shown in place of the Register form once the cap is hit. */
.sold-out-notice {
    text-align: center;
    background: var(--err-bg);
    border: 1px solid var(--err-border);
    border-radius: var(--radius-lg);
    padding: var(--space-6) var(--space-5);
    margin: var(--space-4) 0;
}
.sold-out-icon { font-size: 2.2rem; margin-bottom: 8px; }
.sold-out-title {
    font-size: 1.25rem;
    font-weight: 800;
    color: var(--text);
    margin-bottom: 6px;
}
.sold-out-message {
    color: var(--text-dim);
    font-size: 0.95rem;
    line-height: 1.6;
    max-width: 46ch;
    margin: 0 auto;
}

/* ── Empty state ───────────────────────────────────────────────────────── */
/* A friendly placeholder for an otherwise-empty section (fresh install or
   just after an admin Danger Zone reset) so it reads as "nothing here yet",
   not "something is broken". */
.empty-state {
    text-align: center;
    padding: var(--space-6) var(--space-5);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-lg);
    background: var(--elevated);
    margin: var(--space-3) 0 var(--space-5) 0;
}
.empty-state-icon { font-size: 2rem; margin-bottom: 6px; }
.empty-state-title {
    font-weight: 800;
    color: var(--gold-soft);
    font-size: 1.05rem;
    margin-bottom: 4px;
}
.empty-state-message {
    color: var(--text-dim);
    font-size: 0.9rem;
    max-width: 46ch;
    margin: 0 auto;
}

/* ── Danger Zone (admin) ───────────────────────────────────────────────── */
.danger-zone-warning {
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.5;
}

/* ── Nav cards ─────────────────────────────────────────────────────────── */
.nav-card {
    background: var(--elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-5);
}
.nav-card:hover {
    background: rgba(var(--gold-rgb), 0.08);
    border-color: rgba(var(--gold-rgb), 0.3);
}
.nav-card h3 {
    color: var(--gold-soft) !important;
    margin: 0 0 6px 0 !important;
    font-size: 1.1rem !important;
}
.nav-card p {
    color: var(--text-dim);
    margin: 0 !important;
    font-size: 0.92rem !important;
}

/* ── Event flyer ───────────────────────────────────────────────────────── */
/* Framed like a festival poster on a temple notice board: gold edge,
   stitched inner rule, and a height cap so a tall portrait poster stays a
   glance rather than a wall you have to scroll past. On Home this is meant
   to read as the centrepiece of the page — thicker gold edge and a glow
   (shadow-gold-lg, the same treatment as the hero banner) rather than the
   flatter shadow-md an ordinary card gets — so raise the height cap
   accordingly instead of leaving the artwork visibly capped short. */
.flyer-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--space-5);
    margin: 0 0 var(--space-6) 0;
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.28) 0%, var(--elevated) 100%);
    border: 3px solid rgba(var(--gold-rgb), 0.55);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-gold-lg);
}
.flyer-card::before {
    content: "";
    position: absolute;
    inset: 8px;
    border: 1px dashed rgba(var(--tan-rgb), 0.4);
    border-radius: calc(var(--radius-xl) - 4px);
    pointer-events: none;
}
.flyer-card img {
    max-width: 100%;
    max-height: 85vh;
    width: auto;
    height: auto;
    border-radius: var(--radius-md);
    box-shadow: 0 10px 34px rgba(0, 0, 0, 0.5);
    position: relative;
}
.flyer-caption {
    position: relative;
    margin-top: var(--space-3);
    font-family: 'Bitter', Georgia, serif;
    font-size: 0.92rem;
    font-weight: 700;
    color: var(--gold-soft);
    text-align: center;
}

/* ── Photo gallery (Home) ──────────────────────────────────────────────── */
/* A plain responsive grid of fixed-ratio tiles. Fixed ratio matters: the
   photos are dropped in by the organiser at whatever size their phone
   produced, and without it a single portrait shot would tower over the row
   next to it. */
.photo-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    /* Size each card to its own content instead of stretching it to the
       tallest in the row: captions are optional, and a stretched card with
       no caption shows an empty strip that reads as a missing one. */
    align-items: start;
    gap: var(--space-3);
    margin: var(--space-3) 0 var(--space-5) 0;
}
.photo-card {
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--elevated);
    box-shadow: var(--shadow-md);
}
.photo-card img {
    display: block;
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
}
.photo-caption {
    padding: 10px var(--space-4) var(--space-3) var(--space-4);
    color: var(--text-dim);
    font-size: 0.85rem;
    line-height: 1.4;
}

/* ── Sponsor wall (Home) ───────────────────────────────────────────────── */
/* Grouped into labelled tiers, best first. The top tier gets wider tracks and
   a gold-tinted card, because visible prominence is the thing a headline
   sponsor is actually paying for — a wall where every logo looks identical
   sells the top tier short. */
.sponsor-wall {
    margin: var(--space-3) 0 var(--space-5) 0;
}
.sponsor-tier-heading {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: var(--space-4) 0 var(--space-2) 0;
    font-size: 0.75rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--gold);
}
/* A hairline rule trailing off to the right of each tier label. */
.sponsor-tier-heading::after {
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(var(--gold-rgb), 0.35), transparent);
}
.sponsor-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    align-items: start;
    gap: var(--space-3);
    margin: 0 0 var(--space-4) 0;
}
.sponsor-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 8px;
    padding: var(--space-5) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--elevated);
    box-shadow: var(--shadow-md);
    text-decoration: none !important;
    color: inherit;
}
a.sponsor-card:hover {
    background: rgba(var(--gold-rgb), 0.08);
    border-color: rgba(var(--gold-rgb), 0.3);
}
.sponsor-logo {
    max-height: 64px;
    max-width: 100%;
    width: auto;
    object-fit: contain;
}
.sponsor-name {
    font-weight: 800;
    font-size: 1rem;
    color: var(--gold-soft);
    overflow-wrap: break-word;
}
.sponsor-blurb {
    color: var(--text-dim);
    font-size: 0.85rem;
    line-height: 1.45;
}

/* Top tier: bigger card, bigger logo, gold wash. */
.sponsor-card.is-featured {
    padding: var(--space-6) var(--space-5);
    border-color: rgba(var(--gold-rgb), 0.4);
    background: linear-gradient(135deg, rgba(var(--gold-rgb), 0.14) 0%, var(--elevated) 100%);
    box-shadow: var(--shadow-gold-lg);
}
.sponsor-card.is-featured .sponsor-logo { max-height: 110px; }
.sponsor-card.is-featured .sponsor-name { font-size: 1.25rem; color: var(--gold); }
.sponsor-card.is-featured .sponsor-blurb { font-size: 0.92rem; }
/* The featured row gets wider tracks so a headline sponsor isn't squeezed
   into the same 190px column as a community supporter. Driven by a class the
   builder puts on the grid rather than by :has(), which isn't available in
   every browser a guest might open this on. */
.sponsor-grid.is-featured-row {
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}

/* ── Registration confirmation (top of Home, straight after a submit) ──── */
.confirm-card {
    background: linear-gradient(135deg, rgba(var(--ok-rgb), 0.16) 0%, rgba(var(--gold-rgb), 0.1) 100%);
    border: 1px solid var(--ok-border);
    border-radius: var(--radius-xl);
    padding: var(--space-6) var(--space-5);
    margin: 0 0 var(--space-5) 0;
    box-shadow: var(--shadow-md);
}
.confirm-icon { font-size: 2.2rem; line-height: 1; margin-bottom: 6px; }
.confirm-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--gold-soft);
    margin-bottom: 6px;
    overflow-wrap: break-word;
}
.confirm-message {
    color: var(--text);
    font-size: 0.98rem;
    line-height: 1.6;
}
.confirm-message strong { color: var(--gold-soft); word-break: break-word; }
.confirm-rows {
    margin-top: var(--space-4);
    border-top: 1px solid var(--border-strong);
    padding-top: var(--space-3);
}
.confirm-row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-4);
    padding: 5px 0;
    font-size: 0.95rem;
}
.confirm-label { color: var(--text-dim); flex: 0 0 auto; }
.confirm-value {
    color: var(--text);
    font-weight: 600;
    text-align: right;
    word-break: break-word;
}

/* ── Payment card ──────────────────────────────────────────────────────── */
/* The donation/prasada board: heavier panel, gold-maroon-green trim line
   along the top. */
.payment-card {
    background: linear-gradient(160deg, rgba(var(--leather-rgb), 0.22) 0%, var(--surface) 45%, #150E08 100%);
    border: 2px solid rgba(var(--gold-rgb), 0.45);
    border-radius: var(--radius-xl);
    padding: var(--space-6);
    box-shadow: var(--shadow-lg);
    position: relative;
    overflow: hidden;
}
.payment-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0; height: 4px;
    background: linear-gradient(90deg, var(--gold), var(--rust), var(--turquoise));
}
.payment-title {
    font-family: 'Bitter', Georgia, serif;
}
.payment-card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: var(--space-3);
}
.payment-icon { font-size: 1.8rem; }
.payment-title { font-size: 1.15rem; font-weight: 700; color: var(--gold-soft); }
.payment-desc {
    color: var(--text-dim);
    margin: 0 0 var(--space-4) 0;
}
.zelle-box {
    background: rgba(0, 0, 0, 0.35);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    margin-bottom: var(--space-4);
    border: 1px solid rgba(var(--gold-rgb), 0.25);
}
.zelle-label {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--gold);
    margin-bottom: 4px;
}
.zelle-email {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--gold-soft);
    letter-spacing: 0.3px;
    word-break: break-all;
}
.payment-price-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--text-dim);
}
.price-tag {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--gold);
}

/* ── Group-discount price table (inside the payment card) ──────────────── */
/* Every tier is listed, not just the one the guest currently qualifies for:
   the table sits above the ticket selector precisely so the price can
   influence how many tickets they pick. The row they're on is highlighted
   so "what am I paying" is still answerable at a glance. */
.tier-table {
    border: 1px solid rgba(var(--gold-rgb), 0.25);
    border-radius: var(--radius-md);
    background: rgba(0, 0, 0, 0.25);
    overflow: hidden;
}
.tier-table-head {
    padding: 10px var(--space-4);
    font-size: 0.82rem;
    color: var(--gold);
    border-bottom: 1px solid var(--border);
    line-height: 1.4;
}
.tier-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
    padding: 10px var(--space-4);
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.95rem;
}
.tier-row:first-of-type { border-top: none; }
.tier-row.is-active {
    background: rgba(var(--gold-rgb), 0.12);
    color: var(--text);
    box-shadow: inset 3px 0 0 var(--gold);
}
/* Bolder summary row appended when price_tier_table() is given a total —
   makes the payment card self-sufficient so the real amount to Zelle is
   visible without scrolling to total_card() further down the page. */
.tier-total {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
    padding: 12px var(--space-4);
    border-top: 2px solid var(--gold);
    background: rgba(var(--gold-rgb), 0.14);
    color: var(--text);
    font-size: 1rem;
    font-weight: 800;
}
.tier-total span:last-child { color: var(--gold); }
.tier-range { font-weight: 600; }
.tier-price {
    font-weight: 800;
    color: var(--gold-soft);
    white-space: nowrap;
}
.tier-row.is-active .tier-price { color: var(--gold); }
.tier-each {
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--text-dimmer);
}

/* "One more ticket unlocks the next tier" hint, under the total. */
.tier-nudge {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin: 0 0 var(--space-4) 0;
    font-size: 0.9rem;
    line-height: 1.5;
    color: var(--text);
}
.tier-nudge-icon { font-size: 1.1rem; line-height: 1.35; }
.tier-nudge strong { color: var(--gold-soft); }

/* ── Total-to-pay card ─────────────────────────────────────────────────── */
.total-card {
    background: linear-gradient(135deg, rgba(var(--gold-rgb), 0.25) 0%, rgba(var(--rust-rgb), 0.15) 100%);
    border: 1px solid rgba(var(--gold-rgb), 0.35);
    color: var(--text);
    padding: var(--space-5);
    border-radius: var(--radius-lg);
    text-align: center;
    margin: var(--space-4) 0;
}
.total-label {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--gold);
}
.total-value {
    font-size: 2.2rem;
    font-weight: 800;
    color: var(--gold);
    line-height: 1.2;
}
.total-caption {
    font-size: 0.88rem;
    color: var(--text-dim);
}

/* ── Cinema-style seat map ─────────────────────────────────────────────── */
/* Purely visual: the slider above it drives the actual selection. The map
   makes the tiered pricing tangible — guests see exactly which seats are
   $50, $25, and $10 before they Zelle. */
.seat-map-wrap {
    background: linear-gradient(180deg, rgba(var(--leather-rgb), 0.18) 0%, var(--elevated) 100%);
    border: 1px solid rgba(var(--gold-rgb), 0.22);
    border-radius: var(--radius-lg);
    padding: var(--space-5) var(--space-4);
    margin: var(--space-4) 0;
    text-align: center;
}
.seat-screen {
    display: inline-block;
    background: linear-gradient(90deg, rgba(var(--gold-rgb), 0.25), rgba(var(--gold-rgb), 0.10), rgba(var(--gold-rgb), 0.25));
    color: var(--gold-soft);
    font-family: 'Bitter', Georgia, serif;
    font-weight: 700;
    font-size: 0.9rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 8px 32px;
    border-radius: var(--radius-pill);
    margin-bottom: var(--space-4);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.seat-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: var(--space-4);
    align-items: center;
}
.seat-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
}
/* Row-letter gutter at the start of each row, like a real venue seating
   chart. Fixed width so every row's seats line up under each other
   regardless of whether the row letter is one character ("A") or two
   ("AA", past row 26) — see config.SEAT_ROW_LETTERS. */
.seat-row-label {
    flex: 0 0 16px;
    width: 16px;
    text-align: right;
    padding-right: 4px;
    font-family: 'Bitter', Georgia, serif;
    font-weight: 800;
    font-size: 0.68rem;
    color: var(--gold-soft);
    opacity: 0.85;
}
.seat {
    width: 26px;
    height: 26px;
    border-radius: 4px 4px 8px 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    font-weight: 700;
    color: rgba(0, 0, 0, 0.65);
    background: rgba(var(--gold-rgb), 0.18);
    border: 1px solid rgba(var(--gold-rgb), 0.35);
    box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.2);
}
/* Aisle gap: every 5th seat gets extra right margin to create a center aisle. */
.seat.aisle {
    margin-right: 14px;
}
.seat-gold {
    background: linear-gradient(180deg, var(--gold-soft) 0%, var(--gold) 100%);
    border-color: rgba(var(--gold-dark-rgb, 199, 138, 30), 0.8);
}
.seat-tan {
    background: linear-gradient(180deg, #F4C9A8 0%, var(--tan) 100%);
    border-color: rgba(var(--tan-rgb), 0.85);
}
.seat-turquoise {
    background: linear-gradient(180deg, #7EE6A8 0%, var(--turquoise) 100%);
    border-color: rgba(var(--turquoise-rgb), 0.85);
}
.seat.selected {
    box-shadow: 0 0 0 2px var(--text), 0 0 12px rgba(var(--gold-rgb), 0.55);
    color: #000;
}
/* TAKEN: visibly unavailable, not just "a different tier" — muted, flat,
   dashed border, reduced opacity, and the pointer says "no" too. */
.seat-taken {
    background: var(--surface-2);
    border: 1px dashed var(--border-strong);
    color: var(--text-dimmer);
    opacity: 0.45;
    box-shadow: none;
    cursor: not-allowed;
}
.seat-legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
}
.seat-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.82rem;
    color: var(--text-dim);
    font-weight: 600;
}
.seat-dot {
    width: 14px;
    height: 14px;
    border-radius: 4px 4px 6px 6px;
}
.seat-count {
    font-size: 0.85rem;
    color: var(--text-dim);
    font-weight: 600;
}

/* ── Seat price breakdown (subtotals per tier) ─────────────────────────── */
.seat-note {
    margin-top: var(--space-3);
    padding: 10px var(--space-3);
    border-radius: var(--radius-sm);
    background: rgba(var(--tan-rgb), 0.10);
    border: 1px dashed rgba(var(--tan-rgb), 0.35);
    color: var(--text-dim);
    font-size: 0.82rem;
    line-height: 1.45;
    text-align: center;
}
.seat-note strong { color: var(--gold-soft); }
.seat-breakdown {
    background: rgba(0, 0, 0, 0.22);
    border: 1px solid rgba(var(--gold-rgb), 0.18);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin: 0 0 var(--space-4) 0;
}
.breakdown-line {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    font-size: 0.9rem;
    color: var(--text-dim);
    padding: 4px 0;
}
.breakdown-line span:last-child {
    font-weight: 700;
    color: var(--gold-soft);
    white-space: nowrap;
}

@media (max-width: 480px) {
    /* A 10-across row of 3-digit seat numbers still has to fit a ~360px
       phone content width (10 cells + 9 gaps + the aisle gap), but the
       previous 20px/0.48rem cells were too small to actually read a seat
       number at a glance — this is as large as the row can go without
       overflowing at 430px. */
    .seat {
        width: 25px;
        height: 25px;
        font-size: 0.62rem;
        border-radius: 3px 3px 6px 6px;
    }
    .seat.aisle { margin-right: 10px; }
    .seat-row { gap: 4px; }
    .seat-grid { gap: 6px; }
    .seat-row-label {
        flex: 0 0 12px;
        width: 12px;
        padding-right: 2px;
        font-size: 0.56rem;
    }
}

/* ── Guest-names requirement (how many names the ticket count needs) ───── */
/* Sits between the seat selector and the form, and re-renders every time
   the seat count changes, so the guest learns how many names are wanted
   before they reach the field rather than from a validation error after
   submitting. See theme.guest_names_requirement(). */
.guest-req {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin: 0 0 var(--space-4) 0;
    font-size: 0.92rem;
    color: var(--text);
}
.guest-req.is-solo {
    background: var(--elevated);
    border-color: var(--border);
    color: var(--text-dim);
}
.guest-req-icon {
    font-size: 1.1rem;
    line-height: 1;
}
.guest-req-count {
    font-weight: 800;
    color: var(--gold);
}

/* ── Seat-selection policy chips (kids free / food at venue) ────────────── */
/* Two static venue-policy facts a guest must not miss while choosing seats
   — see theme.seat_policy_chips(). Distinct from .guest-req above (which is
   live validation on THIS booking's ticket count): these never change with
   the selection, so they get a calmer, permanent card treatment instead of
   the info-accent "note" styling. */
.policy-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0 0 var(--space-4) 0;
}
.policy-chip {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1 1 220px;
    background: var(--ok-bg);
    border: 1px solid var(--ok-border);
    border-radius: var(--radius-md);
    padding: 10px var(--space-4);
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text);
    line-height: 1.35;
}
.policy-chip-icon {
    font-size: 1.15rem;
    line-height: 1;
    flex-shrink: 0;
}

/* ── Venue info card ──────────────────────────────────────────────────── */
.venue-info-card {
    background: linear-gradient(160deg, rgba(var(--leather-rgb), 0.18) 0%, var(--elevated) 100%);
    border: 1px solid rgba(var(--gold-rgb), 0.22);
    border-radius: var(--radius-lg);
    padding: var(--space-4) var(--space-5);
    margin: 0 0 var(--space-4) 0;
}
.venue-info-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: var(--space-3);
}
.venue-info-icon { font-size: 1.4rem; }
.venue-info-title {
    font-family: 'Bitter', Georgia, serif;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--gold-soft);
}
.venue-info-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px var(--space-3);
    padding: 6px 0;
    border-top: 1px solid var(--border);
    font-size: 0.9rem;
}
.venue-info-row:first-of-type { border-top: none; }
.venue-info-label {
    font-weight: 700;
    color: var(--gold);
    min-width: 90px;
}
.venue-info-value {
    color: var(--text-dim);
    flex: 1;
}

/* ── Stepper ───────────────────────────────────────────────────────────── */
/* Left-aligned, not centered: the Register page is the app's landing page and
   everything else on it (title, section headers, form fields, labels) starts
   at the same left edge. A centered strip of step pills floating above all of
   that read as an unrelated, stray element rather than as the progress
   indicator for the form directly beneath it. */
.stepper {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0 0 var(--space-5) 0;
}
.step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--border);
    background: var(--elevated);
    font-size: 0.85rem;
    color: var(--text-dimmer);
}
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--elevated-strong);
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--text-dim);
}
.step-active {
    border-color: rgba(var(--gold-rgb), 0.5);
    color: var(--gold-soft);
}
.step-active .step-num {
    background: var(--gold);
    color: var(--ink);
}
.step-done {
    color: var(--ok);
}
.step-done .step-num {
    background: var(--ok);
    color: var(--ink);
}

/* ── Field error ───────────────────────────────────────────────────────── */
.field-error {
    color: var(--err) !important;
    font-size: 0.85rem !important;
    margin: 2px 0 var(--space-3) 0 !important;
}

/* ── Validation banner (registration form) ────────────────────────────── */
.validation-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--err-bg);
    border: 1px solid var(--err-border);
    border-radius: var(--radius-md);
    padding: var(--space-4) var(--space-5);
    color: var(--text);
    font-weight: 700;
    font-size: 0.98rem;
    margin: 0 0 var(--space-4) 0;
}

/* ── Closed notice (scanner page, check-in not open yet) ──────────────── */
.closed-notice {
    text-align: center;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: var(--radius-lg);
    padding: var(--space-6) var(--space-5);
    margin: var(--space-4) 0;
}
.closed-notice-icon { font-size: 2.2rem; margin-bottom: 8px; }
.closed-notice-title {
    font-size: 1.15rem;
    font-weight: 800;
    color: var(--text);
    margin-bottom: 6px;
}
.closed-notice-message { color: var(--text-dim); font-size: 0.95rem; }

/* ── Capacity guard: full-page notice + busy banner ───────────────────── */
/* Shown instead of the whole app when active_session_count() is over the
   hard limit — warm and party-themed, never "server error"-flavored. See
   streamlit_app._render_capacity_page(). */
.capacity-page {
    text-align: center;
    background: linear-gradient(135deg, rgba(var(--gold-rgb), 0.14) 0%, rgba(var(--rust-rgb), 0.1) 100%);
    border: 1px solid rgba(var(--gold-rgb), 0.35);
    border-radius: var(--radius-xl);
    padding: var(--space-8) var(--space-5);
    margin: var(--space-5) 0;
    box-shadow: var(--shadow-gold-lg);
}
.capacity-page-icon { font-size: 2.6rem; margin-bottom: var(--space-3); }
.capacity-page-title {
    font-size: 1.4rem;
    font-weight: 800;
    color: var(--gold-soft);
    margin-bottom: var(--space-3);
}
.capacity-page-message {
    color: var(--text-dim);
    font-size: 1rem;
    line-height: 1.6;
    max-width: 46ch;
    margin: 0 auto var(--space-4) auto;
}
.capacity-page-message strong { color: var(--text); }
.capacity-page-count {
    display: inline-block;
    margin-top: var(--space-2);
    color: var(--text-dimmer);
    font-size: 0.82rem;
}

/* Soft-limit banner: visitors are let through, just told it may be slow. */
.busy-banner {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    text-align: center;
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
    border-radius: var(--radius-md);
    padding: 10px var(--space-4);
    margin: 0 0 var(--space-4) 0;
    color: var(--text);
    font-size: 0.9rem;
    font-weight: 600;
}

/* ── Check-in window status banner (admin) ────────────────────────────── */
.checkin-window-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    border-radius: var(--radius-lg);
    padding: var(--space-4) var(--space-5);
    margin: var(--space-3) 0 var(--space-4) 0;
    font-size: 1.02rem;
    border: 1px solid var(--border);
}
.checkin-window-banner.status-ok {
    background: var(--ok-bg);
    border-color: var(--ok-border);
    color: var(--text);
}
.checkin-window-banner.status-warn {
    background: var(--warn-bg);
    border-color: var(--warn-border);
    color: var(--text);
}
.checkin-window-icon { font-size: 1.4rem; }

/* ── Guest result card (scanner) ──────────────────────────────────────── */
.guest-result-card {
    border-radius: var(--radius-lg);
    padding: var(--space-5);
    margin: var(--space-4) 0;
    border: 1px solid var(--border);
}
.guest-result-card.status-ok { background: var(--ok-bg); border-color: var(--ok-border); }
.guest-result-card.status-warn { background: var(--warn-bg); border-color: var(--warn-border); }
.guest-result-card.status-err { background: var(--err-bg); border-color: var(--err-border); }
.guest-result-name { font-size: 1.3rem; font-weight: 800; color: var(--text); }
.guest-result-meta { color: var(--text-dim); margin: 2px 0 8px 0; }
.guest-result-status { font-weight: 700; }
.status-ok .guest-result-status { color: var(--ok); }
.status-warn .guest-result-status { color: var(--warn); }
.status-err .guest-result-status { color: var(--err); }
.guest-result-message { margin-top: 8px; color: var(--text-dim); font-size: 0.9rem; }

/* ── Guest identity card (scanner: confirm before checking in) ─────────── */
.guest-identity-rows {
    margin-top: var(--space-3);
    border-top: 1px solid var(--border);
    padding-top: var(--space-3);
}
.guest-identity-row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-4);
    padding: 5px 0;
    font-size: 0.95rem;
}
.guest-identity-label { color: var(--text-dim); flex: 0 0 auto; }
/* Long emails must wrap rather than push the value off a phone screen. */
.guest-identity-value {
    color: var(--text);
    font-weight: 600;
    text-align: right;
    word-break: break-word;
}
.guest-identity-value.is-strong { font-size: 1.05rem; color: var(--gold); }

/* ── Footer ────────────────────────────────────────────────────────────── */
.app-footer {
    text-align: center;
    opacity: 0.5;
    font-size: 0.8em;
    margin-top: var(--space-6);
}

/* ── QR code image ─────────────────────────────────────────────────────── */
/* st.image() doesn't expose a way to set meaningful alt text (it defaults
   to the image's index, e.g. alt="0"), so target Streamlit's own image
   wrapper instead of alt text. This app only ever renders QR codes via
   st.image, so scoping to stImage is safe and specific enough. */
div[data-testid="stImage"] img {
    max-width: 100% !important;
    width: 320px !important;
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--shadow-gold-lg) !important;
}

/* ── Alerts ────────────────────────────────────────────────────────────── */
.stAlert {
    border-radius: var(--radius-md) !important;
}
.stSuccess {
    background: var(--ok-bg) !important;
    border: 1px solid var(--ok-border) !important;
}
.stInfo {
    background: var(--info-bg) !important;
    border: 1px solid var(--info-border) !important;
}
.stWarning {
    background: var(--warn-bg) !important;
    border: 1px solid var(--warn-border) !important;
}
.stError {
    background: var(--err-bg) !important;
    border: 1px solid var(--err-border) !important;
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */
/* Transparent/ghost tabs: muted text when inactive, gold text + gold
   underline when active. The tab list scrolls horizontally on narrow
   viewports instead of squashing labels. */
.stTabs [data-baseweb="tab-list"] {
    gap: var(--space-1);
    background: transparent !important;
    overflow-x: auto;
    overflow-y: hidden;
    flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {
    height: 4px;
}
.stTabs button[role="tab"],
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-dim) !important;
    border: none !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 10px var(--space-4) !important;
    margin: 0 !important;
    min-height: auto !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
}
.stTabs button[role="tab"]:hover,
.stTabs [data-baseweb="tab"]:hover {
    color: var(--gold-soft) !important;
    background: rgba(var(--gold-rgb), 0.08) !important;
}
.stTabs button[role="tab"][aria-selected="true"],
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: var(--gold) !important;
    font-weight: 700 !important;
    border-bottom-color: var(--gold) !important;
    background: transparent !important;
}
/* BaseWeb's own sliding highlight bar — we draw the underline per-tab above
   instead, so neutralize this to avoid a second, out-of-sync indicator. */
.stTabs [data-baseweb="tab-highlight"] {
    background: transparent !important;
}
.stTabs [data-baseweb="tab-border"] {
    background: var(--border) !important;
}

/* ── Mobile: wide content scrolls in its own box, never the page ─────────── */
div[data-testid="stDataFrame"], div[data-testid="stTable"] {
    overflow-x: auto !important;
    max-width: 100% !important;
}

@media (max-width: 480px) {
    .block-container {
        padding: var(--space-5) var(--space-2) var(--space-6) var(--space-2) !important;
    }
    .brand-bar-title { font-size: 0.85rem; }
    button:not([role="tab"]):not([data-testid="stBaseButton-headerNoPadding"]),
    .stButton > button {
        min-height: 48px !important;
        width: 100%;
    }
}
</style>
"""


def inject_css() -> None:
    """Render the consolidated design-system stylesheet. Call once per page load."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Component builders ───────────────────────────────────────────────────────

def countdown_pill() -> str:
    """A small pill showing days remaining until the event, via config.days_until_event()."""
    days = config.days_until_event()
    if days <= 0:
        label = "It's happening!"
    elif days == 1:
        label = "1 day to go"
    else:
        label = f"{days} days to go"
    return f'<span class="pill pill-countdown">⏳ {html.escape(label)}</span>'


def brand_bar() -> str:
    """Slim sticky bar with the event name and a countdown pill. Renders once per page."""
    return (
        '<div class="brand-bar">'
        f'<div class="brand-bar-title">🎭 {html.escape(config.EVENT_NAME)}</div>'
        f'{countdown_pill()}'
        '</div>'
    )


def hero() -> str:
    """The homepage hero banner: org name, event name, taglines, dress
    theme, and the date/time/venue badge row.

    Mirrors the printed flyer, because most guests arrive here straight from
    it. Hierarchy, top to bottom: a small "presented by" eyebrow line for
    the ORGANISATION name (`.hero-title`, config.EVENT_NAME — who is
    putting this on), then the actual EVENT/performance name as the
    HEADLINE (`.hero-event-name`, config.EVENT_SUBTITLE, e.g. "Sri Devi
    Mahathme" — what a guest is actually being invited to, so it is the
    largest, boldest text on the banner), then the Kannada tagline, then the
    org's mission tagline demoted to small supporting text
    (`.hero-tagline`, config.EVENT_TAGLINE). Earlier versions reused one
    `.hero-subtitle` class for both the org tagline AND the event name,
    which made the actual event a guest is being invited to visually
    indistinguishable from — and secondary to — the org's mission
    statement. Each now has its own class so weight matches importance; the
    org name (`.hero-title`) intentionally renders SMALLER than the
    performance name below it, not just smaller than the tagline, since the
    performance is the headline and the org is context.

    The dress theme gets its own badge — the one thing on this banner a
    guest has to *do* something about before the event, so it is not buried
    in the badge row.

    The countdown itself lives only in the sticky brand bar (always visible
    while scrolling) — it's intentionally not repeated here to avoid showing
    it twice on the same page.
    """
    local = html.escape(getattr(config, "EVENT_TAGLINE_LOCAL", "") or "")
    local_html = f'<div class="hero-subtitle-local">{local}</div>' if local else ""

    theme_name = html.escape(getattr(config, "EVENT_THEME", "") or "")
    theme_note = html.escape(getattr(config, "EVENT_THEME_NOTE", "") or "")
    if theme_name:
        # The pill (name) and the note (dress-code detail) are separate
        # block-level elements, not one flex row sharing a single pill —
        # cramming both into one `<div class="hero-theme">` used to force
        # the browser to shrink-wrap two flex items independently at narrow
        # widths, producing a lopsided two-line pill. Stacked, each wraps
        # cleanly on its own line instead.
        note_html = f'<div class="hero-theme-note">{theme_note}</div>' if theme_note else ""
        theme_html = (
            '<div class="hero-theme-wrap">'
            f'<span class="hero-theme">🎭 {theme_name} Theme</span>'
            f'{note_html}'
            '</div>'
        )
    else:
        theme_html = ""

    event_name = html.escape(getattr(config, "EVENT_SUBTITLE", "") or "")
    event_name_html = f'<div class="hero-event-name">{event_name}</div>' if event_name else ""

    event_tagline = html.escape(config.EVENT_TAGLINE)
    tagline_html = f'<div class="hero-tagline">{event_tagline}</div>' if config.EVENT_TAGLINE else ""

    return f"""
    <div class="hero-banner">
        <div class="hero-title">{html.escape(config.EVENT_NAME)}</div>
        {event_name_html}
        {local_html}
        {tagline_html}
        {theme_html}
        <div class="hero-badges">
            <span class="badge">📅 {html.escape(config.EVENT_DATE_TEXT)}</span>
            <span class="badge">🕕 {html.escape(config.EVENT_TIME_TEXT)}</span>
        </div>
        <div class="hero-badges">
            <span class="badge badge-wide">📍 {html.escape(config.VENUE_NAME)}, {html.escape(config.VENUE_ADDRESS)}</span>
        </div>
    </div>
    """


def event_strip() -> str:
    """The performance title, plus a compact date / venue / dress-theme chip
    strip, for the Register page.

    Register is the landing page, so for most guests it is the *only* page
    they see — and they arrive on it straight from the flyer, mid-decision,
    about to send money. The three things they need confirmed before that
    (is this the right party, where is it, what do I wear) live on Home's
    hero, which they may never reach. This restates them in one line.

    The performance name (config.EVENT_SUBTITLE) renders as its own heading
    ABOVE the chip strip, in `.event-strip-title` — not as one more `<span>`
    chip inside `.event-strip` alongside the date/venue/theme. It used to
    reuse `.event-strip-date`'s plain metadata styling and lead with a 🎭
    emoji that duplicated the dress-theme chip's own 🎭 a few chips over,
    which made a guest arriving from the flyer read it as just another
    logistics pill instead of the title of what they are attending.
    """
    theme_name = html.escape(getattr(config, "EVENT_THEME", "") or "")
    theme_html = (
        f'<span class="event-strip-theme">🎭 {theme_name} Theme</span>' if theme_name else ""
    )
    subtitle = html.escape(getattr(config, "EVENT_SUBTITLE", "") or "")
    title_html = f'<div class="event-strip-title">{subtitle}</div>' if subtitle else ""
    return (
        f'{title_html}'
        '<div class="event-strip">'
        f'<span class="event-strip-date">📅 {html.escape(config.EVENT_DATE_SHORT)}'
        f' · {html.escape(config.EVENT_TIME_TEXT)}</span>'
        f'<span class="event-strip-venue">📍 {html.escape(config.VENUE_NAME)}, {html.escape(config.VENUE_ADDRESS)}</span>'
        f'{theme_html}'
        '</div>'
    )


_STAT_ACCENTS = {"gold", "ok", "warn", "err", "info", "rust", "turquoise"}


def stat_tiles(items: list) -> str:
    """A responsive CSS-grid of stat tiles with per-tile visual hierarchy.

    `items` is a list of dicts, each describing one tile:
        {
            "label": str,             # required
            "value": Any,             # required — stringified + escaped
            "caption": str = "",      # optional secondary line
            "icon": str = "",         # optional emoji shown beside the label
            "accent": str = "",       # one of _STAT_ACCENTS, or "" for neutral
            "emphasis": str = "normal",  # "hero" for the number(s) that matter most
        }

    `accent` is purely a styling hook onto the existing design tokens
    (--ok/--warn/--err/--info/--gold/--rust/--turquoise) — never a new raw
    color — and unrecognized values are dropped rather than interpolated, so
    a typo can't leak an arbitrary CSS class. A "hero" tile renders larger,
    with a tinted background, and spans two grid tracks so the operationally
    important numbers (e.g. Checked In vs Total Guests) visually lead the
    row instead of blending into a uniform grid of identical boxes; a hero
    tile with no explicit accent defaults to "gold" so it never looks flat.
    """
    tiles = []
    for item in items:
        label = item.get("label", "")
        value = item.get("value", "")
        caption = item.get("caption") or ""
        icon = item.get("icon") or ""
        emphasis = item.get("emphasis") or "normal"
        accent = item.get("accent") or ("gold" if emphasis == "hero" else "")
        if accent not in _STAT_ACCENTS:
            accent = ""

        classes = ["stat-tile"]
        if emphasis == "hero":
            classes.append("stat-tile-hero")
        if accent:
            classes.append(f"accent-{accent}")

        icon_html = f'<span class="stat-icon">{html.escape(icon)}</span>' if icon else ""
        cap_html = (
            f'<div class="stat-caption">{html.escape(str(caption))}</div>' if caption else ""
        )
        tiles.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="stat-label">{icon_html}<span>{html.escape(str(label))}</span></div>'
            f'<div class="stat-value">{html.escape(str(value))}</div>'
            f'{cap_html}'
            f'</div>'
        )
    return f'<div class="stat-grid">{"".join(tiles)}</div>'


def checkin_progress_meter(checked_in: int, total: int) -> str:
    """A labelled check-in progress meter, e.g. '6 of 13 checked in · 46%'.

    Replaces a bare st.progress() bar with a real progress element that
    states the counts in plain language rather than a lone percentage, and
    handles the zero-guests case (fresh install / just after a Danger Zone
    reset) without dividing by zero or drawing a meaningless empty bar.
    """
    checked_in = int(checked_in)
    total = int(total)

    if total <= 0:
        return (
            '<div class="progress-meter">'
            '<div class="progress-meter-track" role="progressbar" '
            'aria-valuenow="0" aria-valuemin="0" aria-valuemax="0" aria-label="Check-in progress">'
            '<div class="progress-meter-fill" style="width:0%;"></div></div>'
            '<div class="progress-meter-detail">No guests registered yet — the check-in rate '
            'will show up here once people sign up.</div>'
            '</div>'
        )

    pct = round(checked_in / total * 100, 1)
    pct_display = int(pct) if pct == int(pct) else pct
    pct_clamped = max(0.0, min(100.0, pct))
    return (
        '<div class="progress-meter">'
        f'<div class="progress-meter-track" role="progressbar" '
        f'aria-valuenow="{checked_in}" aria-valuemin="0" aria-valuemax="{total}" '
        f'aria-label="Check-in progress">'
        f'<div class="progress-meter-fill" style="width:{pct_clamped}%;"></div></div>'
        f'<div class="progress-meter-detail">{checked_in} of {total} checked in · {pct_display}%</div>'
        '</div>'
    )


# Below this many tickets left, the remaining-tickets meter switches to the
# warning accent — "8 left" should not look as calm as "180 left".
TICKETS_LOW_THRESHOLD = 25


def tickets_remaining(availability: dict, context: str = "") -> str:
    """A meter showing how many tickets are still available.

    `availability` is a utils.ticket_availability() payload. Returns an empty
    string when the cap is disabled (`unlimited`), so callers can render this
    unconditionally and get nothing when there is no cap to report.

    Colour follows scarcity: gold normally, warn under TICKETS_LOW_THRESHOLD,
    err at zero. `context` replaces the default note under the bar.
    """
    if not availability or availability.get("unlimited"):
        return ""

    cap = max(0, int(availability.get("cap", 0)))
    if cap <= 0:
        return ""
    remaining = max(0, int(availability.get("remaining", 0)))
    sold = max(0, min(cap, int(availability.get("sold", 0))))

    if remaining <= 0:
        state, note = "is-out", "Every ticket has been claimed."
    elif remaining <= TICKETS_LOW_THRESHOLD:
        state, note = "is-low", "Almost gone — register soon to be sure of your spot."
    else:
        state, note = "", "Tickets are first come, first served."
    if context:
        note = context

    plural = "s" if remaining != 1 else ""
    filled = round(sold / cap * 100, 1) if cap else 0.0
    return (
        f'<div class="tickets-left {state}">'
        '<div class="tickets-left-head">'
        f'<span class="tickets-left-count">🎟️ <strong>{remaining}</strong> ticket{plural} left</span>'
        f'<span class="tickets-left-of">{sold} of {cap} claimed</span>'
        '</div>'
        f'<div class="tickets-left-track" role="progressbar" aria-valuenow="{sold}" '
        f'aria-valuemin="0" aria-valuemax="{cap}" aria-label="Tickets claimed">'
        f'<div class="tickets-left-fill" style="width:{filled}%;"></div></div>'
        f'<div class="tickets-left-note">{html.escape(note)}</div>'
        '</div>'
    )


def sold_out_notice(message: str) -> str:
    """The notice shown in place of the Register form once the cap is hit.

    `message` is utils.SOLD_OUT_MESSAGE — kept in utils rather than inlined
    here so the same wording covers both this screen and the refusal a guest
    hits if the last ticket goes while their form is open.
    """
    return f"""
    <div class="sold-out-notice">
        <div class="sold-out-icon">🎟️</div>
        <div class="sold-out-title">Sold out — every ticket is claimed</div>
        <div class="sold-out-message">{html.escape(message)}</div>
    </div>
    """


SEATS_UNAVAILABLE_MESSAGE = (
    "We can't load seat availability right now — this is a temporary hiccup on our "
    "end, not a sold-out event. Nothing is wrong with your payment or booking. "
    "Please try again in a few minutes."
)


def seats_unavailable_notice(message: str = "") -> str:
    """The notice shown in place of the Register form when seat availability
    can't be determined right now (e.g. utils.seat_availability() reports
    `unavailable=True` because the database is unreachable).

    Deliberately NOT sold_out_notice(): this is an outage, not a sell-out, so
    it must never say "sold out" — that exact confusion (a transient DB blip
    rendering as "every ticket is claimed") is the bug this notice exists to
    fix. Reuses closed_notice()'s informational styling (`.closed-notice`,
    `--info-bg`/`--info-border`) rather than sold_out_notice()'s error-red
    palette, matching the calmer, "come back shortly" tone of that copy
    rather than an alarming one.

    The caller must render this INSTEAD of the seat picker and form, not
    alongside them: with availability unknown, nobody can say which seats
    are actually free, so letting a guest pick and pay here risks a
    double-booking that only the (working) database could have caught.
    """
    return f"""
    <div class="closed-notice">
        <div class="closed-notice-icon">🔌</div>
        <div class="closed-notice-title">Seat availability is temporarily unavailable</div>
        <div class="closed-notice-message">{html.escape(message or SEATS_UNAVAILABLE_MESSAGE)}</div>
    </div>
    """


def empty_state(icon: str, title: str, message: str) -> str:
    """A friendly placeholder for an otherwise-empty section.

    Used so a fresh install or a just-reset dashboard reads as "nothing here
    yet" rather than "something is broken".
    """
    return (
        '<div class="empty-state">'
        f'<div class="empty-state-icon">{html.escape(icon)}</div>'
        f'<div class="empty-state-title">{html.escape(title)}</div>'
        f'<div class="empty-state-message">{html.escape(message)}</div>'
        '</div>'
    )


def section_header(title: str, subtitle: str = "") -> str:
    """A section heading with an optional dimmer subtitle line beneath it."""
    sub_html = f'<p class="section-subtitle">{html.escape(subtitle)}</p>' if subtitle else ""
    return f'<div class="section-header"><h3>{html.escape(title)}</h3>{sub_html}</div>'


def nav_card(icon: str, title: str, desc: str) -> str:
    """The card body for a home-page navigation tile. Pair with an st.button below it."""
    return (
        '<div class="nav-card">'
        f'<h3>{html.escape(icon)} {html.escape(title)}</h3>'
        f'<p>{html.escape(desc)}</p>'
        '</div>'
    )


def flyer_card(src: str, alt: str = "", caption: str = "") -> str:
    """The event flyer, framed, or "" when there isn't one configured.

    Height-capped rather than width-capped: the flyer is a tall portrait
    poster, and left to fill a desktop column it would push everything below
    it off the screen. Capping the height keeps it a glance, not a wall.

    `caption`, when given, renders as a short line under the poster tying it
    to the event (e.g. the event name and date) — optional so the Register
    page's collapsed-expander flyer can render without one. Must still
    return "" for a blank `src` regardless of `caption`, so a caller can
    build a caption unconditionally and rely on this to drop it along with
    everything else when there's no flyer configured.
    """
    src = (src or "").strip()
    if not src:
        return ""
    alt = alt or f"{config.EVENT_NAME} event flyer"
    caption = (caption or "").strip()
    caption_html = f'<div class="flyer-caption">{html.escape(caption)}</div>' if caption else ""
    return (
        '<div class="flyer-card">'
        f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}" loading="lazy">'
        f'{caption_html}'
        "</div>"
    )


def photo_gallery(photos: list) -> str:
    """A responsive grid of event photos, or "" when there are none.

    `photos` is a utils.gallery_photos() payload — a list of
    {"src", "caption"} dicts whose `src` is already resolved to a usable
    https URL or data URI. Returns "" for an empty list so the caller can
    decide between a placeholder and rendering nothing at all.
    """
    if not photos:
        return ""

    cards = []
    for photo in photos:
        src = photo.get("src") or ""
        if not src:
            continue
        caption = str(photo.get("caption") or "").strip()
        # A caption doubles as the alt text — it's the only description of
        # the image anyone has written. With no caption the tile is
        # decorative, so an empty alt keeps screen readers from announcing
        # a meaningless filename.
        cap_html = f'<div class="photo-caption">{html.escape(caption)}</div>' if caption else ""
        cards.append(
            '<div class="photo-card">'
            f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(caption, quote=True)}" loading="lazy">'
            f"{cap_html}"
            "</div>"
        )
    if not cards:
        return ""
    return f'<div class="photo-grid">{"".join(cards)}</div>'


def _sponsor_card(sponsor: dict) -> str:
    """One sponsor card. Returns "" for an entry with no name to show."""
    name = str(sponsor.get("name") or "").strip()
    if not name:
        return ""

    logo = sponsor.get("logo") or ""
    blurb = str(sponsor.get("blurb") or "").strip()
    url = sponsor.get("url") or ""
    featured = bool(sponsor.get("featured"))

    inner = []
    if logo:
        inner.append(
            f'<img class="sponsor-logo" src="{html.escape(logo, quote=True)}" '
            f'alt="{html.escape(name, quote=True)} logo" loading="lazy">'
        )
    inner.append(f'<div class="sponsor-name">{html.escape(name)}</div>')
    if blurb:
        inner.append(f'<div class="sponsor-blurb">{html.escape(blurb)}</div>')
    body = "".join(inner)

    classes = "sponsor-card is-featured" if featured else "sponsor-card"
    if url:
        return (
            f'<a class="{classes}" href="{html.escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{body}</a>'
        )
    return f'<div class="{classes}">{body}</div>'


def sponsor_wall(sponsors: list) -> str:
    """The tiered sponsor wall, or "" when there are no sponsors.

    `sponsors` is a utils.sponsor_list() payload — already ordered best tier
    first, since which tier outranks which is a config question, not a
    rendering one. This walks that order and starts a new labelled section
    every time the tier changes, so the grouping can never disagree with the
    sort.

    The top tier's cards render larger (`featured`), which is the whole point
    of paying for it. A sponsor with a `url` becomes a link (new tab, with
    rel="noopener" so the sponsor's site gets no handle on this one); a
    missing logo is fine — the name is set in type instead.
    """
    if not sponsors:
        return ""

    sections = []
    current_tier = None
    cards = []
    featured_row = False

    def _flush():
        if not cards:
            return
        heading = (
            f'<div class="sponsor-tier-heading">{html.escape(current_tier)}</div>'
            if current_tier
            else ""
        )
        grid_class = "sponsor-grid is-featured-row" if featured_row else "sponsor-grid"
        sections.append(f'{heading}<div class="{grid_class}">{"".join(cards)}</div>')

    for sponsor in sponsors:
        card = _sponsor_card(sponsor)
        if not card:
            continue
        tier = str(sponsor.get("tier") or "").strip()
        if tier != current_tier and cards:
            _flush()
            cards = []
            featured_row = False
        current_tier = tier
        featured_row = featured_row or bool(sponsor.get("featured"))
        cards.append(card)
    _flush()

    if not sections:
        return ""
    return f'<div class="sponsor-wall">{"".join(sections)}</div>'


def registration_confirmation(
    name: str, email: str, tickets: int, guest_names: list,
    seat_numbers=None,
) -> str:
    """The "you're in" card shown at the top of Home right after a submit.

    Registration redirects to Home so the guest lands on the photos,
    sponsors, and party stats — but the confirmation has to travel with
    them, or a submit would look like it did nothing. Reads the booking
    back from what was actually saved so this doubles as the guest's last
    chance to spot a missing name — or a missing seat — before the door.

    The QR email is fire-and-forget (utils.send_qr_email_async), so the
    wording here says it is on its way, never that it arrived (see PART 1).

    `seat_numbers` is the guest's actual held seats (e.g. guest["seats"], a
    list of ints) — this is the guest's receipt, so it must say which seats
    they hold, in the venue-style labels (config.seat_label()) they picked
    on the seat map — not the raw stored integers. Omitted (or empty) skips
    the row, matching a legacy booking with no seat numbers on file.
    """
    try:
        tickets = int(tickets)
    except (TypeError, ValueError):
        tickets = 1
    guest_names = [str(n).strip() for n in (guest_names or []) if str(n).strip()]
    plural = "s" if tickets != 1 else ""

    seats = []
    for s in (seat_numbers or []):
        try:
            seats.append(int(s))
        except (TypeError, ValueError):
            continue
    seats = sorted(set(seats))

    rows = [
        ("Tickets", f"{tickets} ticket{plural}"),
        ("QR code emailed to", email or "—"),
    ]
    if seats:
        rows.insert(1, ("Seats", config.format_seat_labels(seats)))
    if guest_names:
        rows.append((f"Additional guests ({len(guest_names)})", ", ".join(guest_names)))
        rows.append(("On this booking", f"{len(guest_names) + 1} people, including you"))

    # Concatenated rather than an f-string block: a blank line inside the
    # HTML would end st.markdown's HTML block and dump the rest as text.
    parts = ['<div class="confirm-card">']
    parts.append('<div class="confirm-icon">🎉</div>')
    parts.append(f'<div class="confirm-title">You\'re in, {html.escape(str(name))}!</div>')
    parts.append(
        '<div class="confirm-message">Your QR code is on its way to '
        f"<strong>{html.escape(str(email))}</strong> — check your inbox (and spam folder) in a "
        "few minutes. No need to screenshot anything; you can also pull it up again from "
        "<strong>My QR Code</strong> below at any time.</div>"
    )
    parts.append('<div class="confirm-rows">')
    for label, value in rows:
        parts.append(
            '<div class="confirm-row">'
            f'<span class="confirm-label">{html.escape(label)}</span>'
            f'<span class="confirm-value">{html.escape(str(value))}</span>'
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def tier_range_label(tier: dict) -> str:
    """Human label for one price tier's ticket range, e.g. "11–21" or "22+"."""
    low = int(tier.get("min", 1))
    high = tier.get("max")
    if high is None:
        return f"{low}+"
    high = int(high)
    if high <= low:
        return str(low)
    return f"{low}–{high}"


def price_tier_table(tiers: list, ticket_count: int = 0, total_cents: int = None) -> str:
    """The seat-price table, shown inside the payment card.

    `tiers` is a config.price_tiers() payload. `ticket_count` highlights the
    row the current selection falls into — the point of showing the whole
    table on the form is that a guest can see both what they're paying and
    what one more seat would get them, so the row they're on has to be
    unmistakable.

    Each seat is priced individually (see config.booking_total_cents) — this
    is NOT a per-booking group-discount rate, so the copy must never read as
    "N tickets cost $X each" (that reads as N × $X, which is wrong). When
    `total_cents` is given and `ticket_count` is at least 1, a footer row is
    appended showing the real amount to send, so this table can't be
    misread as the total on its own.
    """
    if not tiers:
        return ""

    try:
        count = int(ticket_count)
    except (TypeError, ValueError):
        count = 0

    rows = []
    for tier in tiers:
        low = int(tier.get("min", 1))
        high = tier.get("max")
        active = count >= low and (high is None or count <= int(high))
        price = int(tier.get("price_cents", 0)) / 100
        rows.append(
            f'<div class="tier-row{" is-active" if active else ""}">'
            f'<span class="tier-range">Seats {html.escape(tier_range_label(tier))}</span>'
            f'<span class="tier-price">${price:,.2f} <span class="tier-each">per seat</span></span>'
            "</div>"
        )

    total_html = ""
    if total_cents is not None and count >= 1:
        try:
            total = int(total_cents) / 100
        except (TypeError, ValueError):
            total = None
        if total is not None:
            plural = "s" if count != 1 else ""
            total_html = (
                '<div class="tier-total">'
                f'<span>Your {count} seat{plural}</span>'
                f'<span>${total:,.2f} to send</span>'
                "</div>"
            )

    return (
        '<div class="tier-table">'
        '<div class="tier-table-head">🎟️ Seat pricing — every seat has its own price, '
        "and your total is the sum of the seats you take</div>"
        f'{"".join(rows)}'
        f"{total_html}"
        "</div>"
    )


def payment_card(zelle_info: str, tiers: list, ticket_count: int = 0, total_cents: int = None) -> str:
    """The Zelle payment instructions card shown on the Register page.

    Carries the full seat-price table rather than a single price, because
    this card sits ABOVE the ticket selector: at the point a guest reads it
    they haven't necessarily settled on a quantity yet, and showing every
    tier lets the price influence that choice. When `total_cents` is given,
    price_tier_table() also appends the exact amount to send for
    `ticket_count` seats, so a guest who pays right from this card — without
    scrolling down to total_card() below the selector — still sees the real
    total rather than a per-seat rate they might multiply themselves.

    The kids-free / food-at-venue facts used to be a couple of sentences
    tacked onto the end of this paragraph, where they were easy to skim
    past. They now live in their own chips next to the seat picker (see
    seat_policy_chips()) instead — this card stays focused on the Zelle
    mechanics.
    """
    return f"""
    <div class="payment-card">
        <div class="payment-card-head">
            <span class="payment-icon">💳</span>
            <span class="payment-title">Step 1: Pay via Zelle</span>
        </div>
        <p class="payment-desc">
            Send the <strong>exact total shown below</strong> via Zelle in your banking app —
            seats are priced individually, so the total is not one seat's price times your count.
            You'll need the <strong>transaction confirmation number</strong> on the next step.
        </p>
        <div class="zelle-box">
            <div class="zelle-label">Send Zelle To</div>
            <div class="zelle-email">{html.escape(zelle_info)}</div>
        </div>
        {price_tier_table(tiers, ticket_count, total_cents)}
    </div>
    """


def seat_policy_chips() -> str:
    """Two facts a guest choosing seats must not miss: kids under 12 are
    free, and food is available for purchase at the venue.

    Both strings live once in config.py (KIDS_POLICY_TEXT / FOOD_POLICY_TEXT)
    so this file never hand-types event policy — see the VENUE_* constants
    venue_info_card() reads for the same rule. Rendered as its own small
    chip row next to the seat picker rather than folded into payment_card()'s
    prose, which a guest focused on picking seats could skim right past.
    """
    kids = html.escape(config.KIDS_POLICY_TEXT)
    food = html.escape(config.FOOD_POLICY_TEXT)
    return (
        '<div class="policy-chip-row">'
        f'<div class="policy-chip"><span class="policy-chip-icon">🧒</span><span>{kids}</span></div>'
        f'<div class="policy-chip"><span class="policy-chip-icon">🍽️</span><span>{food}</span></div>'
        '</div>'
    )


def total_card(tickets: int, total_cents: int) -> str:
    """The live-updating 'Total to Pay' card on the Register page.

    `total_cents` is the exact amount to Zelle for the selected seats. There
    is no savings/discount line: seats are picked individually now (see
    config.seats_total_cents), so a guest's total is simply the sum of the
    specific seats they hold — there is no "vs base price" comparison that
    means anything for an arbitrary pick, and no screen may claim a discount
    that isn't real.
    """
    tickets = int(tickets)
    total = total_cents / 100
    plural = "s" if tickets != 1 else ""
    return f"""
    <div class="total-card">
        <div class="total-label">Total to Pay</div>
        <div class="total-value">${total:,.2f}</div>
        <div class="total-caption">{tickets} seat{plural} selected</div>
    </div>
    """


def next_tier_nudge(ticket_count: int, tier: dict, base_price_cents: int) -> str:
    """"Seat N costs less" — or "" if already on the cheapest tier.

    `tier` is a config.next_price_tier() payload (None when the booking is
    already on the best tier). Shown under the total.
    """
    if not tier:
        return ""
    try:
        count = int(ticket_count)
        next_seat = int(tier["min"])
        tier_price = int(tier["price_cents"]) / 100
    except (TypeError, ValueError, KeyError):
        return ""
    if next_seat <= count:
        return ""

    return (
        '<div class="tier-nudge">'
        "<span class=\"tier-nudge-icon\">💡</span>"
        f"<span>Seat <strong>{next_seat}</strong> and above cost "
        f"<strong>${tier_price:,.2f}</strong> per seat. "
        "Everyone coming needs their own ticket and their name below.</span>"
        "</div>"
    )


def seat_map(selected=(), taken=(), max_seats: int = None) -> str:
    """Visual sanctuary-style seat map: every seat renders in exactly one of
    three states — TAKEN (already booked by someone else), SELECTED (this
    guest's own pick), or AVAILABLE (tier-coloured, open to pick).

    `selected` is the seat numbers this guest currently has chosen;
    `taken` is every seat number already sold to someone else (see
    utils.seat_availability()). `max_seats` defaults to config.TOTAL_SEATS.
    Seats are colour-coded by price tier via config.seat_tier_index(), so the
    map can never drift from config.SEAT_TIERS. The map is purely visual —
    the actual selection happens via the multiselect above it.

    Each row starts with a row-letter gutter (config.seat_row_label()) so the
    grid reads like a real venue seating chart, and every seat cell shows its
    full venue-style label (config.seat_label(), e.g. "B7") rather than the
    bare stored integer — that raw integer stays the DB/internal identity,
    this is display only.

    A seat can never render as both taken and selected: if the two sets
    somehow overlap (e.g. a stale selection the caller hasn't pruned yet),
    TAKEN wins — real inventory outranks a page that hasn't caught up yet.
    """
    import config as _config

    if max_seats is None:
        max_seats = _config.TOTAL_SEATS
    try:
        max_seats = int(max_seats)
    except (TypeError, ValueError):
        max_seats = _config.TOTAL_SEATS
    max_seats = max(0, max_seats)

    def _clean(values):
        cleaned = set()
        for v in values or ():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= max_seats:
                cleaned.add(n)
        return cleaned

    taken_set = _clean(taken)
    selected_set = _clean(selected) - taken_set

    tier_colors = ["gold", "tan", "turquoise"]

    cols = getattr(_config, "SEAT_COLS", 10) or 10
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        cols = 10
    cols = max(1, cols)
    rows = (max_seats + cols - 1) // cols
    cells = []
    for seat in range(1, max_seats + 1):
        label = html.escape(_config.seat_label(seat))
        tier_idx = _config.seat_tier_index(seat)
        cls = tier_colors[tier_idx % len(tier_colors)] if tier_idx >= 0 else ""
        # Add an aisle gap between columns 5 and 6.
        aisle = " aisle" if seat % cols == 5 else ""
        if seat in taken_set:
            cells.append(
                f'<div class="seat seat-taken{aisle}" '
                f'aria-label="Seat {label} — already booked" '
                f'title="Seat {label} — already booked"><span>{label}</span></div>'
            )
        elif seat in selected_set:
            cells.append(
                f'<div class="seat seat-{cls} selected{aisle}" '
                f'aria-label="Seat {label} — your seat" '
                f'title="Seat {label} — selected"><span>{label}</span></div>'
            )
        else:
            price = _config.seat_price_cents(seat) / 100
            cells.append(
                f'<div class="seat seat-{cls}{aisle}" '
                f'aria-label="Seat {label} — ${price:,.2f}, available" '
                f'title="Seat {label} — ${price:,.2f}"><span>{label}</span></div>'
            )

    grid = "\n".join(
        '<div class="seat-row">'
        f'<div class="seat-row-label">{html.escape(_config.seat_row_label(r))}</div>'
        + "".join(cells[r * cols:(r + 1) * cols]) + "</div>"
        for r in range(rows)
    )

    legend_items = []
    for idx, (start, end, price) in enumerate(_config.SEAT_TIERS):
        cls = tier_colors[idx % len(tier_colors)]
        label = f"Seats {start}–{end}" if end <= max_seats else f"Seats {start}+"
        legend_items.append(
            f'<div class="seat-legend-item">'
            f'<div class="seat-dot seat-{cls}"></div>'
            f'<span>{label}: ${price / 100:,.2f}</span>'
            f'</div>'
        )
    legend_items.append(
        '<div class="seat-legend-item">'
        '<div class="seat-dot seat-taken"></div>'
        '<span>Taken</span>'
        '</div>'
    )

    still_available = max(0, max_seats - len(taken_set) - len(selected_set))
    plural = "s" if len(selected_set) != 1 else ""

    return f"""
    <div class="seat-map-wrap">
        <div class="seat-screen">🙏 Altar</div>
        <div class="seat-grid">{grid}</div>
        <div class="seat-legend">{''.join(legend_items)}</div>
        <div class="seat-count">{len(selected_set)} seat{plural} selected · {still_available} still available</div>
        <div class="seat-note">
            These seats are <strong>reserved to your booking</strong> once you submit — greyed-out
            seats are already booked by someone else. Choose any open seat.
        </div>
    </div>
    """


def seat_breakdown(selected) -> str:
    """Human breakdown of the guest's ACTUAL picked seats, grouped by tier.

    `selected` is an arbitrary, possibly non-contiguous set of seat numbers
    (e.g. [1, 2, 90]) — seats are individually picked now, not just the
    first N, so this groups by which tier each picked seat actually falls
    in rather than assuming seats 1..N. The tier range is shown in
    venue-style labels (config.seat_label()), matching what the seat map and
    multiselect show, e.g. "2 seats in A1–C5 · $100.00" rather than the raw
    "1–25" a guest would have to translate themselves.
    """
    import config as _config

    cleaned = set()
    try:
        candidates = list(selected or [])
    except TypeError:
        candidates = []
    for seat in candidates:
        try:
            n = int(seat)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= _config.TOTAL_SEATS:
            cleaned.add(n)

    lines = []
    for start, end, price in _config.SEAT_TIERS:
        seats_in_tier = [s for s in cleaned if start <= s <= end]
        if not seats_in_tier:
            continue
        subtotal = len(seats_in_tier) * price
        range_label = f"{_config.seat_label(start)}–{_config.seat_label(end)}"
        lines.append(
            f'<div class="breakdown-line">'
            f'<span>{len(seats_in_tier)} seat{"s" if len(seats_in_tier) != 1 else ""} '
            f'in {html.escape(range_label)}:</span>'
            f'<span>${subtotal / 100:,.2f}</span>'
            f'</div>'
        )
    return f'<div class="seat-breakdown">{"".join(lines)}</div>' if lines else ""


def guest_names_requirement(ticket_count: int, provided: int = 0) -> str:
    """The live note telling the guest how many names their tickets need.

    `ticket_count` is the current value of the Register page's ticket
    selector (which lives outside the form, so changing it re-renders this);
    `provided` is how many names are currently saved for the booking, used
    only to show progress after a failed submit — a fresh form passes 0.

    One ticket per person means a booking of N tickets is the registrant plus
    N-1 named guests, which is exactly what utils.validate_registration
    enforces. Stating it here, in the same words and before the field, is the
    difference between a guest who fills it in correctly and one who submits
    and gets an error.
    """
    tickets = int(ticket_count)
    needed = max(tickets - 1, 0)

    if needed == 0:
        return (
            '<div class="guest-req is-solo">'
            '<span class="guest-req-icon">🎟️</span>'
            "<span>Just you on this booking — no other names needed. "
            "Bringing someone? Add a ticket for each person above.</span>"
            "</div>"
        )

    people_word = "guest" if needed == 1 else "guests"
    name_word = "name" if needed == 1 else "names"
    progress = f" You've entered {int(provided)} so far." if provided else ""
    return (
        '<div class="guest-req">'
        '<span class="guest-req-icon">👥</span>'
        f"<span>{tickets} tickets covers <strong>you plus "
        f'<span class="guest-req-count">{needed}</span> other {people_word}</strong> — '
        f"please enter their {name_word} below, one per line.{html.escape(progress)}</span>"
        "</div>"
    )


def venue_info_card() -> str:
    """A compact venue info card for the Register page.

    Covers parking, arrival time, and house rules so guests have the key
    logistical details before they complete registration. All copy comes
    from config.py (VENUE_PARKING_TEXT / VENUE_DOORS_TEXT /
    VENUE_HOUSE_RULE_TEXT) so venue-specific wording lives in one place and
    VENUE_NAME itself appears only once in the codebase.
    """
    return f"""
    <div class="venue-info-card">
        <div class="venue-info-head">
            <span class="venue-info-icon">📍</span>
            <span class="venue-info-title">Venue &amp; Arrival Info</span>
        </div>
        <div class="venue-info-row">
            <span class="venue-info-label">Location</span>
            <span class="venue-info-value">{html.escape(config.VENUE_NAME)}, {html.escape(config.VENUE_ADDRESS)}</span>
        </div>
        <div class="venue-info-row">
            <span class="venue-info-label">Parking</span>
            <span class="venue-info-value">{html.escape(config.VENUE_PARKING_TEXT)}</span>
        </div>
        <div class="venue-info-row">
            <span class="venue-info-label">Doors</span>
            <span class="venue-info-value">{html.escape(config.VENUE_DOORS_TEXT)}</span>
        </div>
        <div class="venue-info-row">
            <span class="venue-info-label">House rule</span>
            <span class="venue-info-value">{html.escape(config.VENUE_HOUSE_RULE_TEXT)}</span>
        </div>
    </div>
    """


def terms_and_conditions_html() -> str:
    """The Terms & Conditions / participation waiver shown on the Register
    page, inside a collapsible expander directly above the "I/We Agree"
    checkbox.

    Deliberately GENERIC. An earlier version of this text was a party-template
    alcohol/BYOB disclaimer, which is wrong for a devotional Yakshagana
    performance at a spiritual centre (config.VENUE_NAME) and a bad look for
    the organiser. This waiver names no specific substance or activity: it
    covers assumption of risk, release/indemnity (including travel to and
    from the venue, and negligence), responsibility for minors, consent to
    emergency medical treatment, photo/video consent, and a general
    undertaking to follow the venue's house rules. Keep it that way — house
    rules belong to the venue, not to this form.

    Pulled out of streamlit_app.py so the copy is unit-testable without a
    Streamlit runtime, per AGENTS.md ("theme.py: all CSS and HTML component
    builders"). Every interpolated config value is html.escape()'d.
    """
    event_title = f"{html.escape(config.EVENT_NAME)} on {html.escape(config.EVENT_DATE_TEXT)}"
    organizers = html.escape(config.EVENT_NAME)
    venue = html.escape(config.VENUE_NAME)
    return f"""
    <div style='color: rgba(245,245,245,0.85); font-size: 0.88rem; line-height: 1.5;'>
        <h4 style='color: #F4E4BC; margin-top: 0;'>Participation Waiver</h4>
        <p>
            I (Individual) or We (for all the listed attendees in this form and/or a person who is making group Zelle payment representing the group) the undersigned, hereby voluntarily assume all risks associated with participating in the activities related to the <strong>{event_title}</strong> at {venue}.
        </p>
        <p>
            In consideration of being allowed to participate, I/We hereby release and discharge the {organizers} organizers, their owners, employees, volunteers, and representatives, as well as {venue} and its staff and representatives, from any and all liability for injuries, losses, or damages arising before, during, or after the event — including travel to and from the venue. I/We further agree to indemnify and hold them harmless from any claims arising from my/our participation. This waiver includes, but is not limited to, liability arising from negligence.
        </p>
        <p>
            I/We acknowledge that I am/we are solely responsible for supervising any minors in my/our party at all times during the event.
        </p>
        <p>
            I/We consent to receiving emergency medical treatment deemed necessary in case of injury, accident, or illness during the event.
        </p>
        <p>
            I/We acknowledge that I/We may be photographed or filmed during the event, and I/We grant permission for my/our likeness to be used by the event organizers and sponsors for event-related and promotional purposes without compensation.
        </p>
        <p>
            I/We agree to follow all venue house rules and the directions of the organizers and venue staff at all times, including that the building must be cleared by the posted time.
        </p>
        <p>
            By selecting <strong>"I/We Agree"</strong> below, I/We certify that I/We have read and understood this waiver and release of liability. I/We voluntarily agree to its terms and confirm that my/our participation is entirely voluntary.
        </p>
    </div>
    """


def stepper(current_step: int, steps: list = None) -> str:
    """A horizontal progress stepper. `current_step` is 1-indexed."""
    steps = steps or ["Pay via Zelle", "Your Details", "Confirmation"]
    parts = []
    for i, label in enumerate(steps, start=1):
        if i < current_step:
            state = "step-done"
        elif i == current_step:
            state = "step-active"
        else:
            state = ""
        parts.append(
            f'<div class="step {state}">'
            f'<span class="step-num">{i}</span>'
            f'<span class="step-label">{html.escape(label)}</span>'
            f'</div>'
        )
    return f'<div class="stepper">{"".join(parts)}</div>'


def field_error(msg: str) -> str:
    """A small error line meant to render directly under a form field."""
    return f'<p class="field-error">⚠ {html.escape(msg)}</p>'


def validation_banner(error_count: int) -> str:
    """An error banner shown above the registration form when validation fails.

    `error_count` is len(errors) from utils.validate_registration — used to
    pluralize "field(s)" correctly. Per-field messages still render under
    each field via field_error(); this banner is the at-a-glance summary.
    """
    error_count = int(error_count)
    field_word = "field" if error_count == 1 else "fields"
    return (
        '<div class="validation-banner">'
        f'⚠️ Couldn’t submit — please fix the {error_count} highlighted {field_word} below.'
        '</div>'
    )


def closed_notice(message: str) -> str:
    """A friendly notice shown on the Scanner page when check-in isn't open yet.

    Replaces the camera + manual-entry inputs entirely (there's nothing
    useful for a guest to do with them while the window is closed).
    """
    return f"""
    <div class="closed-notice">
        <div class="closed-notice-icon">🕒</div>
        <div class="closed-notice-title">Check-in isn't open yet</div>
        <div class="closed-notice-message">{html.escape(message)}</div>
    </div>
    """


def checkin_window_banner(is_open: bool, detail: str = "") -> str:
    """A prominent banner showing the current check-in gate status (admin)."""
    css_class = "status-ok" if is_open else "status-warn"
    icon = "🟢" if is_open else "🔒"
    label = "OPEN" if is_open else "CLOSED"
    detail_html = f" — {html.escape(detail)}" if detail else ""
    return (
        f'<div class="checkin-window-banner {css_class}">'
        f'<span class="checkin-window-icon">{icon}</span>'
        f'<span>Check-in is <strong>{label}</strong>{detail_html}</span>'
        '</div>'
    )


def capacity_full_page() -> str:
    """The friendly full-page "we're at capacity" screen (capacity guard).

    Shown instead of the whole app when too many sessions are active at
    once. Deliberately warm and party-themed, never server/error-flavored —
    the owner's ask was that anyone turned away should feel like the party
    is popular, not that something broke. Pair with an st.button("Retry")
    below this in the caller; HTML markup alone can't submit a rerun.

    Note this deliberately does NOT promise that a spot is being held. Tickets
    are capped (config.max_total_tickets()) and genuinely first come, first
    served, so a guest bounced off this screen must not be told to relax —
    only that nothing they've already completed is at risk.
    """
    return f"""
    <div class="capacity-page">
        <div class="capacity-page-icon">🎉</div>
        <div class="capacity-page-title">Whoa — lots of people checking this out right now!</div>
        <div class="capacity-page-message">
            So many guests are on the site at once that we're asking new visitors to hang back
            for just a moment so it stays fast for everyone.
            <br><br>
            <strong>Anything you've already done is safe</strong> — registrations and check-ins
            that went through are saved, and nothing is lost by waiting here.
            <br><br>
            Tickets are limited and go first come, first served, so try again in a moment —
            it'll be quick.
        </div>
    </div>
    """


def busy_banner() -> str:
    """A small, non-blocking banner shown when load is elevated but not yet
    at the hard capacity limit — the visitor gets through, just forewarned."""
    return (
        '<div class="busy-banner">'
        '🚦 Busier than usual right now — pages may take a little longer to load. Thanks for your patience!'
        '</div>'
    )


def footer() -> str:
    """The small centered app footer line."""
    return (
        '<p class="app-footer">'
        f'{html.escape(config.EVENT_NAME)} {config.EVENT_DATE.year} • '
        f'{html.escape(config.EVENT_TAGLINE)} • v{html.escape(config.APP_VERSION)}'
        '</p>'
    )


def guest_result_card(name: str, tickets, status: str, message: str = "") -> str:
    """A result card for scanner check-ins.

    `status` is one of "success", "already", "error" — mapped to ok/warn/err
    styling and a status label. `tickets` may be None when no guest was found.
    """
    status_map = {
        "success": ("status-ok", "✅ Checked In"),
        "already": ("status-warn", "⚠ Already Checked In"),
        "error": ("status-err", "❌ Not Found"),
    }
    css_class, label = status_map.get(status, ("status-ok", html.escape(status)))

    # Built via concatenation (not a multi-line f-string) so that an empty
    # optional piece (tickets=None, message="") never leaves a blank line in
    # the middle of the output. st.markdown's HTML-block parsing treats a
    # blank line as the end of the block, which would dump everything after
    # it back out as a literal, unrendered code block.
    parts = [f'<div class="guest-result-card {css_class}">']
    parts.append(f'<div class="guest-result-name">{html.escape(str(name))}</div>')
    if tickets is not None:
        tickets = int(tickets)
        plural = "s" if tickets != 1 else ""
        parts.append(f'<div class="guest-result-meta">{tickets} ticket{plural}</div>')
    parts.append(f'<div class="guest-result-status">{label}</div>')
    if message:
        parts.append(f'<div class="guest-result-message">{html.escape(message)}</div>')
    parts.append("</div>")
    return "".join(parts)


def guest_identity_card(guest: dict, bands: int, status_label: str, status: str = "found") -> str:
    """The "is this you?" card the Scanner shows before anyone is checked in.

    Door staff search by phone (guests often can't remember which email
    address their QR code went to), so the match has to be confirmed against
    a person, not just a number: every identifying field is listed —  name,
    email, phone — alongside what the booking is owed, tickets and the
    wristbands that go with them.

    `status` styles the card ("found" / "already" / "done") and
    `status_label` is the line staff read, e.g. "Not checked in yet".
    """
    status_map = {
        "found": "status-ok",
        "already": "status-warn",
        "done": "status-ok",
    }
    css_class = status_map.get(status, "status-ok")

    try:
        tickets = int(guest.get("ticket_count") or 1)
    except (TypeError, ValueError):
        tickets = 1

    # Door staff need the seat numbers themselves, not just a count — that's
    # the whole point of a seat being reserved. They're read aloud to
    # confirm a guest, so they render in the venue-style label
    # (config.seat_label(), e.g. "B7") a guest actually knows, not the raw
    # stored integer. Legacy rows registered before seat-picking existed
    # carry no seat numbers; say so rather than showing a blank.
    seats = sorted(int(s) for s in (guest.get("seats") or []))
    seats_value = config.format_seat_labels(seats) if seats else "— (no seats on file)"

    rows = [
        ("Email", guest.get("email") or "—", False),
        ("Phone", guest.get("phone") or "— (registered before phone was required)", False),
        ("Tickets", str(tickets), True),
        ("Seats", seats_value, True),
        ("Wristbands", str(bands), True),
    ]

    # Names are collected at registration, one per ticket beyond the booker
    # (see utils.additional_guests_expected), so door staff can read the
    # whole party off this card. Bookings made before names were required
    # can still be short — say so plainly rather than silently listing
    # fewer people than are standing there.
    extra_names = [n for n in (guest.get("plus_one_name") or "").split("\n") if n.strip()]
    expected = max(tickets - 1, 0)
    if extra_names or expected:
        label = f"Additional guests ({len(extra_names)} of {expected})"
        value = ", ".join(extra_names) if extra_names else "— none on file"
        rows.append((label, value, False))

    # Concatenated for the same reason as guest_result_card() above: a blank
    # line inside the HTML block would end it and dump the rest as text.
    parts = [f'<div class="guest-result-card {css_class}">']
    parts.append(f'<div class="guest-result-name">{html.escape(str(guest.get("name") or "Unknown"))}</div>')
    parts.append(f'<div class="guest-result-status">{html.escape(status_label)}</div>')
    parts.append('<div class="guest-identity-rows">')
    for label, value, strong in rows:
        strong_class = " is-strong" if strong else ""
        parts.append(
            '<div class="guest-identity-row">'
            f'<span class="guest-identity-label">{html.escape(label)}</span>'
            f'<span class="guest-identity-value{strong_class}">{html.escape(str(value))}</span>'
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)
