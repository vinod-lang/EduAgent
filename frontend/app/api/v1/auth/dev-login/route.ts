import { NextRequest, NextResponse } from "next/server";
import { developmentLoginEnabled, developmentAliases } from "@/lib/development";
export const dynamic = "force-dynamic";
function rejected(status: number) { return NextResponse.json({ error: { code: "DEV_LOGIN_UNAVAILABLE", message: "Development sign-in is unavailable." } }, { status }); }
export async function POST(request: NextRequest) {
  if (!developmentLoginEnabled() || !process.env.EDUAGENT_DEV_ACCESS_KEY) return rejected(403);
  // Same-origin browser JSON only. Server secret never enters browser props/bundles.
  if (request.headers.get("origin") !== `${request.nextUrl.protocol}//${request.headers.get("host")}` || !request.headers.get("content-type")?.startsWith("application/json")) return rejected(403);
  let body: unknown; try { const raw = await request.text(); if (raw.length > 1024) return rejected(422); body = JSON.parse(raw); } catch { return rejected(422); }
  if (!body || typeof body !== "object" || Object.keys(body).length !== 1 || !("identity" in body) || typeof body.identity !== "string" || !developmentAliases().includes(body.identity)) return rejected(401);
  try {
    const response = await fetch(`${process.env.EDUAGENT_API_BACKEND_URL ?? "http://127.0.0.1:8000"}/api/v1/auth/dev-login`, { method: "POST", cache: "no-store", signal: AbortSignal.timeout(10000), headers: { "Content-Type": "application/json", "X-Development-Key": process.env.EDUAGENT_DEV_ACCESS_KEY, "Origin": request.headers.get("origin")!, ...(request.headers.get("cookie") ? { Cookie: request.headers.get("cookie")! } : {}) }, body: JSON.stringify(body) });
    if (!response.ok) return rejected(response.status === 401 || response.status === 403 ? response.status : 503);
    const data: unknown = await response.json();
    if (!data || typeof data !== "object" || !("csrf_token" in data) || typeof data.csrf_token !== "string") return rejected(503);
    const result = NextResponse.json({ csrf_token: data.csrf_token }, { headers: { "Cache-Control": "no-store" } });
    for (const cookie of response.headers.getSetCookie()) result.headers.append("Set-Cookie", cookie);
    return result;
  } catch { return rejected(503); }
}
