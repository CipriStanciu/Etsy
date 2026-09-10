# Fragrance Bot — recipe engine

Generates one unique, realistic, perfumery-safe DIY fragrance recipe per day
(deterministic per date), plus batch generation for seeding the recipe library.
This package is the foundation the image generator, PDF generator, Supabase
seed and Etsy listing all consume, so the emitted JSON schema is stable and
exactly matches the spec (see `fragbot/schema.py`).

**Zero third-party dependencies.** Standard library only; no network calls at
generation time; no paid services. Python 3.9+.

## Layout

```
fragbot/
├── fragbot/
│   ├── __init__.py        public API: generate_recipe, batch_generate
│   ├── __main__.py        `python -m fragbot ...` entry point
│   ├── cli.py             CLI: generate / batch
│   ├── generator.py       per-date recipe generation, blending, names, balance
│   ├── ingredients.py     category configs + DB loader
│   ├── pricing.py         difficulty, price rules (3.99-9.99), cost estimates
│   ├── schema.py          JSON schema validation (used at emit time too)
│   ├── seo.py             slug, full_title, 13 tags, long description
│   ├── themes.py          7-day themes, holiday windows, season bias
│   ├── data/
│   │   └── ingredients.json   ← CURATE THE INGREDIENT DATABASE HERE
│   ├── imagesgen/         listing image generator (PIL) — see its own
│   │                      section below
│   └── pdfgen/            recipe-card PDF generator (ReportLab) — see its
│                          own section below
├── examples/              3 sample recipes (perfume day, candle day, holiday day)
├── examples-images/       rendered 5-image sets for the examples (generated)
├── examples-pdfs/         rendered recipe-card PDFs for the examples (generated)
├── verify.py              engine self-test / verification script (55 checks)
├── verify_images.py       image-generator verification (output spec checks)
├── verify_pdfs.py         PDF-generator verification (output spec checks)
├── verification-output.txt      captured output of the last engine verify run
├── verification-images-output.txt  captured output of the last images verify run
├── verification-pdfs-output.txt   captured output of the last PDF verify run
├── fragbot/db.py          Supabase storage layer (Postgres / PostgREST / stub)
├── seed_recipes.py        seeds the recipe library (deterministic, idempotent)
├── verify_supabase.py     Supabase-layer verification (no live DB needed)
├── supabase/
│   └── schema.sql         table DDL (recipes + daily_posts) — paste in SQL editor
├── scripts/
│   └── pglite_bridge.cjs  dev-only: runs the DB checks against real Postgres
│                          (PGlite, WASM) — see "Verifying without a live DB"
├── pyproject.toml
└── requirements.txt       Pillow (images), ReportLab + pypdf (PDFs)
```

## Running

```bash
# one recipe for a date, pretty-printed to stdout (default: today)
python3 -m fragbot generate --date 2026-01-19

# save it to a file
python3 -m fragbot generate --date 2026-01-19 --out recipe.json

# batch: N consecutive recipes to a folder (the seeding path)
python3 -m fragbot generate --batch 365 --start 2026-01-01 --outdir seed_library

# repeat variants: R different recipes per date via the batch sequence number
# (deterministic: same date + same seq -> same recipe)
python3 -m fragbot generate --batch 30 --repeat 10 --start 2026-01-01 --outdir big_seed
```

As a library:

```python
from datetime import date
from fragbot import generate_recipe, batch_generate

recipe = generate_recipe(date(2026, 2, 11))   # deterministic per date
recipes = batch_generate(date(2026, 1, 1), 365)  # 365 unique recipes
```

## Verification

```bash
python3 verify.py          # exit 0 = PASS, non-zero = FAIL with details
```

Checks (spec rules): 30 consecutive daily recipes with unique name/slug/full
note profile; schema validity (all fields, tags exactly 13 and each ≤ 20 chars,
full_title ≤ 140 chars); price within 3.99–9.99 and matching
difficulty/weekend/holiday rules; 30/50/20 top/heart/base balance within ±5 pp
(recomputed from the emitted ingredient amounts, so it validates what the PDF
and listing would actually print); day-of-week category rotation incl. the
`solid_perfume` variant on every 4th perfume day; safety rules (no
skin-restricted oils in skin-contact products, ≤ 1 phototoxic citrus per skin
blend with warning note, ≤ 1 sensitizer-class oil per blend, coumarin warning);
holiday windows (Valentine's Feb 7–14, Mother's Day, Christmas Dec 18–26);
determinism (same date + same seq → identical JSON); carrier completeness.

## Recipe JSON schema

Exactly the fields below (plus the two sanctioned extensions `theme` and
`holiday`). `validate()` in `fragbot/schema.py` is the single source of truth:

- `recipe_name` — unique two-word luxury name (never reused within a 6400-recipe
  cycle ≈ 17.5 years; driven by a coprime stride over the date ordinal).
- `full_title` — ≤ 140 chars: `DIY <Name> <Category> Recipe | <Key Notes> | <Occasion> | Digital Download`
- `slug` — `<name>-diy-<category>-recipe`, URL-safe.
- `category` — `perfume | cologne | candle | reed_diffuser | room_spray | solid_perfume`
- `difficulty` — `beginner | intermediate | advanced`
- `scent_profile` — `{top_notes, heart_notes, base_notes}` (real note names)
- `ingredients` — `[{name, amount, purpose}]`; `purpose` ∈ `carrier|top|heart|base`;
  carrier(s) listed first; every oil is a real purchasable oil from the DB.
- `equipment`, `instructions`, `safety_notes` — lists of strings
- `yield`, `cost_to_make` (e.g. `~$4.50`), `price_usd` (float)
- `description_long` — SEO copy with the six spec sections
  (Hook / What You Get / Scent Profile / How It Works / Safety & Tips /
  Instant Download)
- `tags` — exactly 13, each ≤ 20 chars, category-aware
- `theme` — 7-day content theme; `holiday` — `null` or a named holiday

## Generation rules (owner's spec) — how they're implemented

1. **Balance** — every product has a defined number of blend "parts": perfume
   16 drops per 10 ml roller (~6%), cologne 14 drops, solid perfume 24 drops,
   room spray 40 drops, reed diffuser 50 parts = 25 ml oil in 75 ml carrier
   (25 %), candle 20 parts = 10 ml per 110 g soy wax (~8 % load). Parts are
   split 30/50/20 top/heart/base, so the ratio holds in drops *and* in ml.
2. **Safety** — all oils live in `fragbot/data/ingredients.json` with safety
   flags: `phototoxic` (citrus; allowed in skin blends but ≤ 1 per blend with a
   sun-exposure warning note), `skin_restricted` (clove bud, cinnamon bark,
   lemongrass — home fragrance products only, ≤ 1 per blend, with a "do not
   apply to skin" note), `max_parts` (ylang ylang ≤ 2 parts, tonka ≤ 1 part),
   `coumarin` (tonka warning note). No toxic/sensitizer combos are possible by
   construction, and the verifier re-checks every emitted blend. Usage rates
   are IFRA-sensible (see the per-category percentages above).
3. **Rotation** — perfume Mon/Wed/Fri, candle Tue, reed diffuser Thu,
   room spray Sat, cologne Sun; `solid_perfume` replaces every 4th perfume day.
4. **Names** — two-word luxury style from an 80×80 word bank, never reused.
5. **Themes** — Mon "Monday Mood" (citrus/fresh), Tue "Cozy Tuesday"
   (warm/spicy), Wed "Wellness Wednesday" (calming/lavender/chamomile),
   Thu "Date Night" (oud/vanilla), Fri "Friday Luxe" (premium oils),
   Sat "Weekend Project" (home scent), Sun "Sunday Reset" (clean).
6. **Holidays** — Valentine's (Feb 7–14, romantic floral), Christmas
   (Dec 18–26, spice/pine), Mother's Day (week before the 2nd Sunday of May,
   elegant floral). Holiday family pools take precedence and the sampling
   window is biased into them, with the daily theme rounding out the blend.
   Seasons add bias too: Jun–Aug fresh/citrus/coastal, Dec–Feb warm/woody/spicy.
7. **Pricing** — beginner $3.99 / intermediate $5.99 / advanced $7.99;
   Sat+Sun +$1.00; holiday +$2.00; capped at $9.99 per the owner's range
   (advanced + weekend + holiday would otherwise compute to $10.99).
8. **SEO** — title formula above; 13 category-aware tags; description with the
   six required sections.
9. **Determinism** — `random.Random(f"{date}|{seq}")`; same date + same seq →
   identical JSON. Consecutive dates differ by construction (name permutation +
   rotating ingredient windows).
10. **Cost estimate** — computed from the DB prices (USD per ml per oil,
    per-ml carrier prices, per-category packaging), +10 % buffer.

## Curating the ingredient database

Edit `fragbot/data/ingredients.json`. Structure:

```json
{
  "oils": [
    {"name": "Bergamot Essential Oil", "note": "Bergamot",
     "family": "citrus", "role": "top",
     "price_per_ml": 0.80, "drops_per_ml": 25, "flags": ["phototoxic"]}
  ],
  "carriers": [{"name": "Jojoba Oil", "price_per_ml": 0.30}]
}
```

- `family` must match a family referenced in `fragbot/themes.py` family pools
  (e.g. citrus, floral, woody, sweet, spicy, resin, musk, herbal, fresh,
  tobacco, conifer), otherwise the oil will never be selected — add it to the
  pools you want it available in.
- `role` is a fallback hint (top/heart/base); selection is driven by family.
- `flags`: `phototoxic`, `skin_restricted`, `max_parts:N`, `coumarin`.
- Only add real, purchasable essential oils / absolutes / fragrance oils /
  carriers. Captive/mythical ingredients break the "real purchasable" rule.
- Family pools must keep ≥ 5 oils per level (or at least count+2 for the
  rotating sampling windows) so blends stay unique and varietous.

## Examples shipped

`examples/recipe-2026-01-19-perfume.json` (a Monday perfume),
`examples/recipe-2026-02-03-candle.json` (a Tuesday candle),
`examples/recipe-2026-02-11-valentine-holiday.json` (a Valentine's Day
perfume). Dates are fixed demo dates so downstream components (image/PDF
generators) get stable fixtures; the same dates always regenerate the same
recipes.

---

# Fragrance Bot — listing image generator (`fragbot.imagesgen`)

Renders the five Etsy listing images for a recipe produced by the engine
above. **Pillow only** — no paid AI image tools, no network at render time.
Pillow is the package's only third-party dependency (`requirements.txt`);
the engine itself remains standard-library-only.

## The five images (all 2000×2000 px, sRGB JPEG)

| file           | content |
|----------------|---------|
| `hero.jpg`     | elegant dark hero card (#1a1a1a) with gold accents, Playfair Display recipe name, top/heart/base notes line, price pill, "DIY Fragrance Recipe" badge, "Digital Download" watermark, holiday edition badge |
| `ingredients.jpg` | clean cream/minimal list with droplet/circle icons, measurements, purpose tags, "Makes {yield}" + cost callout |
| `pyramid.jpg`  | visual scent pyramid: pastel top / warm heart / deep base blocks, connecting blend lines, 30/50/20 % labels, category chip, holiday badge |
| `included.jpg` | checklist (PDF Recipe Card, Step-by-Step Instructions, Safety Guidelines, Ingredient Sourcing Tips) with ✓ marks, price / difficulty / Instant Download tiles |
| `lifestyle.jpg`| "Create Your Signature Scent at Home" headline, category-specific product art drawn with PIL primitives (bottle, candle, spray, diffuser, tin), soft gradient, floating note pills, brand watermark |

Recipe-specific data is used throughout: recipe name on every image,
ingredient amounts on the breakdown, difficulty + cost on the included card,
category label on the pyramid, holiday gets a badge, and the recipe's 7-day
`theme` nudges the hero/lifestyle accent colour within the gold family.

## Running

```bash
# one recipe -> five JPEGs in out/<slug>/
python3 -m fragbot.imagesgen generate examples/recipe-2026-01-19-perfume.json --out listing

# a whole directory of recipe JSONs -> out/<slug>/ per recipe
python3 -m fragbot.imagesgen generate examples --out listing

# brand / shop name is configurable (watermarks)
python3 -m fragbot.imagesgen generate recipe.json --out listing --brand "My Shop"
FRAGBOT_BRAND="My Shop" python3 -m fragbot.imagesgen generate recipe.json --out listing
```

As a library:

```python
from fragbot.imagesgen import render_recipe
paths = render_recipe(recipe_json, "listing/", brand="Fragrance Bot", quality=90)
# -> {"hero": ".../hero.jpg", "ingredients": ..., "pyramid": ..., "included": ..., "lifestyle": ...}
```

## Output spec (enforced by `fragbot/imagesgen/verify.py`)

- 5 files with the exact names above; each 2000×2000 px, RGB, JPEG
- quality 88–92 (save path raises if asked for anything outside the band)
- 300 DPI metadata (`dpi=(300,300)`); embedded sRGB ICC profile when the
  platform provides one (Pillow LittleCMS), otherwise skipped cleanly —
  never an error
- each file < 10 MB (typical: 260–350 kB)
- text sized for thumbnails: recipe name up to 230 px Playfair Display,
  price 112 px, badges 28–38 px letterspaced

## Verification

```bash
python3 verify_images.py              # renders examples/ and checks every set
python3 verify_images.py --out /tmp/keep  # keep the rendered sets for eyeballing
```

Checks: exact file names, 2000×2000, RGB, JPEG format, 300 DPI, ICC presence
(or clean skip), size < 10 MB, JPEG quality estimate in the 88–92 band
(re-encode-size heuristic), and that rendering raised no errors for any input
recipe. Exit 0 = PASS. Rendered example sets live in `examples-images/<slug>/`.

## Fonts (vendored, free)

`fragbot/imagesgen/fonts/` ships the TTFs so CI/runtime never needs network:

- **Playfair Display** (v40, latin) — SIL OFL 1.1 — Google Fonts
- **Lato** (v25, latin) — SIL OFL 1.1 — tyPoland / Google Fonts
- **Cormorant Garamond** (v21, latin) — SIL OFL 1.1 — Catharsis Fonts / Google Fonts

Static TTFs were exported from the Google Fonts repository via
google-webfonts-helper (gwfh.mranftl.com) once and committed; the matching
`OFL-*.txt` licences are vendored alongside. `fonts.py` refuses to substitute
anything non-free: if a vendored file is missing it falls back (with a loud
warning) only to other free system fonts (DejaVu/Liberation) or errors out.

## Layout / code map

```
fragbot/imagesgen/
├── __init__.py     render_recipe() public API
├── cli.py          generate / verify subcommands
├── draw.py         PIL primitives: gradients, text fitting, shapes,
│                   botanical flourishes, product motifs (bottle/candle/…)
├── fonts.py        vendored-font loading with free-only fallback
├── render.py       the five renderers + save logic
├── verify.py       spec checks (used by verify_images.py and the CLI)
└── fonts/          13 TTFs + 3 OFL licences
```

Rendering is fully deterministic: same recipe JSON + same brand → identical
pixels (no randomness anywhere in the pipeline).
---

# Fragrance Bot — recipe-card PDF generator (`fragbot.pdfgen`)

Renders the **digital-download product** sold on Etsy: a beautifully branded,
printable PDF recipe card per recipe JSON produced by the engine. One file per
recipe → `<slug>.pdf`. **ReportLab 4+ (BSD licence — free, fully offline)** —
no paid services, no network at render time. Deterministic: identical recipe
JSON + brand → byte-identical PDF (verified by the verifier).

## Page plan (5 pages, US Letter 8.5 × 11 in)

| page | content |
|------|---------|
| 1 | **Cover** — dark #1a1a1a canvas with gold accents (theme-tinted, like the listing hero): "DIY Fragrance Recipe" kicker, Playfair Display recipe name (auto-shrinks to fit), category tagline, scent-bottle line-art motif, difficulty + price chips, theme/holiday gold pills, yield + cost-to-make stats, brand + "Instant Digital Download · Print at Home" |
| 2 | **Scent profile** — vector scent pyramid (pastel top / warm heart / deep base trapezoids from the imagesgen palette, with 30/50/20 % labels), right-hand legend (Top/Heart/Base + note names), blending-ratio note, "Wearing it" paragraph |
| 3 | **Ingredients & equipment** — sourced-style table (name, amount, purpose tag with brand colour dot), header row repeats if the table splits pages; two-column equipment checklist; cost-to-make callout |
| 4 | **Step-by-step instructions** — numbered gold circles (ReportLab-drawn pills) with generous spacing; long steps wrap automatically |
| 5 | **Safety notes** — stand-out amber panel with gold border and a "!" badge per note ("safety builds trust" per owner spec), plus difficulty / batch size / cost tiles |

Every page: footer with brand · "For personal use. Not for commercial
resale." · "© 2026 <brand>. All rights reserved." · "Page X of Y".

## Design notes

- **Brand continuity** — reuses `fragbot/imagesgen/style.py` (DARK/GOLD/CREAM
  palette, category & difficulty labels, purpose colours, the pyramid fill
  colours) and `accent_for_theme()` so the theme nudges the PDF accent exactly
  as it does the listing images.
- **Typography** — the exact same vendored free TTFs as the image generator
  (Playfair Display headings, Lato body, Cormorant Garamond accents), loaded
  from `fragbot/imagesgen/fonts/` — zero duplication, zero network.
- **US Letter** is the fixed page size (612×792 pt, 54 pt / 0.75 in margins);
  A4 users can print at 94 % scale via their printer dialog.
- **No overflow by construction** — interior pages use Platypus flowables
  (Paragraph/Table), so text wraps automatically; the cover name shrinks to
  fit; the ingredients table repeats its header when it splits across pages.
  Stress-tested with a synthetic worst-case recipe (18 ingredients, 17 notes,
  8 long instructions, 10 safety notes) — 6 pages, zero text outside margins.
- **Deterministic** — the canvas is created with `invariant=1` (fixed
  CreationDate, no document ID) and fonts are embedded, so renders are
  byte-identical for identical input (double-render check is part of verify).

## Running

```bash
# one recipe -> out/<slug>.pdf
python3 -m fragbot.pdfgen generate examples/recipe-2026-01-19-perfume.json --out cards

# a whole directory of recipe JSONs -> out/<slug>.pdf per recipe
python3 -m fragbot.pdfgen generate examples --out cards

# brand / shop name configurable (cover + footers)
python3 -m fragbot.pdfgen generate recipe.json --out cards --brand "My Shop"
FRAGBOT_BRAND="My Shop" python3 -m fragbot.pdfgen generate recipe.json --out cards
```

As a library:

```python
from fragbot.pdfgen import generate_pdf
path = generate_pdf(recipe_json, "cards/", brand="Fragrance Bot")
# -> cards/<slug>.pdf
```

## Verification

```bash
python3 verify_pdfs.py                       # renders examples/ and checks each PDF
python3 verify_pdfs.py --out examples-pdfs   # keep the PDFs for eyeballing
python3 -m fragbot.pdfgen verify --recipes examples --out /tmp/keep
```

Checks (per recipe, in `fragbot/pdfgen/verify.py`): schema-valid input;
rendering without errors; `<slug>.pdf` exists; size > 50 KB; starts with the
`%PDF-` header; pypdf opens it and reports ≥ 3 pages; extracted text ≥ 200
chars; determinism (two renders byte-identical). Exit 0 = PASS. Rendered
example PDFs live in `examples-pdfs/`; last run output in
`verification-pdfs-output.txt`.

## Layout / code map

```
fragbot/pdfgen/
├── __init__.py     generate_pdf() public API
├── cli.py          generate / verify subcommands
├── fonts.py        registers the imagesgen vendored TTFs with ReportLab
├── render.py       document build: cover canvas, flowables, pyramid drawing
├── verify.py       spec checks (used by verify_pdfs.py and the CLI)
└── __main__.py     `python -m fragbot.pdfgen` entry point
```

Fonts are **not** duplicated here — `fonts.py` registers
`fragbot/imagesgen/fonts/*.ttf` under ReportLab `FB-*` names. ReportLab (BSD)
and pypdf (BSD, for verification) are the only additional dependencies and are
listed in `requirements.txt` / `pyproject.toml`; the engine itself stays
standard-library-only.

# Fragrance Bot — Supabase layer (storage)

The pipeline's persistence: a recipe library (`recipes`) and a per-date
schedule (`daily_posts`) on a free-tier Supabase project. Everything here is
free-tier-OK, credentials are env-only, and the whole layer can be verified
before a database even exists (see "Verifying without a live DB" below).

## 1. Create the Supabase project (free tier)

1. Sign up / log in at <https://supabase.com> (free plan is enough).
2. **New project** → pick a region near you and a strong database password
   (**save it** — it is shown once and is *not* the same as your login).
3. Wait for provisioning (a minute or two).

## 2. Create the tables

Open **SQL Editor → New query**, paste the whole `supabase/schema.sql`, and
**Run**. (Or from a terminal: `psql "$POSTGRES_URL" -f supabase/schema.sql`.)
The file is idempotent, so re-running it is safe.

It creates:

| table | purpose | notes |
|---|---|---|
| `recipes` | one row per generated recipe | `slug` UNIQUE; `status` in `draft` / `draft_ready` / `listed` / `archived`; index on `(status, created_at)` for the daily queue |
| `daily_posts` | one row per calendar date the cron processes | `date` PK; `recipe_id` FK → `recipes.id`; `status` in `scheduled` / `posted` / `skipped` / `failed`; views/favorites/sales counters |

`status` semantics: `draft` = in the library but not queued; `draft_ready` =
in the daily posting queue (the cron draws these oldest-first); `listed` =
a listing was created (listing_id/etsy_url set); `archived` = retired.
`daily_posts.status` mirrors the cron run: `scheduled` → `posted` / `skipped`
/ `failed`.

## 3. Set the environment variables

Get them from **Project Settings → API** (URL + `service_role` key) and
**Project Settings → Database → Connection string**.

| variable | where from | used by |
|---|---|---|
| `POSTGRES_URL` | Database → Connection string (session pooler recommended for short scripts) — the password is the **database password** from step 1 | recommended backend for seed + cron (`PostgresStore`, direct SQL) |
| `SUPABASE_URL` | Project Settings → API → Project URL (e.g. `https://xxxx.supabase.co`) | alternative REST backend (`SupabaseRestStore`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings → API → `service_role` (secret! never expose client-side) | alternative REST backend |

Set the ones you use in your shell / GitHub Actions secrets. Nothing is
hardcoded — `fragbot/db.py` reads these three names only.

## 4. Seed the library

```bash
pip install 'psycopg[binary]'        # optional; only the Postgres backend needs it
export POSTGRES_URL='postgresql://...'   # from step 3

# live seed: 60 deterministic recipes (2026-01-01 onwards),
# first 30 status='draft_ready', remaining 30 status='draft'
python3 seed_recipes.py

# preview without touching a database (logs the exact SQL)
python3 seed_recipes.py --dry-run
python3 seed_recipes.py --dry-run --sql-out seed_library.sql   # runnable script
```

The seed is **idempotent and non-destructive**:

- it upserts on `recipes.slug`, so re-running never duplicates rows;
- it refreshes content fields only — it never resets `status` /
  `listing_id` / `etsy_url` / `created_at` / `listed_at`, so recipes that
  already progressed to `listed` are left alone.

`created_at` is staggered oldest-first, which is exactly how the daily cron
drains the queue: `get_next_draft_recipe()` returns the oldest unlisted
`draft_ready` recipe.

## 5. Using the storage layer from code

```python
from fragbot.db import get_store

db = get_store()                      # picks backend from env vars
recipe = db.get_next_draft_recipe()   # oldest unlisted draft_ready, or None
db.mark_listed(recipe["id"], "123456789", "https://www.etsy.com/listing/123456789")
db.record_daily_post(date(2026, 1, 19), recipe["id"], status="posted")
db.update_daily_post_metrics(date(2026, 1, 19), views=12, favorites=3, sales=1)
```

Backends (same interface, chosen automatically):

- `PostgresStore` — direct SQL via psycopg 3 (`POSTGRES_URL`). Recommended:
  transactional seed, atomic metric increments.
- `SupabaseRestStore` — pure-stdlib client of Supabase's PostgREST API
  (`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`). Zero extra dependencies.
- `StubStore` — in-memory, used by tests / dry runs.

`get_store()` raises `StoreNotConfiguredError` (with hints) when no
credentials are set.

## Verifying without a live DB

```bash
python3 verify_supabase.py     # writes verification-supabase.txt
```

24 checks across five areas: seed counts/uniqueness/schema-validity,
store logic (stub + SQL builders), **real Postgres semantics** (schema DDL,
CHECK/UNIQUE/FK constraints, the exact seed SQL, queue + metrics SQL), the
REST store's request shape against a mock PostgREST server, and the seed
CLI's SQL dump.

The Postgres-engine checks run on **PGlite** — Postgres compiled to WASM —
so the schema and every SQL statement are executed by a genuine Postgres
engine, not mocked. One-time dev setup:

```bash
mkdir -p /tmp/pgverify && cd /tmp/pgverify && npm install @electric-sql/pglite
# verify_supabase.py finds it there automatically; or point it somewhere else:
# export PGLITE_MODULE_PATH=/path/to/node_modules
```

If node/PGlite is missing, only the Postgres-engine checks are skipped
(everything else still runs) and the report says so explicitly. What cannot
be verified locally is only the network hop to Supabase's servers — that is
done once the real credentials land in Secrets.
