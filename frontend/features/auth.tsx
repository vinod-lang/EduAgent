"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { APIClient, APIError } from "@/lib/api";
import type { Professor } from "@/types/api";
type Session = { status: "loading" | "unauthenticated" | "error"; message?: string } | { status: "authenticated"; professor: Professor };
type Auth = { session: Session; client: APIClient; ready: boolean; refresh: () => Promise<void>; login: (alias: string) => Promise<void>; logout: () => Promise<void> };
const Context = createContext<Auth | null>(null);
export function AuthProvider({ children, api }: { children: React.ReactNode; api?: APIClient }) {
  const [client] = useState(() => api ?? new APIClient());
  const [session, setSession] = useState<Session>({ status: "loading" });
  const [verifiedPath, setVerifiedPath] = useState<string | null>(null);
  const pathname = usePathname(); const router = useRouter(); const pending = useRef<AbortController | null>(null);
  const expire = useCallback(() => { pending.current?.abort(); client.clear(); setSession({ status: "unauthenticated", message: "Sign in to continue. Your session may have expired." }); setVerifiedPath(null); }, [client]);
  const refresh = useCallback(async (background = false) => {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    if (!background) { setSession({ status: "loading" }); setVerifiedPath(null); }
    try { const professor = await client.me(controller.signal); if (!controller.signal.aborted) { setSession({ status: "authenticated", professor }); setVerifiedPath(pathname); } }
    catch (error) { if (!controller.signal.aborted) { setSession(error instanceof APIError && error.status === 401 ? { status: "unauthenticated" } : { status: "error", message: "Cannot verify your session. Check the backend connection and retry." }); } }
  }, [client, pathname]);
  useEffect(() => client.subscribeUnauthorized(expire), [client, expire]);
  useEffect(() => { let active = true; queueMicrotask(() => { if (active) void refresh(); }); return () => { active = false; pending.current?.abort(); }; }, [refresh]);
  useEffect(() => { const check = () => { void refresh(true); }; window.addEventListener("focus", check); return () => window.removeEventListener("focus", check); }, [refresh]);
  const login = useCallback(async (alias: string) => { await client.login(alias); await refresh(); }, [client, refresh]);
  const logout = useCallback(async () => {
    try { await client.logout(); } catch (error) { if (!(error instanceof APIError && error.status === 401)) throw error; }
    expire(); router.replace("/login");
  }, [client, expire, router]);
  return <Context.Provider value={{ session, client, ready: session.status === "authenticated" && verifiedPath === pathname, refresh: () => refresh(), login, logout }}>{children}</Context.Provider>;
}
export function useAuth() { const value = useContext(Context); if (!value) throw new Error("AuthProvider is required."); return value; }
