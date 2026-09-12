"use client";

// Small dependency-free UI primitives.

import { useState, type ReactNode } from "react";

export type Tone = "green" | "amber" | "red" | "blue" | "gray" | "purple";

const TONE_CLASS: Record<Tone, string> = {
  green: "pill-green",
  amber: "pill-amber",
  red: "pill-red",
  blue: "pill-blue",
  gray: "pill-gray",
  purple: "pill-purple",
};

export function Pill({ tone = "gray", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`pill ${TONE_CLASS[tone]}`}>{children}</span>;
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

export function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>{title}</h2>
        {sub ? <p className="section-sub">{sub}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function Loading() {
  return <div className="panel muted">Loading dashboard data…</div>;
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="panel error" role="alert">
      <strong>Could not load dashboard data.</strong>
      <p>{message}</p>
      <p className="muted">
        Without credentials the dashboard falls back to the bundled sample snapshot — make sure
        <code> dashboard/data/stub.json</code> exists or set <code>SUPABASE_URL</code> +{" "}
        <code>SUPABASE_SERVICE_ROLE_KEY</code> (or <code>POSTGRES_URL</code>) in{" "}
        <code>.env.local</code>.
      </p>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button type="button" className="btn btn-small" onClick={onCopy}>
      {copied ? "✓ Copied" : label}
    </button>
  );
}