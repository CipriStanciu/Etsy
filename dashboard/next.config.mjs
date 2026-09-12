import path from "node:path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `pg` (Postgres driver) must stay a server-side, un-bundled external package
  // and must never reach the client bundle (service-role credentials).
  serverExternalPackages: ["pg"],
  webpack: (config) => {
    // Explicit `@/*` -> project root alias (mirrors tsconfig paths; keeps the
    // resolver deterministic across Next versions).
    const root = process.cwd();
    config.resolve.alias = { ...config.resolve.alias, "@": root };
    return config;
  },
};

export default nextConfig;