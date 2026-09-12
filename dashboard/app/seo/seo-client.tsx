"use client";

// SEO scorecard body (client) — per-recipe checks computed client-side from
// the recipe JSON: title ≤ 140, exactly 13 tags, tags ≤ 20 chars, description
// word count. No useSearchParams (reads ?slug= from window.location) so this
// page builds and SSRs like a plain client page.

import { useMemo, useState } from "react";
import { useDashboard } from "@/lib/use-dashboard";
import { fmtDate, money, seoScore } from "@/lib/format";
import { ErrorPanel, Loading, Pill, Section, Stat } from "@/components/ui";
import type { Recipe } from "@/lib/types";

export default function SeoClient() {
  const { data, error, loading } = useDashboard();

  const [selected, setSelected] = useState<string>("");
  const [requestedSlug] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("slug") || "";
  });

  const sorted = useMemo(() => {
    if (!data) return [] as Recipe[];
    return [...data.recipes].sort((a, b) => a.recipe_name.localeCompare(b.recipe_name));
  }, [data]);

  const preferId = useMemo(() => {
    if (!data) return "";
    if (requestedSlug) {
      const hit = data.recipes.find((r) => r.slug === requestedSlug);
      if (hit) return hit.id;
    }
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
      today.getDate(),
    ).padStart(2, "0")}`;
    const todayPost = data.daily_posts.find((p) => p.date === todayIso);
    if (todayPost) {
      const hit = data.recipes.find((r) => r.id === todayPost.recipe_id);
      if (hit) return hit.id;
    }
    return data.recipes.find((r) => r.status === "listed")?.id || data.recipes[0]?.id || "";
  }, [data, requestedSlug]);

  const effective = selected || preferId;
  const recipe = sorted.find((r) => r.id === effective) || sorted[0];
  const result = recipe ? seoScore(recipe) : null;

  if (loading) return <Loading />;
  if (error || !data) return <ErrorPanel message={error || "no data"} />;
  if (!recipe || !result) return <div className="panel muted">No recipes loaded.</div>;

  return (
    <>
      <div className="panel">
        <label className="field-label" htmlFor="recipe-pick">
          Recipe
        </label>
        <select
          id="recipe-pick"
          className="select"
          value={recipe.id}
          onChange={(e) => setSelected(e.target.value)}
        >
          {sorted.map((r) => (
            <option key={r.id} value={r.id}>
              {r.recipe_name} — {r.category} ({r.status})
            </option>
          ))}
        </select>
      </div>

      <Section title={recipe.recipe_name} sub={recipe.full_title}>
        <div className="stat-row">
          <Stat label="SEO score" value={`${result.score}%`} sub={result.score === 100 ? "all checks pass" : "fix failing checks →"} />
          <Stat label="Title length" value={`${result.titleLength}/140`} sub={result.titleLength <= 140 ? "within Etsy limit" : "OVER Etsy limit"} />
          <Stat label="Tags" value={`${result.tagCount}/13`} sub={`longest ${result.maxTagLength}/20 chars`} />
          <Stat label="Description" value={`${result.descriptionWords} words`} sub={result.descriptionWords >= 120 ? "≥ 120 recommended" : "short — aim for ≥ 120"} />
        </div>

        <div className="score-bar" aria-label={`SEO score ${result.score}%`}>
          <div
            className={`score-fill ${result.score >= 80 ? "fill-green" : result.score >= 50 ? "fill-amber" : "fill-red"}`}
            style={{ width: `${result.score}%` }}
          />
        </div>

        <ul className="check-list">
          {result.checks.map((c) => (
            <li key={c.key} className={c.pass ? "check-pass" : "check-fail"}>
              <span className="check-icon" aria-hidden>
                {c.pass ? "✓" : "✗"}
              </span>
              <span className="check-label">{c.label}</span>
              <span className="check-detail muted">{c.detail}</span>
            </li>
          ))}
        </ul>

        <div className="tag-grid">
          {recipe.tags.map((t, i) => (
            <span key={i} className={`tag-chip${t.length > 20 ? " tag-over" : ""}`}>
              {t} <em>{t.length}/20</em>
            </span>
          ))}
        </div>

        <div className="meta-grid muted small">
          <span>slug: {recipe.slug}</span>
          <span>{recipe.theme} · {recipe.difficulty} · {money(recipe.price_usd)}</span>
          <span>{recipe.status} · created {fmtDate(recipe.created_at.slice(0, 10))}</span>
        </div>
      </Section>

      <p className="muted small">
        Checklist mirrors the engine&apos;s SEO module (<code>fragbot/seo.py</code>), which
        enforces title / tag / description limits at generation time; the scorecard re-checks
        whatever is in the DB so edits or manual listings are caught.
      </p>
    </>
  );
}