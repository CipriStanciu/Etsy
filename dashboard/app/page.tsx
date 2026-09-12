"use client";

// Daily Post Tracker — which recipe went live today (or next in queue), the
// direct Etsy listing URL, the 5 image previews and status.

import { useDashboard } from "@/lib/use-dashboard";
import { addDays, fmtDate, money, todayISO } from "@/lib/format";
import { ErrorPanel, Loading, Pill, Section, Stat } from "@/components/ui";
import RecipeCard from "@/components/recipe-card";

export default function DailyTrackerPage() {
  const { data, error, loading } = useDashboard();

  let body;
  if (loading) {
    body = <Loading />;
  } else if (error || !data) {
    body = <ErrorPanel message={error || "no data"} />;
  } else {
    const today = todayISO();
    const postsByDate = new Map(data.daily_posts.map((p) => [p.date, p]));
    const byId = new Map(data.recipes.map((r) => [r.id, r]));

    const todayPost = postsByDate.get(today);
    const todayRecipe = todayPost ? byId.get(todayPost.recipe_id) : undefined;

    const queue = data.recipes
      .filter((r) => r.status === "draft_ready")
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    const nextInQueue = queue[0];

    const yesterdayPost = postsByDate.get(addDays(today, -1));
    const yesterdayRecipe = yesterdayPost ? byId.get(yesterdayPost.recipe_id) : undefined;

    const postedCount = data.recipes.filter((r) => r.status === "listed").length;

    body = (
      <>
        <div className="stat-row">
          <Stat label="Listings live" value={postedCount} sub={`${data.recipes.length} recipes in library`} />
          <Stat label="In queue (draft_ready)" value={queue.length} sub={queue.length < 10 ? "below 10 — see Alerts" : "healthy"} />
          <Stat label="Posts recorded" value={data.daily_posts.length} sub={`${data.daily_posts.filter((p) => p.status === "posted").length} posted`} />
        </div>

        <Section
          title="Today's listing"
          sub="The recipe the pipeline posted today (8 AM cron), with its listing images and live URL."
        >
          {todayRecipe && todayPost ? (
            <RecipeCard recipe={todayRecipe} post={todayPost} source={data.source} heading={`${fmtDate(today)} — ${todayPost.status}`} />
          ) : todayRecipe ? (
            <RecipeCard recipe={todayRecipe} source={data.source} heading={`${fmtDate(today)} — no post recorded yet`} />
          ) : (
            <div className="panel muted">
              No post recorded for {fmtDate(today)}. {yesterdayRecipe && yesterdayPost ? (
                <>Yesterday&apos;s listing was <strong>{yesterdayRecipe.recipe_name}</strong> (status {yesterdayPost.status}).</>
              ) : null}{" "}
              The cron writes this row when it runs at 08:00 UTC.
            </div>
          )}
        </Section>

        <Section title="Next in queue" sub="Oldest draft_ready recipe — the one the next cron run will post.">
          {nextInQueue ? (
            <div className="panel queue-row">
              <div className="queue-main">
                <h4>{nextInQueue.recipe_name}</h4>
                <div className="recipe-meta">
                  <Pill tone="blue">{nextInQueue.category.replace("_", " ")}</Pill>
                  <Pill tone="purple">{nextInQueue.theme}</Pill>
                  <Pill tone="gray">{nextInQueue.difficulty}</Pill>
                  <span className="recipe-slug">{nextInQueue.slug}</span>
                </div>
              </div>
              <div className="queue-side">
                <div className="price">{money(nextInQueue.price_usd)}</div>
                <div className="muted small">queued {fmtDate(nextInQueue.created_at.slice(0, 10))}</div>
              </div>
              <a className="btn" href={`/seo?slug=${encodeURIComponent(nextInQueue.slug)}`}>
                SEO scorecard →
              </a>
            </div>
          ) : (
            <div className="panel error">
              <strong>Queue empty.</strong> No draft_ready recipes remain — regenerate the library with{" "}
              <code>python3 seed_recipes.py</code> (see the Alerts page).
            </div>
          )}
        </Section>
      </>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Daily Post Tracker</h1>
        <p className="muted">Today: <strong>{fmtDate(todayISO(), true)}</strong></p>
      </header>
      {body}
    </div>
  );
}