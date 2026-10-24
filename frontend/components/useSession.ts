"use client";
import { useEffect, useState } from "react";
import { Session, STORAGE_KEY } from "../lib/api";

export function useSession() {
 const [session,setSession] = useState<Session|null>(null);
 const [ready,setReady] = useState(false);
 useEffect(() => {
   try { const raw = window.sessionStorage.getItem(STORAGE_KEY); if(raw) setSession(JSON.parse(raw)); } catch { /* ignore invalid session */ }
   setReady(true);
 }, []);
 function save(s: Session) {window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));setSession(s);}
 function logout() {window.sessionStorage.removeItem(STORAGE_KEY);setSession(null);window.location.href="/login";}
 return {session,ready,save,logout};
}
