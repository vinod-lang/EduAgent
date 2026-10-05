import type { Professor, Dashboard, Material, AIStatus, Answer, KnowledgeRequest, Hierarchy, UploadResult, DeleteResult, MaterialDetail, Assessment, AssessmentRequest, QuestionEdit, DocumentCatalog, DraftMetadata, StudioDocument, DocumentRequest, DocumentEdit, DocumentFact, DocumentChange, DocumentPreference, PreferenceRequest } from "@/types/api";
const messages: Record<number, string> = {
  401: "Your session has ended. Sign in again to continue.", 403: "This request is not permitted. Refresh your session and try again.",
  413: "This file exceeds the API upload limit. Choose a smaller file.",
  404: "This resource is unavailable or you do not have access to it.", 409: "This change conflicts with the current saved state. Review it before retrying.",
  422: "Check your question, selection or required fields and try again.", 503: "The local service is unavailable. Check the backend and try again.",
  500: "EduAgent could not complete this request. Try again later.",
};
export class APIError extends Error {
  constructor(public status: number, public code: string = "REQUEST_FAILED", public requestId?: string, public category?: string) { super(messages[status] ?? "Cannot connect to EduAgent. Check the backend connection and try again."); this.name = "APIError"; }
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
export async function parseError(response: Response): Promise<APIError> {
  let value: unknown; try { value = await response.json(); } catch { /* Untrusted/non-JSON errors use local safe wording. */ }
  const detail = record(value) && record(value.error) ? value.error : {};
  const code = typeof detail.code === "string" && /^[A-Z_]{1,40}$/.test(detail.code) ? detail.code : "REQUEST_FAILED";
  const id = typeof detail.request_id === "string" && /^[0-9a-f-]{36}$/.test(detail.request_id) ? detail.request_id : undefined;
  const category=record(detail.diagnostic)&&typeof detail.diagnostic.category==="string"?detail.diagnostic.category:undefined;
  return new APIError(response.status, code, id, category);
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
  private async mutate<T>(path: string, method: string, body?: object | FormData): Promise<T> {
    await this.ensureCSRF();
    const run = () => this.raw<T>(path, {method, headers: {"X-CSRF-Token": this.csrf ?? "", ...(body instanceof FormData || !body ? {} : {"Content-Type":"application/json"})}, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined});
    try { return await run(); } catch (error) {
      if (!(error instanceof APIError) || error.code !== "CSRF_REJECTED") throw error;
      this.csrf=null; await this.ensureCSRF(); return run();
    }
  }
  material(id: string, signal?: AbortSignal) { return this.request<MaterialDetail>(`/materials/${encodeURIComponent(id)}`,undefined,signal); }
  upload(file: File, hierarchy: Hierarchy) { const form=new FormData();form.append("file",file);for(const [k,v] of Object.entries(hierarchy))form.append(k,v);return this.mutate<UploadResult>("/materials","POST",form); }
  editMaterial(id: string, hierarchy: Hierarchy) { return this.mutate<{success:boolean;status:string}>(`/materials/${encodeURIComponent(id)}`,"PATCH",hierarchy); }
  deleteMaterial(id: string) { return this.mutate<DeleteResult>(`/materials/${encodeURIComponent(id)}`,"DELETE"); }
  generateAssessment(body: AssessmentRequest,signal?:AbortSignal){return this.request<Assessment>("/assessments/generate",body,signal);}
  assessment(handle:string,signal?:AbortSignal){return this.request<Assessment>(`/assessments/${encodeURIComponent(handle)}`,undefined,signal);}
  editAssessment(handle:string,revision:number,questions:QuestionEdit[]){return this.mutate<Assessment>(`/assessments/${encodeURIComponent(handle)}`,"PATCH",{revision,questions});}
  discardAssessment(handle:string){return this.mutate<{status:string}>(`/assessments/${encodeURIComponent(handle)}`,"DELETE");}
  uploadPYQ(file:File){const form=new FormData();form.append("file",file);return this.mutate<{handle:string}>("/assessments/pyq","POST",form);}
  async exportAssessment(handle:string,format:'pdf'|'docx',answerKey:boolean){
    let response:Response;try{response=await this.transport(`/api/v1/assessments/${encodeURIComponent(handle)}/export?format=${format}&answer_key=${answerKey}`,{credentials:"include",cache:"no-store"});}catch{throw new APIError(0,"NETWORK_ERROR");}
    if(!response.ok){const error=await parseError(response);if(response.status===401){this.clear();this.unauthorized?.();}throw error;}return response.blob();
  }
  documentCatalog(signal?:AbortSignal){return this.request<DocumentCatalog>("/documents/catalog",undefined,signal);}
  documents(signal?:AbortSignal){return this.request<DraftMetadata[]>("/documents",undefined,signal);}
  loadDocument(id:string,signal?:AbortSignal){return this.request<StudioDocument>(`/documents/${encodeURIComponent(id)}`,undefined,signal);}
  generateDocument(body:DocumentRequest,signal?:AbortSignal){return this.request<StudioDocument>("/documents/generate",body,signal);}
  reviewDocument(handle:string){return this.request<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}`);}
  editDocument(handle:string,body:DocumentEdit){return this.mutate<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}`,"PATCH",body);}
  saveDocument(handle:string,status:'Draft'|'Final'){return this.request<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}/save`,{status});}
  refineDocument(handle:string,instruction:string,signal?:AbortSignal){return this.request<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}/refine`,{instruction},signal);}
  restoreDocument(handle:string,index:number){return this.request<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}/restore`,{index});}
  compareDocument(handle:string,before:number,after:number){return this.request<DocumentChange[]>(`/document-workspaces/${encodeURIComponent(handle)}/diff?before=${before}&after=${after}`);}
  documentConflicts(handle:string,draft:DocumentEdit){return this.request<DocumentFact[]>(`/document-workspaces/${encodeURIComponent(handle)}/conflicts`,draft);}
  resolveDocument(handle:string,draft:DocumentEdit,update_confirmed:boolean,replacements:Record<string,string>){return this.request<StudioDocument>(`/document-workspaces/${encodeURIComponent(handle)}/resolve-edit`,{draft,update_confirmed,replacements});}
  manageDocumentFact(handle:string,body:{operation:'add'|'update'|'remove';field?:string;value?:string;fact_id?:string}){return this.request<{status:string}>(`/document-workspaces/${encodeURIComponent(handle)}/facts`,body);}
  discardDocument(handle:string){return this.mutate<{status:string}>(`/document-workspaces/${encodeURIComponent(handle)}`,"DELETE");}
  documentFeedback(handle:string,rating:'Good'|'Needs Changes',note:string){return this.request<{status:string}>(`/document-workspaces/${encodeURIComponent(handle)}/feedback`,{rating,note});}
  preferences(signal?:AbortSignal){return this.request<DocumentPreference[]>("/preferences",undefined,signal);}
  approvePreference(body:PreferenceRequest){return this.request<{handle:string}>("/preferences",body);}
  updatePreference(id:string,body:{instruction?:string;active?:boolean}){return this.mutate<{status:string}>(`/preferences/${encodeURIComponent(id)}`,"PATCH",body);}
  deletePreference(id:string){return this.mutate<{status:string}>(`/preferences/${encodeURIComponent(id)}`,"DELETE");}
  async exportDocument(handle:string,format:'pdf'|'docx'){
    let response:Response;try{response=await this.transport(`/api/v1/document-workspaces/${encodeURIComponent(handle)}/export?format=${format}`,{credentials:"include",cache:"no-store"});}catch{throw new APIError(0,"NETWORK_ERROR");}
    if(!response.ok){const error=await parseError(response);if(response.status===401){this.clear();this.unauthorized?.();}throw error;}return response.blob();
  }
  async login(identity: string) { const data = await this.raw<{ csrf_token: string }>("/auth/dev-login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identity }) }); this.csrf = data.csrf_token; }
  async logout() { await this.request("/auth/logout", {}); this.clear(); }
  me(signal?: AbortSignal) { return this.request<Professor>("/auth/me", undefined, signal); }
  dashboard(signal?: AbortSignal) { return this.request<Dashboard>("/dashboard", undefined, signal); }
  materials(signal?: AbortSignal) { return this.request<Material[]>("/materials", undefined, signal); }
  status(signal?: AbortSignal) { return this.request<AIStatus>("/system/ai", undefined, signal); }
  answer(body: KnowledgeRequest, signal?: AbortSignal) { return this.request<Answer>("/knowledge/answer", body, signal); }
}
