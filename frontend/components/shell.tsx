"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BookOpen, House, Library, ClipboardList, FileText, ChartNoAxesCombined, ListChecks, Workflow, PanelLeftClose, PanelLeftOpen, Menu, X, LogOut, GraduationCap } from "lucide-react";
import { useAuth } from "@/features/auth";
import { Loading, ErrorNotice } from "@/components/states";
import { APIError } from "@/lib/api";
const navigation = [
  { title: "Home", href: "/home", icon: House }, { title: "Courses", href: "/courses", icon: Library }, { title: "Material library", href: "/library", icon: Library }, { title: "Knowledge", href: "/knowledge", icon: BookOpen },
  { title: "Assessment Studio", href: "/workspace/assessment", icon: ClipboardList, upcoming: true }, { title: "Document Studio", href: "/workspace/documents", icon: FileText, upcoming: true },
  { title: "Student Analytics", href: "/workspace/students", icon: ChartNoAxesCombined, upcoming: true }, { title: "Smart Assistant", href: "/workspace/assistant", icon: Workflow, upcoming: true }, { title: "Activity", href: "/workspace/activity", icon: ListChecks, upcoming: true },
];
function SignInRequired() { const router = useRouter(); useEffect(() => { router.replace("/login"); }, [router]); return <Loading label="Sign in to access your professor workspace."/>; }
export function ProtectedShell({ children }: { children: React.ReactNode }) {
  const auth = useAuth(); const pathname = usePathname(); const dialog = useRef<HTMLDialogElement>(null);
  const [collapsed, setCollapsed] = useState(false); const [logoutError, setLogoutError] = useState<string | null>(null); const [leaving, setLeaving] = useState(false);
  if (auth.session.status === "unauthenticated") return <SignInRequired/>;
  if (auth.session.status === "error") return <main className="auth-boundary"><ErrorNotice message={auth.session.message ?? "Cannot verify your session."} retry={() => { void auth.refresh(); }}/></main>;
  if (!auth.ready || auth.session.status !== "authenticated") return <main className="auth-boundary"><Loading label="Verifying your professor session…"/></main>;
  const current = navigation.find((item) => item.href === pathname)?.title ?? "Workspace";
  const links = (mobile = false) => <nav aria-label={mobile ? "Mobile workspace navigation" : "Workspace navigation"}>{navigation.map(({ title, href, icon: Icon, upcoming }) => <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined} title={collapsed && !mobile ? title : undefined} className="nav-link" onClick={() => dialog.current?.close()}><Icon size={19} aria-hidden="true"/><span className="nav-label">{title}</span>{upcoming && <span className="nav-next">Upcoming</span>}</Link>)}</nav>;
  const signOut = async () => { setLeaving(true); setLogoutError(null); try { await auth.logout(); } catch (e) { setLogoutError(e instanceof APIError ? e.message : "Could not sign out. Check the connection and retry."); } finally { setLeaving(false); } };
  return <div className={`workspace-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
    <a className="skip-link" href="#workspace-main">Skip to workspace</a>
    <aside className="sidebar" aria-label="EduAgent workspace"><Link href="/home" className="brand"><GraduationCap size={28} aria-hidden="true"/><span className="nav-label">EduAgent<small>Professor workspace</small></span></Link>{links()}<div className="sidebar-foot"><span className="nav-label">Built for higher education</span><button className="icon-button" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} aria-expanded={!collapsed}>{collapsed ? <PanelLeftOpen size={18}/> : <PanelLeftClose size={18}/>}</button></div></aside>
    <div className="workspace-body"><header className="topbar"><div className="header-context"><button className="icon-button mobile-menu" aria-label="Open navigation" aria-haspopup="dialog" aria-controls="mobile-navigation" onClick={() => dialog.current?.showModal()}><Menu size={20}/></button><span className="context-label">Professor workspace</span><span className="context-divider" aria-hidden="true">/</span><strong>{current}</strong></div><div className="account"><span className="identity"><span className="avatar" aria-hidden="true">{auth.session.professor.display_name.charAt(0).toUpperCase()}</span><span>{auth.session.professor.display_name}</span></span><button className="icon-button" onClick={() => { void signOut(); }} disabled={leaving} aria-label={leaving ? "Signing out" : "Sign out"} title="Sign out"><LogOut size={18}/></button></div></header>
    <main id="workspace-main" tabIndex={-1} className="main-content">{logoutError && <ErrorNotice message={logoutError}/>} {children}</main></div>
    <dialog id="mobile-navigation" ref={dialog} className="nav-drawer" aria-labelledby="drawer-title"><div className="drawer-heading"><h2 id="drawer-title">EduAgent</h2><button className="icon-button" aria-label="Close navigation" onClick={() => dialog.current?.close()}><X size={20}/></button></div>{links(true)}</dialog>
  </div>;
}
