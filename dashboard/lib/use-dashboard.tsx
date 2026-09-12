"use client";

// Shared client data hook: fetches /api/data once, exposes it via context so
// the source banner and every page read the same snapshot.

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { DashboardData } from "./types";

export interface DataState {
  data: DashboardData | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

const Ctx = createContext<DataState>({ data: null, error: null, loading: true, refresh: () => {} });

export function DataProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/data", { cache: "no-store" });
      if (!res.ok) throw new Error(`API responded ${res.status}`);
      const payload = (await res.json()) as DashboardData;
      setData(payload);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return <Ctx.Provider value={{ data, error, loading, refresh: load }}>{children}</Ctx.Provider>;
}

export function useDashboard(): DataState {
  return useContext(Ctx);
}