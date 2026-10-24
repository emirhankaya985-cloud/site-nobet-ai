"use client";
import Link from "next/link";
import { Activity, ArrowRight } from "lucide-react";
import { FormEvent, useState } from "react";
import { api, Session, STORAGE_KEY } from "../../lib/api";
export default function LoginPage(){
 const [email,setEmail]=useState("");const [password,setPassword]=useState("");const [loading,setLoading]=useState(false);const [error,setError]=useState("");
 async function submit(e:FormEvent){e.preventDefault();setLoading(true);setError("");try{const result=await api<Session>("/auth/login",{method:"POST",body:JSON.stringify({email,password})});sessionStorage.setItem(STORAGE_KEY,JSON.stringify(result));window.location.href="/dashboard";}catch(err){setError(err instanceof Error?err.message:"Bir hata oluştu");}finally{setLoading(false);}}
 return <div className="auth-page"><div className="auth-card"><Link href="/" className="brand"><span className="brand-mark"><Activity size={21}/></span>Site<span className="bright">Nöbet</span></Link><h1>Tekrar hoş geldiniz.</h1><p className="muted">Siteniz kontrol altında. Kaldığınız yerden devam edin.</p><form onSubmit={submit}><label>E-posta adresi<input type="email" required placeholder="ornek@sirket.com" value={email} onChange={e=>setEmail(e.target.value)} autoComplete="email"/></label><label>Şifre<input type="password" required value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label>{error&&<p role="alert" className="error-text">{error}</p>}<button disabled={loading} className="button primary full">{loading?"Giriş yapılıyor...":"Giriş yap"}<ArrowRight size={16}/></button></form><p className="auth-link">Hesabınız yok mu? <Link href="/register">Ücretsiz kayıt olun</Link></p></div></div>;
}
