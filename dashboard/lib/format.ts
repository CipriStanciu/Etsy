// Client-safe pure helpers: dates, SEO scoring, UTM links, engagement math.

import type { DailyPost, Recipe } from "./types";
import { SEED_START } from "./types";

// ── dates ────────────────────────────────────────────────────────────────────
export function todayISO(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

const DAY_MS = 86_400_000;

export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d) + days * DAY_MS);
  return dt.toISOString().slice(0, 10);
}

export function fmtDate(iso: string, withYear = false): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const name = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  return withYear ? `${name}, ${y}` : name;
}

export function daysBetween(aIso: string, bIso: string): number {
  const [ay, am, ad] = aIso.split("-").map(Number);
  const [by, bm, bd] = bIso.split("-").map(Number);
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / DAY_MS);
}

/** Deterministic engine plan: recipe index for a date (engine is deterministic
 *  per date; seed plan starts at SEED_START and rolls over the recipe library). */
export function enginePlanIndex(iso: string, recipeCount: number): number {
  if (recipeCount <= 0) return 0;
  const idx = daysBetween(SEED_START, iso);
  return ((idx % recipeCount) + recipeCount) % recipeCount;
}

// ── money / engagement ───────────────────────────────────────────────────────
export function money(n: number): string {
  return `$${n.toFixed(2)}`;
}

export function engagement(post: DailyPost): number {
  return post.views + post.favorites * 3 + post.sales * 10;
}

// ── SEO score (computed client-side from recipe JSON) ────────────────────────
export interface SeoCheck {
  key: string;
  label: string;
  pass: boolean;
  detail: string;
}

export interface SeoResult {
  score: number;
  checks: SeoCheck[];
  titleLength: number;
  tagCount: number;
  maxTagLength: number;
  descriptionWords: number;
}

export function seoScore(recipe: Recipe): SeoResult {
  const titleLength = recipe.full_title.length;
  const tagCount = recipe.tags.length;
  const maxTagLength = Math.max(...(recipe.tags.map((t) => t.length) as number[]), 0);
  const descriptionWords = recipe.description_long.trim().split(/\s+/).filter(Boolean).length;
  const uniqueTags = new Set(recipe.tags.map((t) => t.toLowerCase())).size;

  const checks: SeoCheck[] = [
    {
      key: "title",
      label: "Title length ≤ 140 characters (Etsy limit)",
      pass: titleLength <= 140,
      detail: `${titleLength}/140`,
    },
    {
      key: "tag-count",
      label: "Exactly 13 tags (Etsy max)",
      pass: tagCount === 13,
      detail: `${tagCount} tags`,
    },
    {
      key: "tag-length",
      label: "Every tag ≤ 20 characters",
      pass: maxTagLength <= 20,
      detail: `longest tag ${maxTagLength}/20`,
    },
    {
      key: "desc",
      label: "Description ≥ 120 words (Etsy best practice)",
      pass: descriptionWords >= 120,
      detail: `${descriptionWords} words`,
    },
    {
      key: "tags-unique",
      label: "Tags are unique (no duplicates)",
      pass: uniqueTags === tagCount,
      detail: `${uniqueTags}/${tagCount} unique`,
    },
  ];
  const passed = checks.filter((c) => c.pass).length;
  return {
    score: Math.round((passed / checks.length) * 100),
    checks,
    titleLength,
    tagCount,
    maxTagLength,
    descriptionWords,
  };
}

// ── UTM builder ──────────────────────────────────────────────────────────────
export interface UtmParams {
  source: string;
  medium: string;
  campaign: string;
  content?: string;
}

export function buildUtm(baseUrl: string, p: UtmParams): string {
  const url = new URL(baseUrl);
  url.searchParams.set("utm_source", p.source.trim());
  url.searchParams.set("utm_medium", p.medium.trim());
  url.searchParams.set("utm_campaign", p.campaign.trim());
  if (p.content?.trim()) url.searchParams.set("utm_content", p.content.trim());
  return url.toString();
}

export function slugHue(slug: string): number {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) % 360;
  return h;
}