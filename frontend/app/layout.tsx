import type { Metadata } from "next";
import { AuthProvider } from "@/features/auth";
import "./globals.css";
export const metadata: Metadata={title:"EduAgent · Professor workspace",description:"Course-grounded academic workspace for higher education."};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><AuthProvider>{children}</AuthProvider></body></html>;}
