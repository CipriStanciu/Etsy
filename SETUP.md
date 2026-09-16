# Fragrance Bot — GO LIVE Setup Guide

This is the owner-facing runbook for taking the Fragrance Bot pipeline live:
wire the real credentials, verify the daily cron, and run the first real Etsy
listing. It consolidates the run/deploy documentation from `README.md` into
one ordered, step-by-step path — no engineering background assumed.

The code is already built, committed, and verified on `main`. You only need to
do the six things below, in order.

```
1. Supabase (free project, tables, seed)
2. Etsy app registration + one-time owner authorization (refresh token)
3. GitHub Secrets wiring
4. Verify the daily cron (GitHub Actions)
5. Live test posting (one real Etsy listing)
6. Troubleshooting (when something fails)
```

Everything you need is free: Supabase free tier, GitHub Actions free tier,
Etsy's API, Python's Pillow/ReportLab (open source). The only recurring cost
is Etsy's **$0.20 per-listing fee**, which Etsy bills to your shop directly.
At the default posting cadence — one new listing **every 3 days** (see
`FRAGBOT_POST_INTERVAL_DAYS` below) — that averages **≈ $0.07/day
(≈ $2/month)**; set the interval to 1 for daily posting (~$6/month) whenever
you want to ramp back up.

---

## 1. Supabase setup (free project + recipe library)

The Bot keeps its recipe library in a free Supabase project. Three steps:
create the project, apply the schema, seed 60 recipes.

### 1.1 Create the free project

1. Go to <https://supabase.com> and sign up / log in (the free plan is
   enough).
2. **New project** → pick a region near you and set a strong **database
   password**. **Save it** — it is shown once and is *not* the same as your
   login password.
3. Wait a minute or two for provisioning to finish.

### 1.2 Apply the schema (two tables)

1. In the Supabase dashboard open **SQL Editor → New query**.
2. Paste the **whole** contents of `supabase/schema.sql` (from this repo) and
   click **Run**.
3. The file is idempotent — re-running it is safe.

It creates two tables: `recipes` (one row per generated recipe, with a
`status` column) and `daily_posts` (one row per posting attempt — non-posting
days write none; see step 4).

### 1.3 Find your two Supabase credentials

In the Supabase dashboard open **Project Settings → API**:

| Value | Where it is | Save as (secret name) |
|---|---|---|
| **Project URL** — e.g. `https://xxxx.supabase.co` | Project Settings → API → Project URL | `SUPABASE_URL` |
| **`service_role` key** (a long `eyJ...` string) | Project Settings → API → `service_role` section | `SUPABASE_SERVICE_ROLE_KEY` |

> ⚠️ **The `service_role` key is a master key.** Anyone holding it can read
> and write your whole database. Never expose it publicly, never paste it in
> client-side code, never commit it to a repo, never share it in chat. It only
> ever goes into your GitHub Secrets (step 3) or your local shell (step 5).

> Optional alternative backend: Supabase **Project Settings → Database →
> Connection string** gives a `POSTGRES_URL` (the password is the **database
> password** from 1.1, not the `service_role` key). The pipeline works with
> either `POSTGRES_URL` *or* `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
> (if both are set, `POSTGRES_URL` wins — `fragbot/db.py` checks it first).
> This guide uses the two-key REST route because it needs **no extra Python
> packages**.

### 1.4 Seed the recipe library (60 recipes, 30 ready to post)

The seed generates 60 deterministic, safety-vetted recipes: the **first 30**
get status `draft_ready` (they are the daily posting queue), the **remaining
30** get status `draft` (library only, not queued).

In a terminal on any machine with the repo checked out and Python 3.9+:

```bash
cd <repo>                                  # the Fragrance Bot repo
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJ..."
python3 seed_recipes.py
```

The seed uses only the Python standard library (no `pip install` needed for
this step). A successful run prints one line per recipe and finishes with:

```
OK: 60 recipes upserted
```

- **Idempotent:** re-running it never duplicates rows (upserts key on
  `slug`), and it never resets recipes that already progressed to `listed`.
- **Preview first** (optional, touches nothing): `python3 seed_recipes.py
  --dry-run`.
- **No-terminal alternative:** run `python3 seed_recipes.py --dry-run
  --sql-out seed_library.sql` once, then open that file in Supabase's SQL
  editor and click **Run** — same result, no shell credentials needed.

### 1.5 Confirm the seed worked

Back in the Supabase dashboard (**SQL Editor → New query**), run:

```sql
select status, count(*) from public.recipes group by status order by status;
select count(*) as daily_posts_rows from public.daily_posts;
```

A correct seed looks like:

| status | count |
|---|---|
| `draft` | 30 |
| `draft_ready` | 30 |

and `daily_posts` is **0 rows** (it only fills in as the cron runs). There are
no `listed` recipes yet. If you ever re-run the seed later, `listed` counts
will appear and grow — that is expected.

The cron draws the **oldest** `draft_ready` recipe first (on posting days
only — see step 4.1), so the very first posting will be the first seeded
recipe (dated 2026-01-01). The queue of 30 holds **~90 days of runway at the
default 3-day cadence** (~30 days if you set `FRAGBOT_POST_INTERVAL_DAYS=1`);
when it drops below 10, the analytics dashboard's inventory alert goes off
(see the README's dashboard section).

---

## 2. Etsy app registration + one-time authorization

The pipeline talks to Etsy through a developer app **you** create and approve
once. The approval produces a long-lived **refresh token** — the only Etsy
credential the Bot keeps.

### 2.1 Create the app

1. Go to <https://www.etsy.com/developers/your-apps> (logged in as your shop's
   Etsy account) → **Create a new app**.
2. Name it (e.g. "Fragrance Bot"), tick the terms, and create it. You'll get:
   - the **keystring** — this is `ETSY_KEYSTRING`;
   - the **shared secret** — *not* required by the pipeline (only used for an
     optional extra API header); you can ignore it.
3. In the app's **Redirect URIs** add **exactly**:
   `http://localhost:8080/callback`
   (Etsy requires exact matches, and explicitly allows `localhost` for
   development. The one-time helper in 2.3 uses that address.)
4. Copy the keystring and keep it secret.

**OAuth scopes.** When you approve the app (2.3), it requests the scopes the
pipeline needs: `listings_r` (read listings), `listings_w` (create/update
listings, which covers image + digital-file upload), `transactions_r`, and
`shops_r` (so the pipeline can verify your shop). Approve all of them — the
helper requests exactly this set.

### 2.2 Find your shop ID (`ETSY_SHOP_ID`)

The pipeline addresses your shop by its **numeric** ID (not its name). To find
it:

- Open your shop page — `https://www.etsy.com/shop/<YourShopName>` — view the
  page source (right-click → *View page source*, Ctrl/Cmd+U) and search for
  `shop_id`: you'll find a number like `"shop_id": 12345678`. That number is
  your `ETSY_SHOP_ID`. (As a fallback you can also look it up through Etsy's
  API, but the page source is the quickest no-API route.)

### 2.3 Mint the refresh token (`ETSY_REFRESH_TOKEN`) — once

From the repo on any machine with Python 3.9+ (this script is standard
library only):

```bash
export ETSY_KEYSTRING="<your keystring from 2.1>"
python3 scripts/etsy_oauth.py
```

The script:

1. Starts a tiny local callback server on `http://localhost:8080/callback`
   and **prints an Etsy authorization URL**;
2. **You open that URL** in your browser while logged into your shop's Etsy
   account, review the requested scopes, and click **Approve**;
3. Your browser redirects back to the local page ("Authorization received —
   you can close this tab");
4. Back in the terminal, the script prints the **REFRESH TOKEN** and the
   confirmed scopes.

**Copy the printed REFRESH TOKEN into a safe place** — it becomes the
`ETSY_REFRESH_TOKEN` secret in step 3. Anyone holding it can manage the shop;
never commit it or paste it in public chats.

> **Token rotation — what it means for you.** Etsy *rotates* the refresh
> token on every refresh. The pipeline saves each new token automatically
> (into an `etsy_tokens` table it creates in your Supabase database, with the
> local gitignored file `secrets/etsy_refresh_token` as fallback), so the
> secret you set in step 3 is just the bootstrap. You only re-run this script
> if the token is ever revoked (see troubleshooting).

---

## 3. Wire the credentials (GitHub Secrets)

The daily cron runs in GitHub Actions and reads its credentials from the
repo's **Secrets**. Go to: your GitHub repo → **Settings → Secrets and
variables → Actions → New repository secret**.

Add each secret with the **exact name** below (these are the names the code
and the workflow actually read — verified against `.github/workflows/
daily-post.yml`, `fragbot/db.py`, `fragbot/etsy/*` and `scripts/daily_post.py`;
don't rename them):

| Secret name | Value | Required? |
|---|---|---|
| `SUPABASE_URL` | Project URL from step 1.3 | ✅ required |
| `SUPABASE_SERVICE_ROLE_KEY` | `service_role` key from step 1.3 | ✅ required |
| `ETSY_KEYSTRING` | App keystring from step 2.1 | ✅ required |
| `ETSY_SHOP_ID` | Numeric shop ID from step 2.2 | ✅ required |
| `ETSY_REFRESH_TOKEN` | Token printed in step 2.3 | ✅ required |

Optional secrets (skip unless you want the behaviour):

| Secret name | Enables | When to add |
|---|---|---|
| `ETSY_TAXONOMY_ID` | Pins the listing category to a fixed Etsy category id | **Recommended** — add after your first live run (step 5.5) |
| `POSTGRES_URL` | Direct-SQL database backend instead of the REST route | Only if you prefer the `POSTGRES_URL` alternative from 1.3 |
| `RESEND_API_KEY` + `ETSY_NOTIFY_TO` | Sends you a notification email with each new listing URL (posting days only; the URL is always logged regardless) | Optional |
| `ETSY_SHIPPING_PROFILE_ID` | Attaches a shipping profile | Not needed — the listings are digital downloads |
| `ETSY_NOTIFY_FROM` | Custom sender for the notification email | Only if you want a non-default sender; note the workflow env doesn't pass it yet, so add one line to the workflow if you do |

> **Posting cadence (optional, no code changes):** set `FRAGBOT_POST_INTERVAL_DAYS`
> as a repository **variable** (Settings → Secrets and variables → Actions →
> Variables, name `FRAGBOT_POST_INTERVAL_DAYS`, value `3`) or as a secret with
> the same name. It is the number of days between postings: `1` = every day
> (the old behaviour), `2` = every 2 days, `3` = every 3 days (default when
> unset). The workflow still triggers **daily at 08:00 UTC**; on non-posting
> days the script logs `not a posting day (interval N) — nothing to do` and
> exits 0 — a green run that writes nothing (no recipe consumed, no
> `daily_posts` row, no listing fee charged).

> The code also reads `ETSY_SHARED_SECRET` (optional extra API header) and
> `FRAGBOT_BRAND` (watermark text) if you ever set them locally; neither is
> needed to go live.

When all five required secrets are saved, the workflow can run the pipeline
end to end.

---

## 4. Verify the daily cron (GitHub Actions)

### 4.1 The workflow is on `main`

The file `.github/workflows/daily-post.yml` is committed on `main` (you can
see it at GitHub → *Actions* and in the repo tree at `.github/workflows/`).
It triggers on a schedule — **08:00 UTC every day** — and can also be
triggered manually. The script inside enforces the posting cadence: posting
days are those where `(today − 2026-01-01).days % FRAGBOT_POST_INTERVAL_DAYS
== 0` (default interval **3** → about every 3 days; see step 3). The cron
expression itself never changes — you only change the interval variable.

### 4.2 Run it manually

1. GitHub repo → **Actions** tab.
2. On the left choose the **daily-post** workflow.
3. Click **Run workflow** (top right) → use the default branch → **Run
   workflow**.
4. Click the new run to watch it live.

### 4.3 What a run looks like

**On a posting day** the run finishes **green** with exit code 0. The log
shows the cadence decision (`posting day (interval 3) — would post` for
dry-runs) and each stage, ending with lines like:

```
INFO ... rendered 5 listing images + PDF at ...
INFO ... created draft listing 123456789 for <slug>
INFO ... posted <slug> -> listing 123456789 (https://www.etsy.com/listing/123456789)
```

Together with the shop/taxonomy verification and the 5 image uploads (rank 1–5)
in between. A "daily-post-logs" artifact (kept 14 days) is attached to every
run for inspection.

**On Etsy** the result is one **active** digital-download listing: title,
pricing tags, 5 images, and the recipe PDF attached as the digital file.

**On a NON-posting day** the run is still **green** (exit 0) but does
nothing: the log shows `not a posting day (interval 3) — nothing to do`,
no recipe is consumed, no `daily_posts` row is written, and Etsy is never
called — so no `$0.20` listing fee is charged.

### 4.4 What a failed run looks like (and the safety net)

A failed run shows a **red ✗** (non-zero exit — the workflow is deliberately
configured to fail loudly rather than silently skip). When that happens:

- the recipe **stays `draft_ready`** — it is never marked `listed`;
- the day is recorded as `failed` in the `daily_posts` table;
- the **next posting day retries the same recipe** — idempotent, no dupes;
- **no partial listing goes live**: the listing is only activated after all 5
  images are uploaded. If a failure happens *after* the draft was created but
  before activation, an **inactive draft** is left on Etsy for manual cleanup
  and its listing id is logged — harmless, never sold to anyone.

---

## 5. Live test posting (first real Etsy listing)

Do the seed (step 1) first so the queue is non-empty — otherwise the run just
logs `no draft_ready recipe in the queue — nothing to do` and exits 0.

### 5.1 Recommended flow

**Option A — trigger from GitHub (no local Python needed):** follow step 4.2.
**Option B — run locally** (nicer logs, same pipeline; needs the repo, Python
3.9+, and Pillow + ReportLab):

```bash
cd <repo>
pip install -r requirements.txt          # Pillow, ReportLab, pypdf — free OSS
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJ..."
export ETSY_KEYSTRING="<keystring>"
export ETSY_SHOP_ID="<numeric shop id>"
export ETSY_REFRESH_TOKEN="<token from step 2.3>"
export FRAGBOT_POST_INTERVAL_DAYS="3"    # optional — posting cadence in days
python3 scripts/daily_post.py --log-file logs/daily-post.log
```

Either way, on a posting day the run posts the **oldest** `draft_ready`
recipe — the first recipe of the seed. The script renders its 5 listing
images and the recipe-card PDF, creates the listing, uploads the images,
activates the listing, attaches the PDF, and records the post. If you run on
a non-posting day you'll see `not a posting day (interval N) — nothing to
do` and exit 0 — that's expected (step 4.3); use
`FRAGBOT_POST_INTERVAL_DAYS=1` temporarily if you want the very next run to
post.

No credentials handy but want to see the flow? `python3 scripts/daily_post.py
--dry-run` renders everything and prints the exact payloads Etsy would receive
— no network, no credentials.

### 5.2 Verify the listing on Etsy

Open the listing URL from the log (`https://www.etsy.com/listing/<id>`) and
check, as a buyer would:

- **Listing page** — page loads, title reads like a normal product title
  (≤140 chars), price shows in the $3.99–$9.99 band;
- **Images** — all 5 images present and look right (hero card, ingredients,
  scent pyramid, what's-included, lifestyle);
- **Digital download** — the listing shows it's a *digital download* and the
  recipe PDF is attached (check *Shop Manager → Listings → edit* if the badge
  isn't obvious);
- **Tags** — all 13 tags were submitted (visible in the listing editor);
- **Category** — the auto-picked category looks sensible.

### 5.3 Pin the category (`ETSY_TAXONOMY_ID`) after the first run

The pipeline picks the listing category automatically: it searches Etsy's
seller taxonomy for the deepest node matching DIY/download keywords, falling
back to **563** — the "Craft Supplies & Tools" root — when nothing matches.
Auto-picking is good enough for the first run, but the team's recommendation
is: after that first live listing, note the exact category Etsy assigned, find
its numeric category id, and add the `ETSY_TAXONOMY_ID` secret (step 3) so
every future listing uses the same pinned category. The override wins over
both the lookup and the fallback.

---

## 6. Troubleshooting

Every error is logged with the failing step. Where to look: the local terminal
output (or your `logs/daily-post.log` if you used `--log-file`), or on GitHub
the Actions run page → the failed step → the **daily-post-logs** artifact
(14-day retention).

| Symptom (what you see) | Likely cause | Fix |
|---|---|---|
| `daily post failed: ... unauthorized / invalid token / invalid_grant` | Etsy refresh token expired, revoked, or mis-typed in Secrets | Re-run `python3 scripts/etsy_oauth.py` (step 2.3), copy the new token into the `ETSY_REFRESH_TOKEN` secret (step 3), and re-trigger the workflow. This is the most common failure — the token only needs re-minting if it was revoked; normal rotation is handled automatically. |
| `HTTP 429` / `Too Many Requests` (rate limit) | Etsy API rate limiting (max ~10 req/sec) | Usually nothing to do: the client spaces requests ≥150 ms apart and retries 429s automatically, honoring Etsy's `Retry-After`. If you hit it, wait a few minutes and re-run manually; persistent 429s mean something else is also calling the API — check no other script uses the same keystring. |
| Taxonomy error, or listing lands in a wrong/generic category | Auto-lookup found no good match (falls back to 563) | Set `ETSY_TAXONOMY_ID` to the numeric category you want (step 5.3) — it overrides everything. |
| `could not configure the store` / `no Supabase credentials found` | Secrets missing or mis-named (exit code 2) | Confirm `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set with the **exact** names in step 3, and that the schema from step 1.2 was applied. |
| `no draft_ready recipe in the queue — nothing to do` (run is green) | Seed hasn't run, or the queue is drained | Run `python3 seed_recipes.py` (step 1.4) and confirm 30 `draft_ready` rows (step 1.5). |
| `not a posting day (interval 3) — nothing to do` (run is green, nothing posted) | Normal — today is between posting days at the current cadence | Nothing to fix: this is the intended behaviour (step 4.3). The next posting day happens automatically. To post *today* instead, temporarily set `FRAGBOT_POST_INTERVAL_DAYS=1` in the workflow env (step 3). |
| Inactive draft left on Etsy after a failed run | Failure happened after draft creation, before activation | The listing id is in the log; delete the draft manually from Shop Manager. It was never activated, so no customer saw it. |

---

## Done when

- [ ] Supabase project created; `supabase/schema.sql` applied via SQL Editor
- [ ] Seed ran: `select status, count(*) ...` shows `draft_ready` 30 / `draft` 30
- [ ] Etsy app created with redirect URI `http://localhost:8080/callback`
- [ ] Refresh token minted via `scripts/etsy_oauth.py` and saved
- [ ] 5 required secrets added: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
      `ETSY_KEYSTRING`, `ETSY_SHOP_ID`, `ETSY_REFRESH_TOKEN`
- [ ] Manual workflow run (Actions → daily-post → Run workflow) is green
- [ ] One real listing verified on Etsy: page, 5 images, PDF download, price, tags
- [ ] `ETSY_TAXONOMY_ID` pinned after the first live run
- [ ] (Optional) `FRAGBOT_POST_INTERVAL_DAYS` repository variable set — e.g. `3`

After go-live the pipeline posts one new listing **every 3 days by default**
(configurable via `FRAGBOT_POST_INTERVAL_DAYS`; the workflow still triggers
daily at 08:00 UTC and skips non-posting days with a green, no-op run), at
~$0.07/day average in Etsy listing fees. The repo also already ships a
private analytics dashboard (`dashboard/`, see README) and a social
promotion engine (`fragbot/promo/`) — both are ready to adopt once live
Etsy data flows.