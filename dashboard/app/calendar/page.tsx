"use client";

// 30-day content calendar — the next 30 days, each showing the recipe the
// engine plans for that date (deterministic: date → recipe), overridden by the
// DB's scheduled/posted row when one exists, plus status.

import { useDashboard } from "@/lib/use-dashboard";
import { addDays, enginePlanIndex, fmtDate, todayISO, daysBetween } from "@/lib/format";
import { SEED_START } from "@/lib/types";
import { ErrorPanel, Loading, Pill, Section } from "@/components/ui";

const DAYS = 30;

export default function CalendarPage() {
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

    const days = Array.from({ length: DAYS }, (_, i) => addDays(today, i));

    const cellFor = (iso: string) => {
      const post = postsByDate.get(iso);
      const recipe = post ? byId.get(post.recipe_id) : undefined;
      const planIdx = post ? null : enginePlanIndex(iso, data.recipes.length);
      const planned = recipe ?? (planIdx !== null ? data.recipes[planIdx] : undefined);
      return { post, planned };
    };

    const posted = data.daily_posts.filter((p) => p.status === "posted").length;

    body = (
      <>
        <div className="cal-grid">
          {days.map((iso) => {
            const { post, planned } = cellFor(iso);
            const isToday = iso === today;
            const dayNum = daysBetween(today, iso);
            return (
              <div key={iso} className={`cal-cell${isToday ? " cal-today" : ""}`}>
                <div className="cal-date">
                  <span className="cal-day">{fmtDate(iso)}</span>
                  {isToday ? <Pill tone="green">today</Pill> : null}
                  {dayNum > 0 ? <span className="muted small">+{dayNum}d</span> : null}
                </div>
                {planned ? (
                  <>
                    <div className="cal-recipe" title={planned.full_title}>
                      {planned.recipe_name}
                    </div>
                    <div className="cal-meta muted">
                      {planned.category.replace("_", " ")} · ${planned.price_usd.toFixed(2)}
                    </div>
                    <div className="cal-pills">
                      {post ? (
                        <Pill tone={post.status === "posted" ? "green" : post.status === "failed" ? "red" : "blue"}>
                          {post.status}
                        </Pill>
                      ) : (
                        <Pill tone="gray">planned</Pill>
                      )}
                      {post && post.views > 0 ? (
                        <span className="muted small">{post.views} views</span>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="muted small">— no recipe available</div>
                )}
              </div>
            );
          })}
        </div>

        <Section title="How this is computed" sub="Transparency for the owner — nothing hidden.">
          <ul className="plain-list">
            <li>
              <strong>Posted / scheduled</strong> — read from the <code>daily_posts</code> table
              (written by the 8 AM cron).
            </li>
            <li>
              <strong>Planned</strong> — no DB row yet; the engine generates one deterministic recipe
              per date (<code>generate_recipe(date)</code>), so the calendar previews exactly what
              will run.
            </li>
            <li>
              <strong>{posted} posts</strong> are recorded in the current window.
            </li>
          </ul>
        </Section>
      </>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Content Calendar</h1>
        <p className="muted">
          Next {DAYS} days from {fmtDate(todayISO(), true)} · engine-deterministic plan (date →
          recipe, from {SEED_START}), completed by DB rows where they exist.
        </p>
      </header>
      {body}
    </div>
  );
}