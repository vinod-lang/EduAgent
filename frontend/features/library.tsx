"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import { Search, ArrowUpRight } from "lucide-react";
import { useAuth } from "@/features/auth";
import { useResource } from "@/features/use-resource";
import { PageHeading, Loading, ErrorNotice, Empty } from "@/components/states";
export function LibraryPage() {
  const { client } = useAuth(); const load = useCallback((signal: AbortSignal) => client.materials(signal), [client]); const view = useResource(load);
  const [search,setSearch] = useState(""); const [course,setCourse] = useState("");
  const materials = view.data?.filter((m) => (!course || m.course===course) && `${m.filename} ${m.subject} ${m.unit}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())) ?? [];
  const courses = [...new Set(view.data?.map((m) => m.course))].sort();
  return <><PageHeading eyebrow="Courses & materials" title="Your material library" description="Browse the materials your professor account can access. Course, semester, subject and unit stay with every material."/><section className="panel">
    <div className="library-tools"><div className="field"><label htmlFor="material-search">Find a material</label><div className="input-icon"><Search size={17} aria-hidden="true"/><input id="material-search" type="search" value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Search filename, subject or unit"/></div></div><div className="field"><label htmlFor="library-course">Course</label><select id="library-course" value={course} onChange={(e)=>setCourse(e.target.value)}><option value="">All authorized courses</option>{courses.map((c)=><option key={c}>{c}</option>)}</select></div></div>
    {view.loading ? <Loading label="Loading your authorized material library…"/> : view.error ? <ErrorNotice message={view.error} retry={view.retry}/> : !view.data?.length ? <Empty title="No materials uploaded yet" detail="Upload and manage materials in the Streamlit reference workspace. Existing legacy materials are not automatically assigned to your account."/> : !materials.length ? <Empty title="No materials match this view" detail="Try another course or search term."/> : <div className="table-scroll"><table><caption className="sr-only">Authorized academic material library</caption><thead><tr><th>Material</th><th>Course / Semester</th><th>Subject / Unit</th><th>Added</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{materials.map((m)=><tr key={m.material_id}><td><strong>{m.filename}</strong></td><td>{m.course}<small>{m.semester}</small></td><td>{m.subject}<small>{m.unit}</small></td><td>{new Date(m.created_at).toLocaleDateString()}</td><td><Link className="text-button" href={`/knowledge?material=${encodeURIComponent(m.material_id)}`}>Ask <ArrowUpRight size={14} aria-hidden="true"/><span className="sr-only"> about {m.filename}</span></Link></td></tr>)}</tbody></table></div>}
    <p className="footnote">Read-only library. Upload, hierarchy editing and deletion remain in Streamlit during migration.</p></section></>;
}
