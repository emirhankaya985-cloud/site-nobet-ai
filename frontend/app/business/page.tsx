"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";
import AppShell from "../../components/AppShell";
import {useSession} from "../../components/useSession";
import {api} from "../../lib/api";
type Lead={id:string;name:string;email:string|null;delivery_state:string;source_id:string};
type Review={id:string;review_text:string;reply_text:string;status:string};
type Summary={leads:number;review_drafts:number;monitors:number;mail_claims:number;business_batches:number;telegram_confirmed:boolean;google_connected:boolean;autonomous_mail_connected:boolean};
export default function BusinessPage(){
 const {session,ready,logout}=useSession();
 const [leads,setLeads]=useState<Lead[]>([]);const [reviews,setReviews]=useState<Review[]>([]);
 const [summary,setSummary]=useState<Summary|null>(null);const [error,setError]=useState("");
 const [source,setSource]=useState("");const [text,setText]=useState("");const [busy,setBusy]=useState(false);
 const refresh=useCallback(async()=>{if(!session)return;try{
  const base=`/organizations/${session.organization_id}/business`;
  const [l,r,s]=await Promise.all([api<Lead[]>(base+"/leads",{},session.access_token),api<Review[]>(base+"/reviews",{},session.access_token),api<Summary>(base+"/summary",{},session.access_token)]);
  setLeads(l);setReviews(r);setSummary(s);setError("");
 }catch(e){setError(e instanceof Error?e.message:"Veriler alınamadı")}},[session]);
 useEffect(()=>{if(ready&&!session)window.location.href="/login"},[ready,session]);
 useEffect(()=>{void refresh()},[refresh]);
 async function addReview(){if(!session)return;setBusy(true);try{
  await api(`/organizations/${session.organization_id}/business/reviews/import`,{method:"POST",body:JSON.stringify({source_id:source,review_text:text})},session.access_token);
  setSource("");setText("");await refresh();
 }catch(e){setError(e instanceof Error?e.message:"Taslak oluşturulamadı")}finally{setBusy(false)}}
 if(!ready||!session)return <div className="page-loading">Yükleniyor...</div>;
 return <AppShell onLogout={logout}><div className="page-heading"><div><div className="eyebrow">İŞLETMENİZİN ORTAK ÇALIŞMA ALANI</div><h1>İşletmePilot</h1><p>Müşteri Avcısı · LeadPilot · YorumPilot · SiteNöbet</p></div><button onClick={()=>void refresh()}>Yenile</button></div>
 {error&&<p role="alert" className="alert">{error}</p>}
 <div className="stats-grid"><div className="stat-card"><h2>CRM adayları</h2><strong>{summary?.leads??"—"}</strong></div><div className="stat-card"><h2>Yorum taslakları</h2><strong>{summary?.review_drafts??"—"}</strong></div><div className="stat-card"><h2>İzlenen siteler</h2><strong>{summary?.monitors??"—"}</strong><Link href="/dashboard">Site izlemeyi aç</Link></div><div className="stat-card"><h2>Telegram</h2><strong>{summary?(summary.telegram_confirmed?"Doğrulandı":"Bağlı değil"):"—"}</strong><Link href="/settings">Bildirim bağlantısını yönet</Link></div></div>
 <section className="section-card"><h2>Entegrasyon doğrulaması</h2><p>Mail geçmişi: {summary?.mail_claims??"—"} · Birleşik batch sayısı: {summary?.business_batches??"—"}</p><p>Otomatik mail: {summary?.autonomous_mail_connected?"Doğrulandı":"Canlı gönderim doğrulanmadı"}. GitHub Actions ayarları bu API üzerinden okunamadığından gönderim veya schedule kabulü yapılamaz.</p><p>Google Business: {summary?.google_connected?"Bağlı":"Resmi Google OAuth/API bağlantısı yok"}. Yorumlar manuel içe alınır, Google hesabına yayınlanmaz.</p></section><section className="section-card"><h2>LeadPilot · Müşteri Avcısı kayıtları</h2><p>Kaynak ve mail geçmişi birlikte korunur. SMTP kabulü gelen kutusuna teslim anlamına gelmez.</p><div className="table-wrap"><table><thead><tr><th>İşletme</th><th>Kaynak</th><th>Alıcı</th><th>Mail durumu</th></tr></thead><tbody>{leads.map(l=><tr key={l.id}><td>{l.name}</td><td>{l.source_id}</td><td>{l.email??"Adres yok"}</td><td>{l.delivery_state}</td></tr>)}</tbody></table>{!leads.length&&<p>Henüz aktarılmış aday yok.</p>}</div></section>
 <section className="section-card"><h2>YorumPilot · Yanıt taslakları</h2><p>Google hesabı bağlantısı henüz etkin değil. Bu alana eklenen yorumlar için şablon taslak hazırlanır; Google’a yayın yapılmaz.</p><label>Yorum kaynak kimliği<input value={source} maxLength={200} onChange={e=>setSource(e.target.value)}/></label><label>Yorum metni<textarea value={text} maxLength={5000} onChange={e=>setText(e.target.value)}/></label><button disabled={busy||!source.trim()||!text.trim()} onClick={()=>void addReview()}>Taslak oluştur</button>{reviews.map(r=><article key={r.id}><blockquote>{r.review_text}</blockquote><p>{r.reply_text}</p><small>Durum: {r.status} · İnceleme bekliyor</small></article>)}</section>
 </AppShell>
}
