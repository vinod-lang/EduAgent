import type { NextConfig } from "next";
const target = process.env.EDUAGENT_API_BACKEND_URL ?? "http://127.0.0.1:8000";
const url = new URL(target);
if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("Configure a backend origin without credentials or a path.");
const config: NextConfig = {
  async rewrites() { return { fallback: [{ source: "/api/v1/:path*", destination: `${url.origin}/api/v1/:path*` }] }; },
  async headers() { return [{ source: "/:path*", headers: [{ key: "X-Content-Type-Options", value: "nosniff" }, { key: "Referrer-Policy", value: "no-referrer" }, { key: "X-Frame-Options", value: "DENY" }] }]; },
};
export default config;
