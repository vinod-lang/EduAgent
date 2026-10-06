"use client";
import Link from "next/link";
import {ErrorNotice} from "@/components/states";
// Never render or log the supplied exception: it may contain private content.
export default function WorkspaceError({retry}:{retry:()=>void}){return <section className="panel"><h1>Workspace unavailable</h1><ErrorNotice message="This view could not be displayed safely. Try loading it again, or return to Home." retry={retry}/><p className="footnote">Unsaved session work may need to be reopened. Nothing is automatically regenerated.</p><Link href="/home">Return to Home</Link></section>;}
