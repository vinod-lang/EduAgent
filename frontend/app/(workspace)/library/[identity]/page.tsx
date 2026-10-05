import { MaterialPage } from '@/features/materials';
export default async function Page({params}:{params:Promise<{identity:string}>}){const {identity}=await params;return <MaterialPage identity={identity}/>;}
