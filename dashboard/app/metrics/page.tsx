"use client";

// Performance Metrics — totals (listings, revenue, engagement) and the
// top-performing recipes. Figures come from daily_posts (views / favorites /
// sales), the fields the pipeline reserves for manual or future Etsy sync.

import { useDashboard } from "@/lib/use-dashboard";
import { engagement, fmtDate, money } from "@/lib/format";
import { ErrorPanel, Loading, Pill, Section, Stat } from "@/components/ui";
import type { DailyPost, Recipe } from "@/lib/types";

export default function MetricsPage() {
  const { data, error, loading } = useDashboard();

  let body;
  if (loading) {
    body = <Loading />;
  } else if (error || !data) {
    body = <ErrorPanel message={error || "no data"} />;
  } else {
    const byId = new Map(data.recipes.map((r) => [r.id, r]));
    const posted = data.daily_posts.filter((p) => p.status === "posted");

    const totalViews = posted.reduce((s, p) => s + p.views, 0);
    const totalFavorites = posted.reduce((s, p) => s + p.favorites, 0);
    const totalSales = posted.reduce((s, p) => s + p.sales, 0);
    const totalRevenue = posted.reduce((s, p) => {
      const r = byId.get(p.recipe_id);
      return s + (r ? r.price_usd * p.sales : 0);
    }, 0);
    const avgPrice = data.recipes.length
      ? data.recipes.reduce((s, r) => s + r.price_usd, 0) / data.recipes.length
      : 0;

    const top = posted
      .map((p): { post: DailyPost; recipe: Recipe | undefined } => ({
        post: p,
        recipe: byId.get(p.recipe_id),
      }))
      .filter((x): x is { post: DailyPost; recipe: Recipe } => Boolean(x.recipe))
      .sort((a, b) => engagement(b.post) - engagement(a.post))
      .slice(0, 12);

    body = (
      <>
        <div className="stat-row">
          <Stat label="Total listings" value={data.recipes.filter((r) => r.status === "listed").length} sub={`${posted.length} posted rows`} />
          <Stat label="Total revenue (est.)" value={money(totalRevenue)} sub={`from ${totalSales} sales × price`} />
          <Stat label="Total views" value={totalViews} sub={`${totalFavorites} favorites`} />
          <Stat label="Avg. list price" value={money(avgPrice)} sub="library-wide" />
        </div>

        <Section
          title="Top-performing recipes"
          sub="Ranked by engagement (views + 3× favorites + 10× sales)."
        >
          {top.length === 0 ? (
            <div className="panel muted">No posted performance data yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Recipe</th>
                    <th>Posted</th>
                    <th>Views</th>
                    <th>Favorites</th>
                    <th>Sales</th>
                    <th>Est. revenue</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {top.map(({ post, recipe }, i) => (
                    <tr key={post.date}>
                      <td>{i + 1}</td>
                      <td>
                        <div className="cell-name">
                          {recipe.etsy_url && data.source !== "stub" ? (
                            <a href={recipe.etsy_url} target="_blank" rel="noopener noreferrer">
                              {recipe.recipe_name}
                            </a>
                          ) : (
                            recipe.recipe_name
                          )}
                          <span className="muted small">
                            {recipe.theme} · {recipe.category.replace("_", " ")}
                          </span>
                        </div>
                      </td>
                      <td>{fmtDate(post.date)}</td>
                      <td>{post.views}</td>
                      <td>{post.favorites}</td>
                      <td>{post.sales}</td>
                      <td>{money(post.sales * recipe.price_usd)}</td>
                      <td>
                        <Pill tone={post.status === "posted" ? "green" : "gray"}>{post.status}</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small">
            Revenue/views/favorites are seeded from the <code>daily_posts</code> table — updated
            via <code>update_daily_post_metrics</code>, manually or by a future Etsy sync once
            live postings begin.
          </p>
        </Section>
      </>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Performance Metrics</h1>
        <p className="muted">
          From <code>daily_posts</code>: listings, revenue (sales × price), views / favorites /
          sales, top performers.
        </p>
      </header>
      {body}
    </div>
  );
}