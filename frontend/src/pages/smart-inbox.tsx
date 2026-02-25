import React, { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import Navbar from '../components/Navbar';
import { useAuth } from '../contexts/AuthContext';
import {
  Inbox, Send, AlertTriangle, CheckCircle, XCircle, RefreshCw,
  Search, Eye, Clock, Shield, Zap, Mail, User,
  ChevronDown, RotateCw, Edit3, Check, X,
  Activity, AlertCircle, Archive, MailOpen, CheckSquare, Square,
  Minimize2, Maximize2, Bell, EyeOff, Pause, Play, Paperclip
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

interface InboundEmail {
  id: number; created_at: string; from_address: string; subject: string;
  category: string; sensitivity: string; ai_summary: string;
  confidence_score: number; extracted_policy_number: string | null;
  extracted_insured_name: string | null; extracted_carrier: string | null;
  customer_name: string | null; customer_email: string | null;
  match_method: string | null; match_confidence: number | null;
  status: string; nowcerts_note_logged: boolean; error_message: string | null;
  attachment_count: number; attachment_names: string[] | null;
  has_outbound: boolean; body_plain?: string; body_html?: string;
  ai_analysis?: any; outbound_messages?: OutboundMessage[];
  is_read: boolean; is_archived: boolean;
}

interface OutboundMessage {
  id: number; created_at: string; to_email: string; to_name: string | null;
  subject: string; body_html: string; body_plain: string;
  ai_rationale: string | null; status: string; sensitivity: string;
  sent_at: string | null; approved_by: string | null;
  rejected_reason: string | null; send_error: string | null;
}

interface InboxStats {
  received_24h: number; received_7d: number; pending_approval: number;
  auto_sent_24h: number; failed: number; matched_7d: number;
  unmatched_7d: number; category_breakdown: Record<string, number>;
}

const CAT_TW: Record<string, string> = {
  non_payment: 'bg-red-500/15 text-red-400', cancellation: 'bg-red-600/15 text-red-500',
  non_renewal: 'bg-orange-500/15 text-orange-400', underwriting_requirement: 'bg-amber-500/15 text-amber-400',
  renewal_notice: 'bg-violet-500/15 text-violet-400', policy_change: 'bg-blue-500/15 text-blue-400',
  claim_notice: 'bg-rose-500/15 text-rose-400', billing_inquiry: 'bg-sky-500/15 text-sky-400',
  customer_request: 'bg-cyan-500/15 text-cyan-400', general_inquiry: 'bg-slate-500/15 text-slate-400',
  endorsement: 'bg-indigo-500/15 text-indigo-400', new_business_confirmation: 'bg-emerald-500/15 text-emerald-400',
  audit_notice: 'bg-fuchsia-500/15 text-fuchsia-400', other: 'bg-slate-500/15 text-slate-400',
};
const CAT_BORDER: Record<string, string> = {
  non_payment: '#f87171', cancellation: '#ef4444', non_renewal: '#f97316',
  underwriting_requirement: '#fbbf24', renewal_notice: '#a78bfa', policy_change: '#60a5fa',
  claim_notice: '#f43f5e', billing_inquiry: '#38bdf8', customer_request: '#22d3ee',
  general_inquiry: '#94a3b8', endorsement: '#818cf8', new_business_confirmation: '#34d399',
  audit_notice: '#e879f9', other: '#64748b',
};
const SENS: Record<string, { tw: string; label: string }> = {
  routine: { tw: 'text-emerald-400', label: 'Routine' }, moderate: { tw: 'text-amber-400', label: 'Moderate' },
  sensitive: { tw: 'text-orange-400', label: 'Sensitive' }, critical: { tw: 'text-red-400', label: 'Critical' },
};
const STAT_TW: Record<string, string> = {
  received: 'text-slate-400', parsing: 'text-blue-400', parsed: 'text-sky-400',
  customer_matched: 'text-cyan-400', customer_not_found: 'text-orange-400',
  logged: 'text-violet-400', outbound_queued: 'text-amber-400',
  outbound_sent: 'text-emerald-400', outbound_approved: 'text-emerald-400',
  outbound_rejected: 'text-red-400', completed: 'text-cyan-400',
  failed: 'text-red-400', skipped: 'text-slate-400',
};

function timeAgo(d: string): string {
  const s = (Date.now() - new Date(d).getTime()) / 1000;
  if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`; if (s < 172800) return 'yesterday';
  if (s < 604800) return `${Math.floor(s/86400)}d ago`;
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function fmtCat(c: string) { return (c||'other').replace(/_/g,' ').replace(/\b\w/g,x=>x.toUpperCase()); }
function fmtStat(s: string) { return (s||'').replace(/_/g,' ').replace(/\b\w/g,x=>x.toUpperCase()); }
function dateGroup(d: string): string {
  const dt = new Date(d), now = new Date();
  const today = new Date(now.getFullYear(),now.getMonth(),now.getDate());
  if (dt >= today) return 'Today';
  if (dt >= new Date(today.getTime()-86400000)) return 'Yesterday';
  if (dt >= new Date(today.getTime()-today.getDay()*86400000)) return 'This Week';
  return dt.toLocaleDateString('en-US',{month:'long',day:'numeric'});
}
function needsAttn(e: InboundEmail) { return e.status==='failed'||e.status==='outbound_queued'; }

export default function SmartInboxPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'inbox'|'queue'|'stats'>('inbox');
  const [emails, setEmails] = useState<InboundEmail[]>([]);
  const [queue, setQueue] = useState<OutboundMessage[]>([]);
  const [stats, setStats] = useState<InboxStats|null>(null);
  const [sel, setSel] = useState<InboundEmail|null>(null);
  const [search, setSearch] = useState('');
  const [fCat, setFCat] = useState(''); const [fSens, setFSens] = useState('');
  const [loading, setLoading] = useState(false);
  const [editId, setEditId] = useState<number|null>(null);
  const [editSubj, setEditSubj] = useState(''); const [editBody, setEditBody] = useState('');
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [compact, setCompact] = useState(false);
  const [vf, setVf] = useState<'all'|'unread'|'attention'|'archived'>('all');
  const [batchOpen, setBatchOpen] = useState(false);
  const [autoRef, setAutoRef] = useState(true);
  const batchRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<NodeJS.Timeout|null>(null);

  const tok = typeof window!=='undefined' ? localStorage.getItem('token') : null;
  const hdr = { Authorization: `Bearer ${tok}` };

  const fetchEmails = useCallback(async (quiet=false) => {
    if (!quiet) setLoading(true);
    try {
      const p: any = { limit: 100 };
      if (search) p.search = search; if (fCat) p.category = fCat; if (fSens) p.sensitivity = fSens;
      if (vf==='archived') p.archived = true; else p.archived = false;
      if (vf==='unread') p.is_read = false;
      const r = await axios.get(`${API}/api/smart-inbox/emails`, { params: p, headers: hdr });
      setEmails(r.data.emails || []);
    } catch(e) { console.error(e); }
    if (!quiet) setLoading(false);
  }, [search, fCat, fSens, vf]);

  const fetchQueue = async () => {
    try { const r = await axios.get(`${API}/api/smart-inbox/queue`, { params:{status:'pending_approval'}, headers:hdr }); setQueue(r.data.queue||[]); } catch{}
  };
  const fetchStats = async () => {
    try { const r = await axios.get(`${API}/api/smart-inbox/stats`, { headers:hdr }); setStats(r.data); } catch{}
  };
  const fetchDetail = async (id: number) => {
    try {
      const r = await axios.get(`${API}/api/smart-inbox/emails/${id}`, { headers:hdr }); setSel(r.data);
      try { await axios.post(`${API}/api/smart-inbox/emails/${id}/read`, {}, { headers:hdr }); } catch{}
      setEmails(p => p.map(e => e.id===id ? {...e, is_read:true} : e));
    } catch(e) { console.error(e); }
  };
  const refreshAll = (q=false) => { fetchEmails(q); fetchQueue(); fetchStats(); };

  useEffect(() => { refreshAll(); }, []);
  useEffect(() => { fetchEmails(); }, [search, fCat, fSens, vf]);
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (autoRef) timerRef.current = setInterval(() => refreshAll(true), 30000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [autoRef, search, fCat, fSens, vf]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (batchRef.current && !batchRef.current.contains(e.target as Node)) setBatchOpen(false); };
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h);
  }, []);

  const batch = async (action: string) => {
    const ids = [...checked]; if (!ids.length) return;
    try { await axios.post(`${API}/api/smart-inbox/emails/batch`, { ids, action }, { headers:hdr }); } catch{}
    setChecked(new Set()); setBatchOpen(false); fetchEmails(true);
    if (sel && ids.includes(sel.id)) { if (action==='archive') setSel(null); else fetchDetail(sel.id); }
  };
  const toggle = (id:number, e?:React.MouseEvent) => {
    e?.stopPropagation(); setChecked(p => { const n=new Set(p); n.has(id)?n.delete(id):n.add(id); return n; });
  };
  const selAll = () => { if (checked.size===filtered.length) setChecked(new Set()); else setChecked(new Set(filtered.map(e=>e.id))); };

  const approve = async (id:number) => {
    try { await axios.post(`${API}/api/smart-inbox/queue/${id}/approve`, {}, { headers:hdr }); } catch(e:any) { alert(e.response?.data?.detail||'Failed'); }
    fetchQueue(); if (sel) fetchDetail(sel.id);
  };
  const reject = async (id:number) => {
    const reason = prompt('Rejection reason (optional):');
    try { await axios.post(`${API}/api/smart-inbox/queue/${id}/reject`, null, { headers:hdr, params:{reason} }); } catch(e:any) { alert(e.response?.data?.detail||'Failed'); }
    fetchQueue(); if (sel) fetchDetail(sel.id);
  };
  const editSend = async (id:number) => {
    try { await axios.post(`${API}/api/smart-inbox/queue/${id}/edit`, { subject:editSubj, body_html:`<div style="font-family:-apple-system,sans-serif;">${editBody.replace(/\n/g,'<br>')}</div>`, body_plain:editBody, send:true }, { headers:hdr }); } catch(e:any) { alert(e.response?.data?.detail||'Failed'); }
    setEditId(null); fetchQueue(); if (sel) fetchDetail(sel.id);
  };
  const reprocess = async (id:number) => { try { await axios.post(`${API}/api/smart-inbox/reprocess/${id}`, {}, { headers:hdr }); } catch{} fetchEmails(); };

  const filtered = vf==='attention' ? emails.filter(e=>needsAttn(e)) : emails;
  const grouped = (() => {
    const gs: {label:string;items:InboundEmail[]}[] = []; const m = new Map<string,InboundEmail[]>(); const o: string[] = [];
    for (const e of filtered) { const g=dateGroup(e.created_at); if(!m.has(g)){m.set(g,[]);o.push(g);} m.get(g)!.push(e); }
    for (const l of o) gs.push({label:l,items:m.get(l)!}); return gs;
  })();
  const unread = emails.filter(e=>!e.is_read&&!e.is_archived).length;
  const attn = emails.filter(e=>needsAttn(e)&&!e.is_archived).length;

  if (!user) return null;

  return (
    <>
      <Head><title>Smart Inbox — ORBIT</title></Head>
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <div className="px-4 py-4 max-w-[1600px] mx-auto">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="stat-card w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-400 to-cyan-600 flex items-center justify-center">
                <Inbox size={18} className="text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">Smart Inbox</h1>
                <p className="text-xs text-slate-500">AI-Powered Email Processing • <span className="text-cyan-600 cursor-pointer hover:underline" onClick={()=>navigator.clipboard.writeText('process@mail.betterchoiceins.com')}>process@mail.betterchoiceins.com</span></p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {queue.length > 0 && (
                <button onClick={()=>setTab('queue')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-xs font-semibold animate-pulse">
                  <AlertTriangle size={13} /> {queue.length} awaiting approval
                </button>
              )}
              <button onClick={()=>setAutoRef(!autoRef)} title={autoRef?'Pause auto-refresh':'Resume auto-refresh'}
                className={`p-1.5 rounded-lg border text-xs ${autoRef?'bg-emerald-50 border-emerald-200 text-emerald-600':'bg-slate-100 border-slate-200 text-slate-400'}`}>
                {autoRef ? <Play size={13}/> : <Pause size={13}/>}
              </button>
              <button onClick={()=>refreshAll()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-600 text-xs font-medium">
                <RefreshCw size={13}/> Refresh
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-0 border-b border-slate-200 mb-4">
            {([{key:'inbox' as const,label:'Inbox',icon:Inbox,badge:unread},{key:'queue' as const,label:'Approval Queue',icon:Clock,badge:queue.length},{key:'stats' as const,label:'Analytics',icon:Activity,badge:0}]).map(t=>(
              <button key={t.key} onClick={()=>setTab(t.key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 ${tab===t.key?'border-cyan-500 text-cyan-600':'border-transparent text-slate-500 hover:text-slate-700'}`}>
                <t.icon size={15}/>{t.label}
                {t.badge>0 && <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${t.key==='queue'?'bg-amber-100 text-amber-700':'bg-cyan-100 text-cyan-700'}`}>{t.badge}</span>}
              </button>
            ))}
          </div>

          {/* INBOX */}
          {tab==='inbox' && (
            <div className="flex gap-4" style={{minHeight:'calc(100vh - 220px)'}}>
              <div className={`flex flex-col ${sel?'w-[520px] flex-shrink-0':'flex-1'}`}>
                {/* Toolbar */}
                <div className="flex gap-2 mb-3 flex-wrap items-center">
                  <div className="flex-1 min-w-[180px] relative">
                    <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400"/>
                    <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search emails, customers, policies..."
                      className="w-full pl-8 pr-3 py-2 text-xs rounded-lg border border-slate-200 bg-white text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-400"/>
                  </div>
                  <select value={fCat} onChange={e=>setFCat(e.target.value)} className="px-2.5 py-2 text-xs rounded-lg border border-slate-200 bg-white text-slate-700">
                    <option value="">All Categories</option>
                    {Object.keys(CAT_TW).map(c=><option key={c} value={c}>{fmtCat(c)}</option>)}
                  </select>
                  <select value={fSens} onChange={e=>setFSens(e.target.value)} className="px-2.5 py-2 text-xs rounded-lg border border-slate-200 bg-white text-slate-700">
                    <option value="">All Sensitivity</option>
                    <option value="routine">Routine</option><option value="moderate">Moderate</option>
                    <option value="sensitive">Sensitive</option><option value="critical">Critical</option>
                  </select>
                  <button onClick={()=>setCompact(!compact)} className={`p-2 rounded-lg border text-xs ${compact?'bg-cyan-50 border-cyan-200 text-cyan-600':'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'}`}>
                    {compact?<Maximize2 size={13}/>:<Minimize2 size={13}/>}
                  </button>
                </div>

                {/* View filters */}
                <div className="flex gap-1.5 mb-3 items-center">
                  {([{key:'all' as const,label:'All'},{key:'unread' as const,label:'Unread',count:unread},{key:'attention' as const,label:'Needs Attention',count:attn,Icon:Bell},{key:'archived' as const,label:'Archived',Icon:Archive}]).map(f=>(
                    <button key={f.key} onClick={()=>{setVf(f.key);setChecked(new Set());}}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold ${vf===f.key?'bg-cyan-50 text-cyan-700 border border-cyan-200':'bg-white text-slate-500 border border-slate-200 hover:bg-slate-50'}`}>
                      {'Icon' in f && f.Icon && <f.Icon size={11}/>}{f.label}
                      {'count' in f && (f.count??0)>0 && <span className="text-[9px] font-bold bg-cyan-100 text-cyan-700 px-1 rounded">{f.count}</span>}
                    </button>
                  ))}
                  <div className="flex-1"/>
                  {autoRef && <span className="text-[10px] text-slate-400 flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"/>Live</span>}
                  {checked.size>0 && (
                    <div ref={batchRef} className="relative">
                      <button onClick={()=>setBatchOpen(!batchOpen)} className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold bg-cyan-50 text-cyan-700 border border-cyan-200">
                        {checked.size} selected <ChevronDown size={11}/>
                      </button>
                      {batchOpen && (
                        <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg shadow-lg border border-slate-200 py-1 min-w-[150px]">
                          <button onClick={()=>batch('read')} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"><Eye size={12}/> Mark Read</button>
                          <button onClick={()=>batch('unread')} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"><EyeOff size={12}/> Mark Unread</button>
                          <button onClick={()=>batch(vf==='archived'?'unarchive':'archive')} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                            {vf==='archived'?<><MailOpen size={12}/> Unarchive</>:<><Archive size={12}/> Archive</>}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Select all */}
                {filtered.length>0 && (
                  <div className="flex items-center gap-2 px-2 py-1 border-b border-slate-100 mb-1">
                    <button onClick={selAll} className="text-slate-400 hover:text-cyan-500">
                      {checked.size===filtered.length&&checked.size>0?<CheckSquare size={14}/>:<Square size={14}/>}
                    </button>
                    <span className="text-[11px] text-slate-400">{filtered.length} email{filtered.length!==1?'s':''}</span>
                  </div>
                )}

                {/* List */}
                <div className="card flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-white">
                  {loading ? (
                    <div className="flex items-center justify-center py-16 text-slate-400"><RefreshCw size={18} className="animate-spin mr-2"/> Loading...</div>
                  ) : filtered.length===0 ? (
                    <div className="text-center py-16">
                      {vf==='unread'?<><CheckCircle size={32} className="mx-auto text-emerald-400 mb-2"/><p className="text-emerald-600 font-semibold text-sm">All caught up!</p></>
                      :vf==='attention'?<><CheckCircle size={32} className="mx-auto text-emerald-400 mb-2"/><p className="text-emerald-600 font-semibold text-sm">Nothing needs attention</p></>
                      :vf==='archived'?<><Archive size={32} className="mx-auto text-slate-300 mb-2"/><p className="text-slate-400 text-sm">No archived emails</p></>
                      :<><Inbox size={32} className="mx-auto text-slate-300 mb-2"/><p className="text-slate-400 text-sm">No emails yet</p><p className="text-slate-400 text-xs mt-1">Forward to <strong className="text-cyan-600">process@mail.betterchoiceins.com</strong></p></>}
                    </div>
                  ) : grouped.map(g=>(
                    <div key={g.label}>
                      <div className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider bg-slate-50 border-b border-slate-100 sticky top-0 z-10">{g.label}</div>
                      {g.items.map(email=>{
                        const isA=sel?.id===email.id; const sens=SENS[email.sensitivity]||SENS.routine; const att=needsAttn(email);
                        return (
                          <div key={email.id} onClick={()=>fetchDetail(email.id)}
                            className={`flex items-start gap-2.5 px-3 cursor-pointer border-b border-slate-50 transition-all ${compact?'py-2':'py-3'} ${isA?'bg-cyan-50/70':email.is_read?'bg-white hover:bg-slate-50/80':'bg-blue-50/40 hover:bg-blue-50/60'}`}
                            style={{borderLeft:`3px solid ${att?'#fbbf24':CAT_BORDER[email.category]||'#94a3b8'}`}}>
                            <button onClick={e=>toggle(email.id,e)} className={`mt-0.5 flex-shrink-0 ${checked.has(email.id)?'text-cyan-500':'text-slate-300 hover:text-slate-400'}`}>
                              {checked.has(email.id)?<CheckSquare size={14}/>:<Square size={14}/>}
                            </button>
                            <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${email.is_read?'':'bg-cyan-500 shadow-sm shadow-cyan-300'}`}/>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between mb-0.5">
                                <span className={`text-xs truncate ${email.is_read?'font-medium text-slate-600':'font-bold text-slate-900'}`}>{email.subject||'(no subject)'}</span>
                                <span className="text-[10px] text-slate-400 ml-2 flex-shrink-0">{timeAgo(email.created_at)}</span>
                              </div>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${CAT_TW[email.category]||CAT_TW.other}`}>{fmtCat(email.category)}</span>
                                <span className={`text-[10px] ${sens.tw}`}>{sens.label}</span>
                                <span className={`text-[10px] ${STAT_TW[email.status]||'text-slate-400'}`}>• {fmtStat(email.status)}</span>
                                {email.customer_name && <span className="text-[10px] text-emerald-500 flex items-center gap-0.5"><User size={9}/>{email.customer_name}</span>}
                                {email.nowcerts_note_logged && <span className="text-[9px] text-violet-400">📋</span>}
                                {email.attachment_count>0 && <span className="text-[9px] text-slate-400 flex items-center gap-0.5"><Paperclip size={9}/>{email.attachment_count}</span>}
                                {att && <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-100 text-amber-700">ACTION</span>}
                              </div>
                              {!compact && email.ai_summary && <p className={`text-[11px] mt-1 truncate ${email.is_read?'text-slate-400':'text-slate-500'}`}>{email.ai_summary}</p>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>

              {/* Detail Panel */}
              {sel && (
                <div className="card flex-1 min-w-[380px] rounded-lg border border-slate-200 bg-white flex flex-col overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100 flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-bold text-slate-900 leading-snug">{sel.subject}</h3>
                      <p className="text-[11px] text-slate-500 mt-0.5">From: {sel.from_address}</p>
                      {sel.attachment_names && sel.attachment_names.length>0 && (
                        <div className="flex items-center gap-1 mt-1 flex-wrap">
                          <Paperclip size={10} className="text-slate-400"/>
                          {sel.attachment_names.map((n,i)=><span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{n}</span>)}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-1 flex-shrink-0">
                      {!sel.is_archived ? (
                        <button onClick={async()=>{try{await axios.post(`${API}/api/smart-inbox/emails/${sel.id}/archive`,{},{headers:hdr});}catch{}fetchEmails(true);setSel(null);}} className="p-1 text-slate-400 hover:text-slate-600" title="Archive"><Archive size={15}/></button>
                      ) : (
                        <button onClick={async()=>{try{await axios.post(`${API}/api/smart-inbox/emails/${sel.id}/unarchive`,{},{headers:hdr});}catch{}fetchEmails(true);setSel(null);}} className="p-1 text-cyan-500" title="Unarchive"><MailOpen size={15}/></button>
                      )}
                      <button onClick={()=>setSel(null)} className="p-1 text-slate-400 hover:text-slate-600"><X size={15}/></button>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
                    {/* AI Analysis */}
                    <div className="rounded-lg bg-cyan-50 border border-cyan-200 p-3">
                      <div className="flex items-center gap-1.5 mb-2"><Zap size={13} className="text-cyan-600"/><span className="text-xs font-semibold text-cyan-700">AI Analysis</span>
                        {sel.confidence_score && <span className="text-[10px] text-slate-500">{(sel.confidence_score*100).toFixed(0)}%</span>}
                      </div>
                      <p className="text-xs text-slate-700 leading-relaxed mb-2">{sel.ai_summary}</p>
                      <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                        {sel.extracted_carrier && <div className="text-slate-500"><span className="text-slate-400">Carrier:</span> {sel.extracted_carrier}</div>}
                        {sel.extracted_policy_number && <div className="text-slate-500"><span className="text-slate-400">Policy:</span> {sel.extracted_policy_number}</div>}
                        {sel.customer_name && <div className="text-emerald-600"><span className="text-slate-400">Customer:</span> {sel.customer_name}{sel.match_method&&<span className="text-slate-400"> (via {sel.match_method})</span>}</div>}
                        {sel.extracted_insured_name && !sel.customer_name && <div className="text-orange-500"><span className="text-slate-400">Insured:</span> {sel.extracted_insured_name} (unmatched)</div>}
                      </div>
                    </div>
                    {sel.status==='failed' && (
                      <button onClick={()=>reprocess(sel.id)} className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-red-50 border border-red-200 text-red-600 text-xs font-medium hover:bg-red-100">
                        <RotateCw size={13}/> Reprocess {sel.error_message&&<span className="text-[10px] text-red-400 ml-1">({sel.error_message})</span>}
                      </button>
                    )}
                    {sel.outbound_messages && sel.outbound_messages.length>0 && (
                      <div>
                        <h4 className="text-xs text-slate-500 font-semibold mb-2 flex items-center gap-1.5"><Send size={12}/> Outbound</h4>
                        {sel.outbound_messages.map(msg=>(
                          <div key={msg.id} className={`rounded-lg border p-3 mb-2 ${msg.status==='pending_approval'?'border-amber-200 bg-amber-50/50':'border-slate-200 bg-slate-50'}`}>
                            <div className="flex justify-between mb-1">
                              <span className="text-[11px] text-slate-500">To: {msg.to_email}</span>
                              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${msg.status==='pending_approval'?'bg-amber-100 text-amber-700':msg.status==='sent'||msg.status==='auto_sent'?'bg-emerald-100 text-emerald-700':'bg-slate-100 text-slate-500'}`}>{fmtStat(msg.status)}</span>
                            </div>
                            <p className="text-xs font-semibold text-slate-800 mb-0.5">{msg.subject}</p>
                            {msg.ai_rationale && <p className="text-[10px] text-slate-400 italic mb-1.5">AI: {msg.ai_rationale}</p>}
                            <div className="rounded bg-white border border-slate-100 p-2.5 text-xs text-slate-600 leading-relaxed max-h-[160px] overflow-y-auto" dangerouslySetInnerHTML={{__html:msg.body_html}}/>
                            {(msg.status==='pending_approval'||msg.status==='draft')&&editId!==msg.id && (
                              <div className="flex gap-2 mt-2">
                                <button onClick={()=>approve(msg.id)} className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-white text-xs font-semibold"><Check size={12}/> Approve & Send</button>
                                <button onClick={()=>{setEditId(msg.id);setEditSubj(msg.subject);setEditBody(msg.body_plain||'');}} className="px-3 py-1.5 rounded-lg bg-violet-50 border border-violet-200 text-violet-600 text-xs"><Edit3 size={12}/></button>
                                <button onClick={()=>reject(msg.id)} className="px-3 py-1.5 rounded-lg bg-red-50 border border-red-200 text-red-500 text-xs"><X size={12}/></button>
                              </div>
                            )}
                            {editId===msg.id && (
                              <div className="mt-2 space-y-1.5">
                                <input value={editSubj} onChange={e=>setEditSubj(e.target.value)} className="w-full px-2.5 py-1.5 text-xs rounded border border-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-400"/>
                                <textarea value={editBody} onChange={e=>setEditBody(e.target.value)} rows={5} className="w-full px-2.5 py-1.5 text-xs rounded border border-slate-200 resize-y focus:outline-none focus:ring-1 focus:ring-cyan-400"/>
                                <div className="flex gap-2">
                                  <button onClick={()=>editSend(msg.id)} className="flex-1 py-1.5 rounded bg-cyan-500 text-white text-xs font-semibold hover:bg-cyan-600">Save & Send</button>
                                  <button onClick={()=>setEditId(null)} className="px-3 py-1.5 rounded bg-slate-100 text-slate-500 text-xs">Cancel</button>
                                </div>
                              </div>
                            )}
                            {msg.sent_at && <p className="text-[10px] text-emerald-500 mt-1.5">✓ Sent {timeAgo(msg.sent_at)}{msg.approved_by&&` • ${msg.approved_by}`}</p>}
                          </div>
                        ))}
                      </div>
                    )}
                    <div>
                      <h4 className="text-xs text-slate-500 font-semibold mb-1.5 flex items-center gap-1.5"><Mail size={12}/> Original Email</h4>
                      <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 leading-relaxed whitespace-pre-wrap break-words">{sel.body_plain||'(no content)'}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* QUEUE */}
          {tab==='queue' && (
            <div className="max-w-3xl">
              {queue.length===0?(
                <div className="text-center py-16 rounded-lg border border-slate-200 bg-white card">
                  <CheckCircle size={36} className="mx-auto text-emerald-400 mb-2"/><p className="text-emerald-600 font-semibold">All caught up!</p><p className="text-slate-400 text-xs mt-1">No messages waiting.</p>
                </div>
              ):queue.map(msg=>(
                <div key={msg.id} className="card rounded-lg border border-amber-200 bg-white p-4 mb-3" style={{borderLeft:'4px solid #fbbf24'}}>
                  <div className="flex justify-between mb-1.5">
                    <div><span className="text-sm font-semibold text-slate-900">{msg.subject}</span><p className="text-xs text-slate-500 mt-0.5">To: {msg.to_name||msg.to_email} • {timeAgo(msg.created_at)}</p></div>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-100 text-amber-700 self-start">PENDING</span>
                  </div>
                  {msg.ai_rationale && <p className="text-[11px] text-slate-400 italic mb-2">💡 {msg.ai_rationale}</p>}
                  <div className="rounded bg-slate-50 border border-slate-200 p-3 mb-3 text-xs text-slate-600 leading-relaxed max-h-[200px] overflow-y-auto" dangerouslySetInnerHTML={{__html:msg.body_html}}/>
                  <div className="flex gap-2">
                    <button onClick={()=>approve(msg.id)} className="flex-1 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-semibold">✓ Approve & Send</button>
                    <button onClick={()=>reject(msg.id)} className="py-2 px-4 rounded-lg bg-red-50 border border-red-200 text-red-500 text-sm hover:bg-red-100">✕ Reject</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* STATS */}
          {tab==='stats' && stats && (
            <div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
                {[{l:'Received (24h)',v:stats.received_24h,t:'text-cyan-600',I:Inbox},{l:'Received (7d)',v:stats.received_7d,t:'text-blue-600',I:Mail},{l:'Pending',v:stats.pending_approval,t:'text-amber-600',I:Clock},{l:'Auto-Sent',v:stats.auto_sent_24h,t:'text-emerald-600',I:Send},{l:'Matched',v:stats.matched_7d,t:'text-violet-600',I:User},{l:'Unmatched',v:stats.unmatched_7d,t:'text-orange-600',I:AlertTriangle},{l:'Failed',v:stats.failed,t:'text-red-600',I:XCircle}].map((s,i)=>(
                  <div key={i} className="stat-card rounded-lg border border-slate-200 bg-white p-3">
                    <div className="flex items-center gap-1.5 mb-1"><s.I size={13} className={s.t}/><span className="text-[10px] text-slate-500">{s.l}</span></div>
                    <div className={`text-xl font-bold ${s.t}`}>{s.v}</div>
                  </div>
                ))}
              </div>
              {Object.keys(stats.category_breakdown).length>0 && (
                <div className="card rounded-lg border border-slate-200 bg-white p-4">
                  <h3 className="text-xs text-slate-500 font-semibold mb-3">Category Breakdown (7 days)</h3>
                  <div className="space-y-2">
                    {Object.entries(stats.category_breakdown).sort((a,b)=>b[1]-a[1]).map(([cat,count])=>{
                      const max = Math.max(...Object.values(stats.category_breakdown));
                      return (
                        <div key={cat} className="flex items-center gap-3">
                          <span className="w-36 text-xs text-slate-600">{fmtCat(cat)}</span>
                          <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{width:`${(count/max)*100}%`,backgroundColor:CAT_BORDER[cat]||'#64748b',transition:'width 0.5s'}}/>
                          </div>
                          <span className="w-8 text-right text-xs font-semibold text-slate-600">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
