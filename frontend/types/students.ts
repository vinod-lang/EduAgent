export type Cell=string|number|boolean|null;
export type Row=Record<string,Cell| string[]>;
export type Preview={columns:string[];rows:Record<string,string|null>[];total_rows:number;suggestions:Record<string,{candidates:string[];confidence:string}>};
export type Mapping={sheet:string;header_row:number;student_id:string|null;student_name:string|null;attendance:string;attendance_scale:string;assessment_number:string|null;assessments:{column:string;name:string;scale:string;maximum:number|null}[]};
export type Normalized={handle:string;validation:Record<string,number>;issues:{row:number;code:string;severity:string}[]};
export type Filters={view:string;search:string;marks_threshold:number;attendance_threshold:number};
export type Analysis={students:Row[];summary:Record<string,Cell|Record<string,number>|string[]>};
export type Detail={student:Row;history:Row[];mode:string};
