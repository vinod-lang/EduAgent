import type { Professor, Dashboard, Material, AIStatus, Answer, KnowledgeRequest } from "@/types/api";
const messages: Record<number, string> = {
  401: "Your session has ended. Sign in again to continue.", 403: "This request is not permitted. Refresh your session and try again.",
  404: "This resource is unavailable or you do not have access to it.", 409: "This change conflicts with the current saved state. Review it before retrying.",
  422: "Check your question, selection or required fields and try again.", 503: "The local service is unavailable. Check the backend and try again.",
  500: "EduAgent could not complete this request. Try again later.",
};
export class APIError extends Error {
  constructor(public status: number, public code: string = "REQUEST_FAILED", public requestId?: string) { super(messages[status] ?? "Cannot connect to EduAgent. Check the backend connection and try again."); this.name = "APIError"; }
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
export async function parseError(response: Response): Promise<APIError> {
  let value: unknown; try { value = await response.json(); } catch { /* Untrusted/non-JSON errors use local safe wording. */ }
  const detail = record(value) && record(value.error) ? value.error : {};
  const code = typeof detail.code === "string" && /^[A-Z_]{1,40}$/.test(detail.code) ? detail.code : "REQUEST_FAILED";
  const id = typeof detail.request_id === "string" && /^[0-9a-f-]{36}$/.test(detail.request_id) ? detail.request_id : undefined;
  return new APIError(response.status, code, id);
}
export class APIClient {
  private csrf: string | null = null;
  private csrfPending: Promise<void> | null = null;
  private unauthorized: (() => void) | null = null;
  subscribeUnauthorized(handler: () => void) { this.unauthorized = handler; return () => { this.unauthorized = null; }; }
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}
  clear() { this.csrf = null; this.csrfPending = null; }
  private async raw<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try { response = await this.transport(`/api/v1${path}`, { ...options, credentials: "include", cache: "no-store" }); }
    catch (error) { if (record(error) && error.name === "AbortError") throw error; throw new APIError(0, "NETWORK_ERROR"); }
    if (!response.ok) { const error = await parseError(response); if (response.status === 401) { this.clear(); this.unauthorized?.(); } throw error; }
    return response.json() as Promise<T>;
  }
  private async ensureCSRF() {
    if (this.csrf) return;
    if (!this.csrfPending) this.csrfPending = this.raw<{ csrf_token: string }>("/auth/csrf").then((data) => { this.csrf = data.csrf_token; }).finally(() => { this.csrfPending = null; });
    await this.csrfPending;
  }
  async request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    if (body === undefined) return this.raw<T>(path, { signal });
    await this.ensureCSRF();
    const run = () => this.raw<T>(path, { method: "POST", signal, headers: { "Content-Type": "application/json", "X-CSRF-Token": this.csrf ?? "" }, body: JSON.stringify(body) });
    try { return await run(); } catch (error) {
      // Retry only a CSRF rejection: backend rejected it before domain mutation.
      if (!(error instanceof APIError) || error.code !== "CSRF_REJECTED" || signal?.aborted) throw error;
      this.csrf = null; await this.ensureCSRF(); return run();
    }
  }
  async login(identity: string) { const data = await this.raw<{ csrf_token: string }>("/auth/dev-login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identity }) }); this.csrf = data.csrf_token; }
  async logout() { await this.request("/auth/logout", {}); this.clear(); }
  me(signal?: AbortSignal) { return this.request<Professor>("/auth/me", undefined, signal); }
  dashboard(signal?: AbortSignal) { return this.request<Dashboard>("/dashboard", undefined, signal); }
  materials(signal?: AbortSignal) { return this.request<Material[]>("/materials", undefined, signal); }
  status(signal?: AbortSignal) { return this.request<AIStatus>("/system/ai", undefined, signal); }
  answer(body: KnowledgeRequest, signal?: AbortSignal) { return this.request<Answer>("/knowledge/answer", body, signal); }
}
