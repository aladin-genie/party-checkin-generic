# Assets — photos & sponsor logos

Images shown on the **Home** page. Drop files in here, then list them in
`config.py` — nothing else needs to change.

```
assets/
  flyer.png   ← the event flyer   → config.EVENT_FLYER   (not added yet)
  photos/     ← event photos      → config.PHOTOS
  sponsors/   ← sponsor logos     → config.SPONSORS
```

## The two images to add first

These are the ones that make the biggest difference, and neither needs a code change:

| Save it as | What happens |
|---|---|
| `assets/flyer.png` | The flyer appears full-width on Home, and behind a "📜 See the party flyer" expander on Register. Nothing renders until this file exists. |
| `assets/photos/<your-photo>.jpg` | Add an entry to `config.PHOTOS` and the group shot joins the gallery. |

Any of the supported formats works; the `.png` / `.jpg` in the paths above just have to match
whatever you list in `config.py`.

## ⚠️ Everything in here right now is a placeholder

The files currently committed are **generated stand-ins**, not real photos or
real sponsor artwork. They are stamped `PLACEHOLDER` / `SAMPLE LOGO — NOT A
REAL SPONSOR` on the image itself, and the names in `config.py` are
deliberately generic ("Placeholder Top Sponsor"), so that nobody visiting the
site can mistake one for a genuine backer.

**Replace them before the registration link goes out.** Delete the stand-in
file, drop the real one in with the same name (or a better one), and update
the matching entry in `config.py`.

| Placeholder | Replace with |
|---|---|
| `photos/2016-the-first-crew.png` … `photos/2025-twelve-years-on.png` | The real team photos, oldest first |
| `sponsors/top-sponsor.png` | The headline sponsor's logo |
| `sponsors/gold-*.png`, `sponsors/silver-*.png` | Real logos for each tier |

## Sponsor tiers

`config.SPONSOR_TIERS` sets the display order — best first. The **first tier
in that tuple renders larger** (bigger logo, gold-washed card), which is the
prominence a headline sponsor is paying for:

```python
SPONSOR_TIERS = ("Top Sponsor", "Gold", "Silver", "Community")
```

A sponsor whose `tier` isn't in that tuple still gets a card — it just sorts
to the end under its own heading. Sponsors within a tier keep the order you
list them in, so put them in the order you want them seen.

## Adding a photo

1. Put the file in `assets/photos/`.
2. Add an entry to `PHOTOS` in `config.py`:

   ```python
   PHOTOS = [
       {"src": "assets/photos/2025-dance-floor.jpg", "caption": "2025 · the dance floor at 11pm"},
   ]
   ```

The caption is also used as the image's alt text, so write it for someone who
can't see the photo.

## Adding a sponsor

1. Put the logo in `assets/sponsors/` (a transparent PNG or an SVG looks best
   on the dark background).
2. Add an entry to `SPONSORS` in `config.py`:

   ```python
   SPONSORS = [
       {"name": "Acme Catering", "tier": "Gold", "logo": "assets/sponsors/acme.png",
        "url": "https://acme.example", "blurb": "Dinner is on them."},
   ]
   ```

Only `name` is required — a sponsor with no logo yet still gets a card with
their name set in type, so the lineup can go up before the artwork arrives.

## Rules worth knowing

- **Paths are relative to the repo root**, not to wherever the app is run
  from (`utils.resolve_image_src` resolves them against the project
  directory for exactly that reason).
- **A remote image must be `https://`.** Plain `http://` is dropped — it
  would be blocked as mixed content on the HTTPS deployment anyway.
- **Keep files under 3 MB** (`utils.MAX_INLINE_IMAGE_BYTES`) and resize
  before committing. Streamlit serves no static files, so every local image
  is base64-inlined into the page HTML and re-sent on each rerun; a folder of
  full-size phone photos will make the whole app feel slow. Around
  1200px wide is plenty.
- **Supported formats:** `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.svg`.
- Anything that can't be resolved — wrong path, unsupported extension,
  oversized — is **skipped**, not rendered as a broken tile. If a photo
  doesn't appear, check the app logs for the "skipping…" line.
- With both lists empty, Home shows a "coming soon" placeholder for each
  section rather than a gap.
