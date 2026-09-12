// SEO Scorecard page. Plain client-page pattern (header + client body, no
// Suspense, no useSearchParams — ?slug= is read from window.location) so the
// header renders in SSR HTML and the page builds like the other dashboard pages.

import SeoClient from "./seo-client";

export default function SeoPage() {
  return (
    <div className="page">
      <header className="page-head">
        <h1>SEO Scorecard</h1>
        <p className="muted">
          Per-recipe checks computed from the recipe JSON: title ≤ 140 chars, exactly 13 tags,
          each tag ≤ 20 chars, description word count.
        </p>
      </header>
      <SeoClient />
    </div>
  );
}
