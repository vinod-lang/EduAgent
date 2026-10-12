import type {Mapping,Preview} from '@/types/students';
export type MappingRole='student_id'|'student_name'|'attendance'|'assessment_number';
const roles:MappingRole[]=['student_id','student_name','attendance','assessment_number'];
export function initialMapping(p:Preview,sheet:string,header_row:number):Mapping{
 const choice=(r:MappingRole)=>p.suggestions[r]?.candidates.length===1?p.suggestions[r].candidates[0]:null;
 return {sheet,header_row,student_id:choice('student_id'),student_name:choice('student_name'),attendance:choice('attendance')??'',attendance_scale:p.mapping_hints?.attendance_scale??'auto',assessment_number:choice('assessment_number'),assessments:(p.suggestions.assessments?.candidates??[]).map(column=>({column,name:column,scale:p.mapping_hints?.assessments[column]?.scale??'raw',maximum:p.mapping_hints?.assessments[column]?.maximum??null}))};
}
export function roleColumns(p:Preview,role:MappingRole):string[]{
 const reserved=new Set(roles.filter(r=>r!==role).flatMap(r=>p.suggestions[r]?.candidates??[]));
 for(const c of p.suggestions.assessments?.candidates??[])reserved.add(c);
 return p.columns.filter(c=>!reserved.has(c));
}
export function markColumns(p:Preview,m:Mapping):string[]{
 const reserved=new Set(roles.flatMap(r=>p.suggestions[r]?.candidates??[]));
 for(const r of roles)if(m[r])reserved.add(m[r]!);
 return (p.mapping_hints?.assessment_columns??p.suggestions.assessments?.candidates??[]).filter(c=>!reserved.has(c));
}
export function changeRole(m:Mapping,key:MappingRole,value:string):Mapping{
 const next={...m,[key]:value||(key==='attendance'?'':null)};
 if(key!=='student_id'&&next.student_id===value)next.student_id=null;
 if(key!=='student_name'&&next.student_name===value)next.student_name=null;
 if(key!=='attendance'&&next.attendance===value)next.attendance='';
 if(key!=='assessment_number'&&next.assessment_number===value)next.assessment_number=null;
 return {...next,assessments:next.assessments.filter(a=>!value||a.column!==value)};
}
