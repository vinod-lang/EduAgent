import {notFound,redirect} from "next/navigation";
const destinations:Record<string,string>={assessment:"/assessment",documents:"/documents",students:"/students",assistant:"/assistant",activity:"/activity"};
export default async function LegacyWorkspace({params}:{params:Promise<{slug:string}>}){const {slug}=await params;const destination=destinations[slug];if(!destination)notFound();redirect(destination);}
