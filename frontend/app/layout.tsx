import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata = { title: "SiteNöbet AI | Website Monitoring", description: "Web sitelerinizi 7/24 takip edin." };
export default function RootLayout({children}: Readonly<{children:React.ReactNode}>) { return <html lang="tr"><body>{children}</body></html>; }
