import { Suspense } from "react";
import { KnowledgePage } from "@/features/knowledge";
import { Loading } from "@/components/states";
export default function Knowledge(){return <Suspense fallback={<Loading label="Preparing your knowledge workspace…"/>}><KnowledgePage/></Suspense>;}
