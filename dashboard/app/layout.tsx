import type { Metadata } from "next";
import "./globals.css";
import { DataProvider } from "@/lib/use-dashboard";
import AppShell from "@/components/app-shell";

export const metadata: Metadata = {
  title: "Fragrance Bot — Owner Dashboard",
  description:
    "Private dashboard for the Fragrance Bot daily Etsy posting pipeline: daily post tracker, 30-day calendar, performance metrics, inventory alerts, SEO scorecard and UTM builder.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <DataProvider>
          <AppShell>{children}</AppShell>
        </DataProvider>
      </body>
    </html>
  );
}