export interface Professor { professor_id: string; display_name: string; institution_id: string; department_id: string }
export interface Material { material_id: string; filename: string; course: string; semester: string; subject: string; unit: string; created_at: string }
export interface DraftMetadata { document_id: string; template_id: string; created_at: string; updated_at: string; status: string; title?:string; document_type?:string; version_count?:number }
export interface Activity { actor_professor_id: string; action: string; timestamp: string }
export interface Dashboard { material_count: number; courses: string[]; materials: Material[]; saved_drafts: DraftMetadata[]; activity: Activity[] }
export interface AIStatus { provider: string; preferred_model: string; effective_model: string | null; fallback_active: boolean | null; embedding: string; candidate_k: number; final_k: number; threshold: number; reranker: boolean; router: boolean }
export interface Source { source: string; material_id: string | null }
export interface Answer { answer: string; grounded: boolean; sources: Source[] }
export type Scope = Partial<Record<"course" | "semester" | "subject" | "unit" | "material_id", string>>;
export interface KnowledgeRequest { question: string; filters: Scope }

export type Hierarchy = Record<"course"|"semester"|"subject"|"unit", string>;
export interface UploadResult { success: boolean; duplicate: boolean; material: Material|null; message: string }
export interface DeleteResult { success: boolean; sqlite_deleted: boolean|null; vectors_deleted: number|null; file_deleted: boolean|null }

export interface MaterialDetail extends Material { visibility: "PRIVATE"|"COURSE"|"DEPARTMENT"|"INSTITUTE"; can_manage: boolean }

export interface AssessmentQuestion {question_number:number;question_type:'MCQ'|'Descriptive';question_text:string;options:Record<string,string>;correct_answer:string;model_answer:string;difficulty:string;bloom_level:string;marks:number}
export interface Assessment {handle:string;title:string;assessment_type:'Quiz'|'Question Paper';total_marks:number;questions:AssessmentQuestion[];revision:number;professor_edited:boolean;validation:Record<string,boolean>}
export interface AssessmentRequest {assessment_type:'Quiz'|'Question Paper';course:string;semester:string;subject:string;units:string[];material_ids:string[];question_types:Record<string,number>;difficulties:Record<string,number>;blooms:Record<string,number>;total_questions:number;total_marks:number;title:string;institution:string;instructions:string;topic:string;pyq_handle:string|null}
export type QuestionEdit=Pick<AssessmentQuestion,'question_text'|'marks'|'options'|'correct_answer'|'model_answer'>;

export interface DocumentCatalog {types:{value:string;label:string;style:string}[];tones:string[];fields:string[];fact_fields:string[];preference_scopes:string[];preference_categories:string[]}
export interface DocumentEdit {title:string;recipient:string;sender:string;date:string;reference_number:string;subject:string;salutation:string;body:string[];closing:string;signature:string}
export interface DocumentRequest {document_type:string;description:string;tone:string;template_id:string;recipient:string;sender:string;title:string;date:string;reference_number:string;subject:string;signature:string;additional_context:string}
export interface DocumentFact {fact_id:string;field:string;value:string;source:string}
export interface DocumentVersion {version_number:number;source:string;created_at:string}
export interface DocumentProvenance {generation_type:string;generated_at:string;validation_status:string;attempts_used:number;model:string;provider:string;grounded:boolean;professor_edited:boolean;preferences_applied:boolean}
export interface StudioDocument extends DocumentEdit {handle:string;document_id:string|null;document_type:string;version_count:number;saved:boolean;status:string|null;versions:DocumentVersion[];facts:DocumentFact[];provenance:DocumentProvenance|null}
export interface DocumentChange {field:string;action:string;before:string[];after:string[]}
export interface DocumentPreference {preference_id:string;instruction:string;category:string;scope:string;active:boolean;approved:boolean;document_type:string|null;template_id:string|null;tone:string|null}
export interface PreferenceRequest {instruction:string;category:string;scope:string;document_type:string|null;template_id:string|null;tone:string|null}
