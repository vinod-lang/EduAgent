export interface Professor { professor_id: string; display_name: string; institution_id: string; department_id: string }
export interface Material { material_id: string; filename: string; course: string; semester: string; subject: string; unit: string; created_at: string }
export interface DraftMetadata { document_id: string; template_id: string; created_at: string; updated_at: string; status: string }
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
