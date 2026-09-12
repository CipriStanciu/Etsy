"use client";

// Inventory Alert — when the draft_ready pool drops below 10: clear alert +
// the exact regeneration commands from the README ("Seed the library").

import { useDashboard } from "@/lib/use-dashboard";
import { fmtDate, money } from "@/lib/format";
import { ErrorPanel, Loading, Pill, Section, Stat } from "@/components/ui";

const MIN_QUEUE = 10;

export default function AlertsPage() {
  const { data, error, loading } = useDashboard();

  let body;
  if (loading) {
    body = <Loading />;
  } else if (error || !data) {
    body = <ErrorPanel message={error || "no data"} />;
  } else {
    const count = (s: string) => data.recipes.filter((r) => r.status === s).length;
    const queue = data.recipes
      .filter((r) => r.status === "draft_ready")
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    const low = queue.length < MIN_QUEUE;

    body = (
      <>
        <div className="stat-row">
          <Stat label="draft_ready (runway)" value={queue.length} sub={`min ${MIN_QUEUE}`} />
          <Stat label="draft (library)" value={count("draft")} sub="not yet queued" />
          <Stat label="listed" value={count("listed")} sub="live on Etsy" />
          <Stat label="archived" value={count("archived")} sub="retired" />
        </div>

        {low ? (
          <div className="panel alert alert-red" role="alert">
            <h3>⚠ Inventory low — {queue.length} recipes left in the posting queue</h3>
            <p>
              At one posting per day the queue runs out in <strong>{queue.length} day(s)</strong>.
              Regenerate more recipes from the engine and re-seed Supabase:
            </p>
            <pre className="code-block">{`# from the repo root — regenerate + reseed the library (idempotent, safe to re-run)
python3 seed_recipes.py

# or generate a fresh batch to a folder first (engine batch mode, README §Running):
python3 -m fragbot generate --batch 365 --start 2026-01-01 --outdir seed_library`}</pre>
            <p className="muted small">
              Seed instructions: README → “Seed the library”. Re-running never duplicates rows and
              never touches recipes that already went live.
            </p>
          </div>
        ) : (
          <div className="panel alert alert-green">
            <h3>✓ Inventory healthy — {queue.length} recipes queued</h3>
            <p className="muted">More than {MIN_QUEUE} days of runway. No action needed.</p>
          </div>
        )}

        <Section
          title="Posting queue"
          sub="Oldest first — this is the exact order the cron will post."
        >
          {queue.length === 0 ? (
            <div className="panel muted">Queue is empty — run <code>python3 seed_recipes.py</code>.</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Recipe</th>
                    <th>Theme</th>
                    <th>Category</th>
                    <th>Price</th>
                    <th>Queued since</th>
                    <th>Goes live in</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((r, i) => (
                    <tr key={r.id}>
                      <td>{i + 1}</td>
                      <td>
                        <div className="cell-name">
                          {r.recipe_name}
                          <span className="muted small">{r.slug}</span>
                        </div>
                      </td>
                      <td>{r.theme}</td>
                      <td>{r.category.replace("_", " ")}</td>
                      <td>{money(r.price_usd)}</td>
                      <td>{fmtDate(r.created_at.slice(0, 10))}</td>
                      <td>
                        <Pill tone={i === 0 ? "blue" : "gray"}>{i + 1} day(s)</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Inventory Alerts</h1>
        <p className="muted">
          The daily cron draws one <code>draft_ready</code> recipe per day — the queue size is
          runway in days. Regenerate before it hits {MIN_QUEUE}.
        </p>
      </header>
      {body}
    </div>
  );
}