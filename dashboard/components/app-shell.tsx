"use client";

// Global shell: top nav, data-source banner, content area, footer.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useDashboard } from "@/lib/use-dashboard";
import type { ReactNode } from "react";

const LINKS: Array<[string, string]> = [
  ["/", "Today"],
  ["/calendar", "Calendar"],
  ["/metrics", "Metrics"],
  ["/alerts", "Alerts"],
  ["/seo", "SEO"],
  ["/utm", "UTM"],
];

function SourceBanner() {
  const { data, loading, error } = useDashboard();
  if (loading) return <div className="banner banner-gray">Loading data source…</div>;
  if (error || !data) {
    return (
      <div className="banner banner-red" role="alert">
        <span className="banner-dot" aria-hidden />
        DATA SOURCE ERROR — {error || "no data"}
      </div>
    );
  }
  if (data.source === "stub") {
    return (
      <div className="banner banner-amber">
        <span className="banner-dot" aria-hidden />
        <strong>DATA SOURCE: STUB</strong> — showing the bundled sample snapshot
        (dashboard/data/stub.json), not live Etsy/Supabase data. Set SUPABASE_URL +
        SUPABASE_SERVICE_ROLE_KEY (or POSTGRES_URL) to go live. Sample snapshot generated{" "}
        {data.generated_at ? new Date(data.generated_at).toLocaleString() : ""} (
        {data.recipes.length} recipes).
      </div>
    );
  }
  return (
    <div className="banner banner-green">
      <span className="banner-dot" aria-hidden />
      <strong>DATA SOURCE: LIVE</strong> — connected to Supabase (
      {data.source === "live-postgres" ? "Postgres" : "PostgREST"}). {data.recipes.length} recipes,{" "}
      {data.daily_posts.length} daily posts.
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden>
            🌸
          </span>
          Fragrance Bot <span className="brand-sub">Owner Dashboard</span>
        </Link>
        <nav className="nav" aria-label="Dashboard sections">
          {LINKS.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`nav-link${pathname === href ? " nav-active" : ""}`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <SourceBanner />
      <main className="content">{children}</main>
      <footer className="footer">
        Fragrance Bot pipeline · Etsy digital-download recipe cards · free tier only · dashboard
        runs from Supabase (live) or the bundled stub snapshot (no credentials needed)
      </footer>
    </div>
  );
}