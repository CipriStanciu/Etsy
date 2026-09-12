"use client";

// UTM Builder — Pinterest / TikTok / share tracking links for a selected
// recipe. Base URL defaults to the recipe's Etsy listing URL (or a
// dashboard-hosted page), override-able per link.

import { useMemo, useState } from "react";
import { useDashboard } from "@/lib/use-dashboard";
import { buildUtm } from "@/lib/format";
import { CopyButton, ErrorPanel, Loading, Section } from "@/components/ui";

const SOURCE_PRESETS = [
  { label: "Pinterest", source: "pinterest", medium: "pin" },
  { label: "TikTok", source: "tiktok", medium: "video" },
  { label: "Instagram", source: "instagram", medium: "story" },
  { label: "Email", source: "email", medium: "newsletter" },
  { label: "Share", source: "share", medium: "link" },
];

export default function UtmPage() {
  const { data, error, loading } = useDashboard();

  const [recipeId, setRecipeId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [source, setSource] = useState("pinterest");
  const [medium, setMedium] = useState("pin");
  const [campaign, setCampaign] = useState("");
  const [content, setContent] = useState("");
  const [showShare, setShowShare] = useState(true);

  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data.recipes].sort((a, b) => a.recipe_name.localeCompare(b.recipe_name));
  }, [data]);

  const preferId = useMemo(() => {
    if (!data) return "";
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
      today.getDate(),
    ).padStart(2, "0")}`;
    const todayPost = data.daily_posts.find((p) => p.date === todayIso);
    return (
      (todayPost && data.recipes.find((r) => r.id === todayPost.recipe_id)?.id) ||
      data.recipes.find((r) => r.status === "listed")?.id ||
      data.recipes[0]?.id ||
      ""
    );
  }, [data]);

  const recipe = sorted.find((r) => r.id === (recipeId || preferId)) || sorted[0];

  const effectiveCampaign = campaign || (recipe ? recipe.slug : "");

  const defaultBase = useMemo(() => {
    if (!recipe) return "";
    if (recipe.etsy_url) return recipe.etsy_url;
    const base = (process.env.NEXT_PUBLIC_DASHBOARD_URL || "").replace(/\/+$/, "");
    if (base) return `${base}/recipe/${recipe.slug}`;
    return typeof window !== "undefined" ? `${window.location.origin}/recipe/${recipe.slug}` : "";
  }, [recipe]);

  const effectiveBase = baseUrl || defaultBase;

  const links = showShare
    ? SOURCE_PRESETS.map((p) => ({
        label: p.label,
        url: buildUtm(effectiveBase || "https://www.etsy.com", {
          source: p.source,
          medium: p.medium,
          campaign: effectiveCampaign,
          content,
        }),
      }))
    : [];

  let body;
  if (loading) {
    body = <Loading />;
  } else if (error || !data) {
    body = <ErrorPanel message={error || "no data"} />;
  } else if (!recipe) {
    body = <div className="panel muted">No recipes loaded.</div>;
  } else {
    body = (
      <>
        <section className="panel">
          <div className="form-grid">
            <div className="form-field">
              <label className="field-label" htmlFor="utm-recipe">Recipe</label>
              <select
                id="utm-recipe"
                className="select"
                value={recipe.id}
                onChange={(e) => {
                  const r = sorted.find((x) => x.id === e.target.value);
                  setRecipeId(e.target.value);
                  if (r) setCampaign(r.slug);
                }}
              >
                {sorted.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.recipe_name} — {r.status}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field form-field-wide">
              <label className="field-label" htmlFor="utm-base">
                Base URL (default: the recipe&apos;s Etsy listing, or dashboard-hosted page)
              </label>
              <input
                id="utm-base"
                className="input"
                type="url"
                value={effectiveBase}
                placeholder={defaultBase}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="utm-source">utm_source</label>
              <input id="utm-source" className="input" value={source} onChange={(e) => setSource(e.target.value)} />
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="utm-medium">utm_medium</label>
              <input id="utm-medium" className="input" value={medium} onChange={(e) => setMedium(e.target.value)} />
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="utm-campaign">utm_campaign</label>
              <input id="utm-campaign" className="input" value={effectiveCampaign} onChange={(e) => setCampaign(e.target.value)} />
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="utm-content">utm_content (optional)</label>
              <input id="utm-content" className="input" value={content} placeholder="e.g. hero-image" onChange={(e) => setContent(e.target.value)} />
            </div>
          </div>

          <div className="preset-row">
            <span className="muted small">Quick presets:</span>
            {SOURCE_PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                className={`btn btn-small${p.source === source && p.medium === medium ? " btn-active" : ""}`}
                onClick={() => {
                  setSource(p.source);
                  setMedium(p.medium);
                }}
              >
                {p.label}
              </button>
            ))}
            <label className="toggle">
              <input type="checkbox" checked={showShare} onChange={(e) => setShowShare(e.target.checked)} />
              <span className="muted small">show all preset links</span>
            </label>
          </div>
        </section>

        <Section
          title="Generated links"
          sub={`${recipe.recipe_name} (${recipe.status}) — $${recipe.price_usd.toFixed(2)}`}
        >
          {links.length === 0 ? (
            <div className="panel muted">Toggle “show all preset links” to render them.</div>
          ) : (
            <ul className="utm-list">
              {links.map((l) => (
                <li key={l.label} className="utm-row">
                  <span className="utm-label">{l.label}</span>
                  <code className="utm-url" title={l.url}>{l.url}</code>
                  <CopyButton text={l.url} />
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            Base URL: {effectiveBase || "(no recipe Etsy URL — enter a base)"} · default campaign:{" "}
            {effectiveCampaign || recipe.slug}
          </p>
        </Section>
      </>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>UTM Builder</h1>
        <p className="muted">
          Pinterest / TikTok / share tracking links — appends <code>utm_source</code>,{" "}
          <code>utm_medium</code>, <code>utm_campaign</code> (+ optional{" "}
          <code>utm_content</code>) for attribution.
        </p>
      </header>
      {body}
    </div>
  );
}