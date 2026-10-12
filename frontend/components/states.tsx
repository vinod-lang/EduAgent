"use client";
import { AlertCircle, ArrowRight } from "lucide-react";
import Link from "next/link";
export function Loading({ label = "Loading your workspace…" }: { label?: string }) { return <div className="loading" role="status"><span className="progress-line" />{label}</div>; }
export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) { return <div className="error-notice" role="alert"><AlertCircle size={18} aria-hidden="true"/><div><p>{message}</p>{retry && <button className="text-button" onClick={retry}>Try again <ArrowRight size={14} aria-hidden="true"/></button>}</div></div>; }
export function Empty({ title, detail, href, action }: { title: string; detail: string; href?: string; action?: string }) { return <div className="empty"><h3>{title}</h3><p>{detail}</p>{href && <Link className="text-button" href={href}>{action} <ArrowRight size={14} aria-hidden="true"/></Link>}</div>; }
export function PageHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: React.ReactNode }) { return <header className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="lede">{description}</p></div>{children}</header>; }
