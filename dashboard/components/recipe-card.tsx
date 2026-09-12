"use client";

// A full recipe card — the daily-post tracker's centerpiece: recipe identity,
// status, price, the 5 image previews, Etsy listing link and post metrics.

import type { DailyPost, Recipe } from "@/lib/types";
import { fmtDate, money } from "@/lib/format";
import PreviewStrip from "./preview-strip";
import { Pill } from "./ui";

const CATEGORY_TONE: Record<string, "purple" | "blue" | "green" | "amber" | "red" | "gray"> = {
  perfume: "purple",
  cologne: "blue",
  candle: "amber",
  reed_diffuser: "green",
  room_spray: "red",
  solid_perfume: "gray",
};

const POST_TONE: Record<string, "green" | "blue" | "amber" | "red"> = {
  posted: "green",
  scheduled: "blue",
  skipped: "amber",
  failed: "red",
};

export default function RecipeCard({
  recipe,
  post,
  source,
  heading,
}: {
  recipe: Recipe;
  post?: DailyPost | null;
  source: "stub" | "live-supabase-rest" | "live-postgres";
  heading?: string;
}) {
  const isStub = source === "stub";
  return (
    <article className="panel recipe-card">
      {heading ? <h3 className="card-heading">{heading}</h3> : null}
      <div className="recipe-head">
        <div>
          <h4 className="recipe-name">{recipe.recipe_name}</h4>
          <div className="recipe-meta">
            <Pill tone={CATEGORY_TONE[recipe.category] ?? "gray"}>{recipe.category.replace("_", " ")}</Pill>
            <Pill tone="blue">{recipe.difficulty}</Pill>
            <Pill tone="purple">theme: {recipe.theme}</Pill>
            {recipe.holiday ? <Pill tone="red">{recipe.holiday}</Pill> : null}
            <span className="recipe-slug">{recipe.slug}</span>
          </div>
        </div>
        <div className="recipe-price">
          <div className="price">{money(recipe.price_usd)}</div>
          <div className="muted small">PDF download · {recipe.yield_text}</div>
        </div>
      </div>

      <PreviewStrip recipe={recipe} />

      <div className="recipe-foot">
        <div className="status-line">
          <Pill tone={recipe.status === "listed" ? "green" : recipe.status === "draft_ready" ? "blue" : "gray"}>
            recipe: {recipe.status}
          </Pill>
          {post ? (
            <Pill tone={POST_TONE[post.status] ?? "gray"}>post ({post.date}): {post.status}</Pill>
          ) : null}
        </div>
        {recipe.etsy_url ? (
          <a className="btn" href={recipe.etsy_url} target="_blank" rel="noopener noreferrer">
            View Etsy listing ↗
            {isStub ? <span className="muted"> (sample URL)</span> : null}
          </a>
        ) : (
          <span className="muted small">No Etsy listing yet — this recipe is still in the queue.</span>
        )}
      </div>

      {post && (post.views > 0 || post.favorites > 0 || post.sales > 0) ? (
        <div className="metric-row">
          <div className="mini-stat"><b>{post.views}</b> views</div>
          <div className="mini-stat"><b>{post.favorites}</b> favorites</div>
          <div className="mini-stat"><b>{post.sales}</b> sales</div>
          <div className="mini-stat"><b>{money(post.sales * recipe.price_usd)}</b> est. revenue</div>
          {post.posted_at ? <div className="muted small">posted {fmtDate(post.posted_at.slice(0, 10))}</div> : null}
        </div>
      ) : null}
    </article>
  );
}