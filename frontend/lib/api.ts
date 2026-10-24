export type Session = { access_token: string; organization_id: string };
export type Monitor = { id: string; name: string; url: string; status: string; last_response_ms: number | null; last_status_code: number | null; last_checked_at: string | null; last_error: string | null; interval_seconds: number; paused: boolean };
export type Dashboard = { total: number; up: number; down: number; unknown: number; average_uptime_percent: number | null; last_24h_incidents: number };
export type MonitorDetail = Monitor & { uptime: {uptime_percent: number|null; observed_seconds:number; unobserved_seconds:number; confirmed_down_seconds:number}; checks: Array<{at:string; status_code:number|null; response_ms:number|null; state:string}>; incidents: Array<{id:string;opened_at:string;closed_at:string|null;closed_reason:string|null;reason:string|null}>; ssl: {expires_at:string|null; checked_at:string;error:string|null}|null };
export const STORAGE_KEY = "sitenobet-session-v1";
export function apiBase() { return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, ""); }
export async function api<T>(path: string, opts: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { ...opts, cache:"no-store", headers: {"Content-Type": "application/json", ...(token ? {Authorization: `Bearer ${token}`} : {}), ...(opts.headers || {})} });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}
export function statusText(status: string) { return ({UP:"Çalışıyor",DOWN:"Erişilemiyor",SUSPECTED_DOWN:"Kontrol ediliyor",RECOVERING:"Kurtarılıyor",PAUSED:"Duraklatıldı",UNKNOWN:"Bilinmiyor"} as Record<string,string>)[status] || status; }
export function statusClass(status: string) { return status === "UP" ? "good" : status === "DOWN" ? "bad" : status === "UNKNOWN" || status === "PAUSED" ? "idle" : "warn"; }
