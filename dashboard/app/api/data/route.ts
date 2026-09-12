// GET /api/data — single source-of-truth endpoint. Resolves live Supabase data
// when credentials are present, otherwise the bundled stub snapshot. The UI
// labels whichever source was used; stub data is never presented as live.

import { NextResponse } from "next/server";
import { loadDashboardData } from "@/lib/data";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    const payload = await loadDashboardData();
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 },
    );
  }
}