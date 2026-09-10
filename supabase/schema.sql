-- ============================================================================
-- Fragrance Bot — Supabase / Postgres schema (free tier)
-- ============================================================================
-- Target: Supabase's managed Postgres (15+). Also runs on any Postgres 13+
-- (gen_random_uuid() is built-in from PG13; PG12 would need the pgcrypto
-- extension).
--
-- How to apply:
--   Option A (recommended): Supabase Dashboard -> SQL Editor -> paste this
--     file -> Run.
--   Option B: psql "$POSTGRES_URL" -f supabase/schema.sql
--
-- The file is idempotent: re-running it is safe (CREATE ... IF NOT EXISTS).
--
-- Security note: these tables are owned/accessed by the service role (the
-- cron uses SUPABASE_SERVICE_ROLE_KEY). Row Level Security is intentionally
-- left DISABLED so nothing else is required for the pipeline to work. If a
-- public dashboard ever needs anon reads, enable RLS per table and add a
-- policy for the anon role — that is a future change, not needed today.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- recipes — one row per generated DIY fragrance recipe (the library)
-- ---------------------------------------------------------------------------
-- status semantics:
--   'draft'       in the library, NOT yet in the daily posting queue
--   'draft_ready' in the daily queue; the cron draws from these first
--   'listed'      a listing was created on Etsy (listing_id / etsy_url set)
--   'archived'    retired (end-of-library fallback, manual cleanup, etc.)
--
-- The spec's status vocabulary is draft_ready / listed / archived; 'draft'
-- is added so the seed can park 30 library-only recipes that are not yet
-- queued. seed_recipes.py marks the first 30 as 'draft_ready' and the rest
-- as 'draft'.
-- ---------------------------------------------------------------------------
create table if not exists public.recipes (
    id              uuid primary key default gen_random_uuid(),
    recipe_name     text        not null,
    category        text        not null
                    check (category in ('perfume', 'cologne', 'candle',
                                        'reed_diffuser', 'room_spray',
                                        'solid_perfume')),
    difficulty      text        not null
                    check (difficulty in ('beginner', 'intermediate',
                                          'advanced')),
    -- scent_profile: {"top_notes": [...], "heart_notes": [...], "base_notes": [...]}
    scent_profile   jsonb       not null,
    -- ingredients:   [{"name": ..., "amount": ..., "purpose": ...}, ...]
    ingredients     jsonb       not null,
    instructions    jsonb       not null,   -- [step strings]
    equipment       jsonb       not null,   -- [item strings]
    safety_notes    jsonb       not null,   -- [warning strings]
    yield_text      text        not null,   -- engine "yield" field ("1 x 10ml roll-on bottle")
    -- The engine emits cost_to_make as a display string ("~$5.24"); the
    -- numeric price used for payment lives in price_usd. Keeping the display
    -- string as text preserves the engine output exactly.
    cost_to_make    text        not null,
    price_usd       numeric(6,2) not null check (price_usd >= 0),
    full_title      text        not null,   -- Etsy title (<= 140 chars)
    slug            text        not null unique,
    tags            jsonb       not null,   -- exactly 13 Etsy tags (<= 20 chars each)
    description_long text       not null,
    theme           text        not null,   -- 7-day content theme
    holiday         text,                   -- null unless a holiday is detected
    status          text        not null default 'draft'
                    check (status in ('draft', 'draft_ready', 'listed',
                                      'archived')),
    listing_id      text,                   -- Etsy listing id once posted
    etsy_url        text,                   -- Etsy listing URL once posted
    created_at      timestamptz not null default now(),
    listed_at       timestamptz             -- set when status becomes 'listed'
);

-- The daily cron's hot query:
--   WHERE status = 'draft_ready' AND listing_id IS NULL
--   ORDER BY created_at LIMIT 1  (oldest queued recipe first)
create index if not exists recipes_status_created_idx
    on public.recipes (status, created_at);

-- Convenience index for "has this recipe been listed?" lookups.
create index if not exists recipes_status_listing_idx
    on public.recipes (listing_id)
    where listing_id is not null;

-- ---------------------------------------------------------------------------
-- daily_posts — one row per calendar date the cron processes (the schedule)
-- ---------------------------------------------------------------------------
-- status semantics:
--   'scheduled' recipe chosen for the date (or date queued without a recipe)
--   'posted'    listing created + post completed
--   'skipped'   deliberately skipped (e.g. fallback queue exhausted)
--   'failed'    an error occurred; retry policy decides what happens next
-- ---------------------------------------------------------------------------
create table if not exists public.daily_posts (
    date        date primary key,
    recipe_id   uuid not null references public.recipes (id) on delete cascade,
    listing_id  text,                       -- Etsy listing id, once posted
    status      text not null default 'scheduled'
                check (status in ('scheduled', 'posted', 'skipped', 'failed')),
    views       integer not null default 0 check (views >= 0),
    favorites   integer not null default 0 check (favorites >= 0),
    sales       integer not null default 0 check (sales >= 0),
    posted_at   timestamptz                 -- set when status becomes 'posted'
);

create index if not exists daily_posts_status_idx
    on public.daily_posts (status);