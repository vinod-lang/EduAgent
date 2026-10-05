import type { Material, Hierarchy, Scope } from '@/types/api';
export const levels = ['course','semester','subject','unit'] as const;
export function scopeURL(scope: Scope) { const p=new URLSearchParams();for(const key of [...levels,'material_id'] as const)if(scope[key])p.set(key==='material_id'?'material':key,scope[key]!);return `/knowledge?${p}`; }
export function courseURL(course:string){return `/courses/${encodeURIComponent(course)}`;}
export function canonical(value:string, existing:string[]){const trimmed=value.trim();return existing.find(v=>v.toLocaleLowerCase()===trimmed.toLocaleLowerCase())??trimmed;}
export function options(materials:Material[],scope:Partial<Hierarchy>,level:typeof levels[number]) { const index=levels.indexOf(level);return [...new Set(materials.filter(m=>levels.slice(0,index).every(k=>!scope[k]||scope[k]===m[k])).map(m=>m[level]))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true})); }
export function projectCourses(materials:Material[]){return [...new Set(materials.map(m=>m.course))].sort((a,b)=>a.localeCompare(b)).map(name=>{const rows=materials.filter(m=>m.course===name);return {name,materials:rows,subjects:new Set(rows.map(m=>`${m.semester}\0${m.subject}`)).size,semesters:[...new Set(rows.map(m=>m.semester))].sort(),latest:rows.map(m=>m.created_at).sort().at(-1)};});}

export function normalizeHierarchy(hierarchy:Hierarchy,materials:Material[]):Hierarchy { const normalized={...hierarchy};for(const key of levels)normalized[key]=canonical(normalized[key],options(materials,normalized,key));return normalized; }

export function decodeRouteSegment(value:string){try{return decodeURIComponent(value);}catch{return value;}}
