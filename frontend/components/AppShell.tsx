"use client";
import Link from "next/link";
import { Activity, BellRing, LayoutDashboard, ShieldCheck, LogOut, ChartNoAxesColumn } from "lucide-react";
import { ReactNode } from "react";

export default function AppShell({children,onLogout}:{children:ReactNode;onLogout:()=>void}) {
 return <div className="app-shell">
  <aside className="sidebar">
   <Link href="/dashboard" className="brand"><span className="brand-mark"><Activity size={23}/></span><span>Site<span className="bright">Nöbet</span><small>AI MONITORING</small></span></Link>
   <div className="nav-subtitle">ÇALIŞMA ALANI</div>
   <nav className="navigation"><Link href="/dashboard"><LayoutDashboard size={18}/> Genel Bakış</Link><Link href="/reports"><ChartNoAxesColumn size={18}/> Raporlar</Link><Link href="/settings"><BellRing size={18}/> Bildirimler</Link></nav>
   <div className="sidebar-footer"><span className="status-dot"/> İzleme altyapısı <span className="muted">V1</span><button className="nav-logout" onClick={onLogout}><LogOut size={16}/> Çıkış yap</button></div>
  </aside>
  <main className="main"><header className="topbar"><span>Kontrol Merkezi</span><div className="topbar-safe"><ShieldCheck size={17}/> Güvenli izleme</div></header><div className="page-content">{children}</div></main>
 </div>
}
