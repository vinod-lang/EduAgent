import {Suspense} from "react";
import {StudentAnalyticsPage} from "@/features/students";
export default function Page(){return <Suspense fallback={<p role="status">Loading Student Analytics…</p>}><StudentAnalyticsPage/></Suspense>;}
