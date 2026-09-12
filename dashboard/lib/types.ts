// Shared types — mirror supabase/schema.sql (public.recipes + public.daily_posts)
// exactly so the live API route and the bundled stub.json are interchangeable.

export type RecipeStatus = "draft" | "draft_ready" | "listed" | "archived";
export type PostStatus = "scheduled" | "posted" | "skipped" | "failed";

export interface ScentProfile {
  top_notes: string[];
  heart_notes: string[];
  base_notes: string[];
}

export interface Ingredient {
  name: string;
  amount: string;
  purpose: string;
}

export interface Recipe {
  id: string;
  recipe_name: string;
  category: string;
  difficulty: string;
  scent_profile: ScentProfile;
  ingredients: Ingredient[];
  instructions: string[];
  equipment: string[];
  safety_notes: string[];
  yield_text: string;
  cost_to_make: string;
  price_usd: number;
  full_title: string;
  slug: string;
  tags: string[];
  description_long: string;
  theme: string;
  holiday: string | null;
  status: RecipeStatus;
  listing_id: string | null;
  etsy_url: string | null;
  created_at: string;
  listed_at: string | null;
}

export interface DailyPost {
  date: string; // YYYY-MM-DD
  recipe_id: string;
  listing_id: string | null;
  status: PostStatus;
  views: number;
  favorites: number;
  sales: number;
  posted_at: string | null;
}

export type DataSource = "stub" | "live-supabase-rest" | "live-postgres";

export interface DashboardData {
  source: DataSource;
  generated_at: string;
  recipes: Recipe[];
  daily_posts: DailyPost[];
  meta?: Record<string, unknown>;
}

export const SEED_START = "2026-01-01"; // engine/seed default (seed_recipes.py)