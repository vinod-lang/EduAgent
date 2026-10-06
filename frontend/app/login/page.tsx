import { LoginPage } from "@/features/login";
import { developmentLoginEnabled,developmentAliases } from "@/lib/development";
export const dynamic="force-dynamic";
export default function Login(){return <LoginPage enabled={developmentLoginEnabled()} aliases={developmentLoginEnabled()?developmentAliases():[]}/>;}
