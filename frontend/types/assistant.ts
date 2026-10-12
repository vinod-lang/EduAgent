export type ActionType='ASK_KNOWLEDGE'|'CREATE_ASSESSMENT'|'CREATE_DOCUMENT'|'ANALYZE_STUDENTS'|'NAVIGATE';
export type PlanAction={action_id:string;action_type:ActionType;parameters:Record<string,unknown>;depends_on:string[]};
export type Plan={handle:string;unsupported:boolean;actions:PlanAction[]};
export type Preview=Plan&{valid:boolean;clarifications:{action_id:string;missing_fields:string[]}[]};
export type Outcome={action_id:string;status:'completed'|'failed'|'blocked'|'cancelled';type:ActionType;summary:string;destination:string|null;answer:string|null;grounded:boolean|null;sources:string[];student_count:number|null};
export type Execution={status:'completed'|'partial_failure'|'failed';results:Outcome[]};
export type ActivityPage={items:{action:string;timestamp:string;category:string}[];next_cursor:number|null};
