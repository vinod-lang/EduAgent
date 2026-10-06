import {Suspense} from "react";
import {DocumentStudioPage} from "@/features/documents";
import {Loading} from "@/components/states";
export default function Page(){return <Suspense fallback={<Loading label="Loading Document Studio…"/>}><DocumentStudioPage/></Suspense>;}
