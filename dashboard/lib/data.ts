// Server-side data source for the dashboard (used by app/api/data/route.ts).
// Resolution order:
//   1. SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY  -> Supabase PostgREST (live)
//   2. POSTGRES_URL                              -> direct Postgres via `pg` (live)
//   3. neither                                   -> bundled dashboard/data/stub.json
// The safest possible default is the STUB: the UI always labels its data source
// and never claims sample data is live.

import { readFile } from "node:fs/promises";
import path from "node:path";
import type { DashboardData, DailyPost, Recipe } from "./types";

const SUPABASE_URL = (process.env.SUPABASE_URL || "").trim().replace(/\/+$/, "");
const SERVICE_ROLE_KEY = (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();
const POSTGRES_URL = (process.env.POSTGRES_URL || "").trim();

function toNum(v: unknown): number {
  const n = typeof v === "string" ? Number.parseFloat(v) : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function toDay(v: unknown): string {
  if (!v) return "";
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  return String(v).slice(0, 10);
}

function normRecipe(r: Record<string, any>): Recipe {
  return { ...(r as unknown as Recipe), price_usd: toNum(r.price_usd) };
}

function normPost(p: Record<string, any>): DailyPost {
  return {
    ...(p as unknown as DailyPost),
    date: toDay(p.date),
    views: toNum(p.views),
    favorites: toNum(p.favorites),
    sales: toNum(p.sales),
  };
}

async function loadStub(): Promise<DashboardData> {
  const file = path.join(process.cwd(), "data", "stub.json");
  const raw = JSON.parse(await readFile(file, "utf8")) as DashboardData;
  return {
    source: "stub",
    generated_at: new Date().toISOString(),
    recipes: raw.recipes.map(normRecipe),
    daily_posts: raw.daily_posts.map(normPost),
    meta: raw.meta,
  };
}

async function loadSupabaseRest(): Promise<DashboardData> {
  const headers = {
    apikey: SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
  };
  const [recipesRes, postsRes] = await Promise.all([
    fetch(`${SUPABASE_URL}/rest/v1/recipes?select=*&order=created_at.asc`, {
      headers,
      signal: AbortSignal.timeout(15_000),
    }),
    fetch(`${SUPABASE_URL}/rest/v1/daily_posts?select=*&order=date.asc`, {
      headers,
      signal: AbortSignal.timeout(15_000),
    }),
  ]);
  if (!recipesRes.ok || !postsRes.ok) {
    throw new Error(
      `Supabase REST responded ${recipesRes.status}/${postsRes.status} — check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY`,
    );
  }
  const [recipes, posts] = (await Promise.all([
    recipesRes.json(),
    postsRes.json(),
  ])) as [Record<string, any>[], Record<string, any>[]];
  return {
    source: "live-supabase-rest",
    generated_at: new Date().toISOString(),
    recipes: recipes.map(normRecipe),
    daily_posts: posts.map(normPost),
  };
}

async function loadPostgres(): Promise<DashboardData> {
  // Imported lazily inside the branch so the module can also be type-checked
  // without the dependency ever touching the client bundle.
  const pgModule = await import("pg");
  const client = new pgModule.Client({ connectionString: POSTGRES_URL });
  try {
    await client.connect();
    const [recipesRes, postsRes] = await Promise.all([
      client.query("select * from public.recipes order by created_at asc"),
      client.query("select * from public.daily_posts order by date asc"),
    ]);
    return {
      source: "live-postgres",
      generated_at: new Date().toISOString(),
      recipes: (recipesRes.rows as Record<string, any>[]).map(normRecipe),
      daily_posts: (postsRes.rows as Record<string, any>[]).map(normPost),
    };
  } finally {
    await client.end();
  }
}

export async function loadDashboardData(): Promise<DashboardData> {
  if (SUPABASE_URL && SERVICE_ROLE_KEY) return loadSupabaseRest();
  if (POSTGRES_URL) return loadPostgres();
  return loadStub();
}