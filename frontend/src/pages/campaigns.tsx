import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Upload, Search, Users, Mail, Calendar, BarChart2, Play, Pause,
  CheckCircle, XCircle, Clock, ChevronDown, ChevronUp, AlertTriangle, Trash2,
  Target, Send, UserX, UserCheck, Filter, RefreshCw, Eye, MailOpen,
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

function fmtDate(iso: string) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function daysUntil(iso: string) {
  if (!iso) return null;
  const diff = Math.ceil((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  return diff;
}

const STATUS_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  pending: { color: 'text-slate-400', bg: 'bg-slate-500/15', label: 'Pending' },
  touch1_scheduled: { color: 'text-blue-300', bg: 'bg-blue-500/15', label: 'Touch 1 Scheduled' },
  touch1_sent: { color: 'text-cyan-300', bg: 'bg-cyan-500/15', label: 'Touch 1 Sent' },
  touch2_scheduled: { color: 'text-indigo-300', bg: 'bg-indigo-500/15', label: 'Touch 2 Scheduled' },
  touch2_sent: { color: 'text-violet-300', bg: 'bg-violet-500/15', label: 'Touch 2 Sent' },
  touch3_scheduled: { color: 'text-purple-300', bg: 'bg-purple-500/15', label: 'Touch 3 Scheduled' },
  touch3_sent: { color: 'text-emerald-300', bg: 'bg-emerald-500/15', label: 'All Sent' },
  responded: { color: 'text-amber-300', bg: 'bg-amber-500/15', label: 'Responded' },
  requoted: { color: 'text-green-300', bg: 'bg-green-500/15', label: 'Requoted' },
  converted: { color: 'text-emerald-300', bg: 'bg-emerald-500/15', label: 'Converted!' },
  skipped: { color: 'text-red-300', bg: 'bg-red-500/15', label: 'Skipped (Current)' },
  opted_out: { color: 'text-red-400', bg: 'bg-red-500/15', label: 'Opted Out' },
};

export default function CampaignsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // View state
  const [view, setView] = useState<'list' | 'detail'>('list');
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<any>(null);
  const [leads, setLeads] = useState<any[]>([]);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [leadsPage, setLeadsPage] = useState(1);
  const [loading, setLoading] = useState(true);

  // Pipeline stats
  const [pipelineStats, setPipelineStats] = useState<any>(null);
  const [showEmailPreview, setShowEmailPreview] = useState(false);
  const [emailPreviewHtml, setEmailPreviewHtml] = useState('');
  const [emailPreviewSubject, setEmailPreviewSubject] = useState('');
  const [previewTouch, setPreviewTouch] = useState(1);
  const [recheckingNowCerts, setRecheckingNowCerts] = useState(false);
  const [retargeting, setRetargeting] = useState(false);

  // Upload modal
  const [showUpload, setShowUpload] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [campaignName, setCampaignName] = useState('');
  const [touch1Days, setTouch1Days] = useState(45);
  const [touch2Days, setTouch2Days] = useState(28);
  const [touch3Days, setTouch3Days] = useState(15);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);

  // Filters
  const [leadFilter, setLeadFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // Dedup
  const [deduping, setDeduping] = useState(false);
  const [dedupResult, setDedupResult] = useState<any>(null);

  // Sending
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<any>(null);

  const isManager = user && ['admin', 'manager', 'owner', 'ADMIN'].includes((user as any).role?.toLowerCase() || (user as any).role);

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
    else if (user) loadCampaigns();
  }, [user, authLoading]);

  const loadCampaigns = async () => {
    try {
      const res = await axios.get(`${API}/api/campaigns/`, { headers: headers() });
      setCampaigns(res.data.campaigns || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
    // Also load pipeline stats
    try {
      const ps = await axios.get(`${API}/api/campaigns/pipeline/stats`, { headers: headers() });
      setPipelineStats(ps.data);
    } catch (e) { console.error(e); }
  };

  const loadEmailPreview = async (touch: number) => {
    try {
      const res = await axios.get(`${API}/api/campaigns/preview-email`, {
        headers: headers(), params: { touch },
      });
      setEmailPreviewSubject(res.data.subject);
      setEmailPreviewHtml(res.data.html);
      setPreviewTouch(touch);
      setShowEmailPreview(true);
    } catch (e) { console.error(e); }
  };

  const handleRecheckNowCerts = async () => {
    setRecheckingNowCerts(true);
    try {
      const res = await axios.post(`${API}/api/campaigns/recheck-nowcerts`, {}, { headers: headers() });
      alert(`${res.data.message}`);
      loadCampaigns();
    } catch (e: any) { alert(e.response?.data?.detail || 'Recheck failed'); }
    finally { setRecheckingNowCerts(false); }
  };

  const handleAutoRetarget = async () => {
    setRetargeting(true);
    try {
      const res = await axios.post(`${API}/api/campaigns/auto-retarget`, {}, { headers: headers() });
      if (res.data.retarget_campaigns_created > 0) {
        alert(`Created ${res.data.retarget_campaigns_created} retarget campaign(s) in draft mode:\n\n${res.data.campaigns.map((c: any) => `• ${c.campaign_name} — ${c.leads} leads (Round ${c.retarget_round})`).join('\n')}\n\nReview and activate when ready.`);
      } else {
        alert('No campaigns eligible for retargeting yet. Campaigns must be 180+ days old with unconverted leads.');
      }
      loadCampaigns();
    } catch (e: any) { alert(e.response?.data?.detail || 'Retarget failed'); }
    finally { setRetargeting(false); }
  };

  const loadCampaignDetail = async (id: number) => {
    try {
      const res = await axios.get(`${API}/api/campaigns/${id}`, { headers: headers() });
      setSelectedCampaign(res.data);
      loadLeads(id);
      setView('detail');
    } catch (e) { console.error(e); }
  };

  const loadLeads = async (campaignId: number, page = 1) => {
    try {
      const params: any = { page, per_page: 50 };
      if (leadFilter) params.status = leadFilter;
      if (searchQuery) params.search = searchQuery;
      const res = await axios.get(`${API}/api/campaigns/${campaignId}/leads`, { headers: headers(), params });
      setLeads(res.data.leads || []);
      setLeadsTotal(res.data.total || 0);
      setLeadsPage(page);
    } catch (e) { console.error(e); }
  };

  // Upload handler
  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('campaign_name', campaignName);
      formData.append('touch1_days', String(touch1Days));
      formData.append('touch2_days', String(touch2Days));
      formData.append('touch3_days', String(touch3Days));
      const res = await axios.post(`${API}/api/campaigns/upload`, formData, { headers: headers() });
      setUploadResult(res.data);
      loadCampaigns();
    } catch (e: any) {
      setUploadResult({ error: e.response?.data?.detail || 'Upload failed' });
    }
    finally { setUploading(false); }
  };

  // Dedup handler
  const handleDedup = async () => {
    if (!selectedCampaign) return;
    setDeduping(true);
    setDedupResult(null);
    try {
      const res = await axios.post(`${API}/api/campaigns/${selectedCampaign.id}/dedup`, {}, { headers: headers() });
      setDedupResult(res.data);
      loadCampaignDetail(selectedCampaign.id);
    } catch (e: any) {
      setDedupResult({ error: e.response?.data?.detail || 'Dedup failed' });
    }
    finally { setDeduping(false); }
  };

  // Send due emails
  const handleSendDue = async () => {
    if (!selectedCampaign) return;
    setSending(true);
    setSendResult(null);
    try {
      const res = await axios.post(`${API}/api/campaigns/${selectedCampaign.id}/send-due`, {}, { headers: headers() });
      setSendResult(res.data);
      loadCampaignDetail(selectedCampaign.id);
    } catch (e: any) {
      setSendResult({ error: e.response?.data?.detail || 'Send failed' });
    }
    finally { setSending(false); }
  };

  // Lead actions
  const markLead = async (leadId: number, action: string) => {
    try {
      await axios.post(`${API}/api/campaigns/${selectedCampaign.id}/leads/${leadId}/${action}`, {}, { headers: headers() });
      loadLeads(selectedCampaign.id, leadsPage);
      loadCampaignDetail(selectedCampaign.id);
    } catch (e) { console.error(e); }
  };

  // Pause/Resume
  const toggleCampaignStatus = async () => {
    if (!selectedCampaign) return;
    const action = selectedCampaign.status === 'active' ? 'pause' : 'resume';
    try {
      await axios.post(`${API}/api/campaigns/${selectedCampaign.id}/${action}`, {}, { headers: headers() });
      loadCampaignDetail(selectedCampaign.id);
      loadCampaigns();
    } catch (e) { console.error(e); }
  };

  const deleteCampaign = async () => {
    if (!selectedCampaign) return;
    if (!confirm(`Delete campaign "${selectedCampaign.name}" and all its leads? This cannot be undone.`)) return;
    try {
      await axios.post(`${API}/api/campaigns/${selectedCampaign.id}/delete`, {}, { headers: headers() });
      setView('list');
      setSelectedCampaign(null);
      loadCampaigns();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Delete failed');
    }
  };

  useEffect(() => {
    if (selectedCampaign) loadLeads(selectedCampaign.id, 1);
  }, [leadFilter, searchQuery]);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-[#0a0f1a]">
        <Navbar />
        <div className="flex items-center justify-center h-[80vh]">
          <div className="animate-pulse text-cyan-400">Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0f1a] text-white">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-6">

        {/* ── HEADER ── */}
        <div className="flex items-center justify-between mb-6">
          <div>
            {view === 'detail' && (
              <button onClick={() => { setView('list'); setSelectedCampaign(null); }} className="text-xs text-cyan-400 hover:text-cyan-300 mb-1 block">
                ← Back to Campaigns
              </button>
            )}
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Target className="text-cyan-400" size={24} />
              {view === 'list' ? 'Requote Campaigns' : selectedCampaign?.name || 'Campaign'}
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              {view === 'list'
                ? 'Re-engage former customers with targeted X-date email campaigns'
                : `${selectedCampaign?.total_valid || 0} leads · ${selectedCampaign?.status}`}
            </p>
          </div>
          <div className="flex gap-2">
            {view === 'list' && (
              <>
              <a href="/get-quote" target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-4 py-2 bg-blue-500/15 hover:bg-blue-500/25 border border-blue-500/25 rounded-lg text-blue-300 text-sm font-semibold transition">
                <Eye size={16} /> Landing Page
              </a>
              <button onClick={() => { setShowUpload(true); setUploadResult(null); setUploadFile(null); setCampaignName(''); }}
                className="flex items-center gap-1.5 px-4 py-2 bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/25 rounded-lg text-cyan-300 text-sm font-semibold transition">
                <Upload size={16} /> New Campaign
              </button>
              </>
            )}
            {view === 'detail' && isManager && (
              <>
                <button onClick={handleDedup} disabled={deduping}
                  className="flex items-center gap-1.5 px-3 py-2 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 rounded-lg text-amber-300 text-xs font-semibold transition disabled:opacity-50">
                  <UserX size={14} /> {deduping ? 'Checking...' : 'Check NowCerts'}
                </button>
                {selectedCampaign?.status === 'active' && (
                  <div className="flex items-center gap-1.5 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-300 text-xs font-semibold">
                    <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span>
                    Auto-Sending
                  </div>
                )}
                <button onClick={toggleCampaignStatus}
                  className="flex items-center gap-1.5 px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-300 text-xs font-semibold transition">
                  {selectedCampaign?.status === 'active' ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}
                </button>
                <button onClick={deleteCampaign}
                  className="flex items-center gap-1.5 px-3 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded-lg text-red-400 text-xs font-semibold transition">
                  <Trash2 size={14} /> Delete
                </button>
              </>
            )}
          </div>
        </div>

        {/* ── CAMPAIGN LIST VIEW ── */}
        {view === 'list' && (
          <>
            {/* ── PIPELINE DASHBOARD ── */}
            {pipelineStats && (
              <div className="mb-6 space-y-4">
                {/* Lead funnel */}
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-bold text-slate-300">Lead Pipeline — All Campaigns</h3>
                    <div className="flex gap-2">
                      <button onClick={() => loadEmailPreview(1)}
                        className="text-xs px-3 py-1.5 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 rounded-lg text-blue-300 font-semibold transition">
                        <Eye size={12} className="inline mr-1" /> Preview Touch 1
                      </button>
                      <button onClick={() => loadEmailPreview(2)}
                        className="text-xs px-3 py-1.5 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 rounded-lg text-indigo-300 font-semibold transition">
                        <Eye size={12} className="inline mr-1" /> Preview Touch 2
                      </button>
                      <button onClick={() => loadEmailPreview(3)}
                        className="text-xs px-3 py-1.5 bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 rounded-lg text-purple-300 font-semibold transition">
                        <Eye size={12} className="inline mr-1" /> Preview Touch 3
                      </button>
                      <button onClick={handleRecheckNowCerts} disabled={recheckingNowCerts}
                        className="text-xs px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 rounded-lg text-amber-300 font-semibold transition disabled:opacity-50">
                        <RefreshCw size={12} className={`inline mr-1 ${recheckingNowCerts ? 'animate-spin' : ''}`} />
                        {recheckingNowCerts ? 'Checking...' : 'Re-check NowCerts'}
                      </button>
                      <button onClick={handleAutoRetarget} disabled={retargeting}
                        className="text-xs px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 rounded-lg text-emerald-300 font-semibold transition disabled:opacity-50">
                        <Target size={12} className={`inline mr-1 ${retargeting ? 'animate-spin' : ''}`} />
                        {retargeting ? 'Creating...' : 'Auto-Retarget'}
                      </button>
                    </div>
                  </div>

                  {/* Funnel bars */}
                  <div className="grid grid-cols-7 gap-2">
                    {[
                      { label: 'Pending', count: pipelineStats.pipeline.pending, color: 'bg-slate-500', text: 'text-slate-300' },
                      { label: 'Touch 1 Queued', count: pipelineStats.pipeline.touch1_scheduled, color: 'bg-blue-500', text: 'text-blue-300' },
                      { label: 'Touch 1 Sent', count: pipelineStats.pipeline.touch1_sent, color: 'bg-cyan-500', text: 'text-cyan-300' },
                      { label: 'Touch 2 Queued', count: pipelineStats.pipeline.touch2_scheduled, color: 'bg-indigo-500', text: 'text-indigo-300' },
                      { label: 'Touch 2 Sent', count: pipelineStats.pipeline.touch2_sent, color: 'bg-purple-500', text: 'text-purple-300' },
                      { label: 'Touch 3 Queued', count: pipelineStats.pipeline.touch3_scheduled || 0, color: 'bg-violet-500', text: 'text-violet-300' },
                      { label: 'Touch 3 Sent', count: pipelineStats.pipeline.touch3_sent || 0, color: 'bg-fuchsia-500', text: 'text-fuchsia-300' },
                      { label: 'Responded', count: pipelineStats.pipeline.responded, color: 'bg-emerald-500', text: 'text-emerald-300' },
                      { label: 'Requoted', count: pipelineStats.pipeline.requoted, color: 'bg-green-500', text: 'text-green-300' },
                    ].map((s, i) => {
                      const maxCount = Math.max(pipelineStats.pipeline.pending || 1, pipelineStats.pipeline.touch1_scheduled || 1, 1);
                      const pct = Math.max(8, (s.count / maxCount) * 100);
                      return (
                        <div key={i} className="text-center">
                          <div className={`text-lg font-bold ${s.text}`}>{s.count}</div>
                          <div className="h-2 bg-white/[0.04] rounded-full mt-1 overflow-hidden">
                            <div className={`h-full ${s.color} rounded-full transition-all`} style={{ width: `${pct}%`, opacity: 0.7 }} />
                          </div>
                          <div className="text-[9px] text-slate-500 mt-1 font-semibold">{s.label}</div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Bottom stats */}
                  <div className="flex gap-4 mt-4 pt-3 border-t border-white/[0.04]">
                    <div className="text-xs"><span className="text-slate-500">Total Leads: </span><span className="text-white font-bold">{pipelineStats.total_leads}</span></div>
                    <div className="text-xs"><span className="text-slate-500">Current Customers: </span><span className="text-amber-400 font-bold">{pipelineStats.current_customers_excluded}</span></div>
                    <div className="text-xs"><span className="text-slate-500">Global Opt-Outs: </span><span className="text-red-400 font-bold">{pipelineStats.global_opt_outs}</span></div>
                    <div className="text-xs"><span className="text-slate-500">Opted Out: </span><span className="text-red-300 font-bold">{pipelineStats.pipeline.opted_out}</span></div>
                  </div>
                </div>

                {/* Per-campaign breakdown */}
                {pipelineStats.campaigns?.length > 0 && (
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-white/[0.06]">
                          <th className="text-left px-4 py-2.5 text-slate-500 font-semibold">Campaign</th>
                          <th className="text-center px-2 py-2.5 text-slate-500 font-semibold">Status</th>
                          <th className="text-center px-2 py-2.5 text-slate-500 font-semibold">Leads</th>
                          <th className="text-center px-2 py-2.5 text-slate-500 font-semibold">Emailed</th>
                          <th className="text-center px-2 py-2.5 text-slate-500 font-semibold">Responded</th>
                          <th className="text-center px-2 py-2.5 text-slate-500 font-semibold">Requoted</th>
                          <th className="text-center px-2 py-2.5 text-amber-500/60 font-semibold">Customers</th>
                          <th className="text-center px-2 py-2.5 text-red-500/60 font-semibold">Opted Out</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pipelineStats.campaigns.map((c: any) => (
                          <tr key={c.id} className="border-b border-white/[0.03] hover:bg-white/[0.02] cursor-pointer" onClick={() => loadCampaignDetail(c.id)}>
                            <td className="px-4 py-2 text-slate-300 font-medium">{c.name}</td>
                            <td className="px-2 py-2 text-center">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                c.status === 'active' ? 'bg-emerald-500/15 text-emerald-300' :
                                c.status === 'draft' ? 'bg-blue-500/15 text-blue-300' :
                                c.status === 'paused' ? 'bg-amber-500/15 text-amber-300' : 'bg-slate-500/15 text-slate-400'
                              }`}>{c.status}</span>
                            </td>
                            <td className="px-2 py-2 text-center text-slate-400">{c.total_leads}</td>
                            <td className="px-2 py-2 text-center text-cyan-400">{c.emails_sent}</td>
                            <td className="px-2 py-2 text-center text-emerald-400">{c.responded}</td>
                            <td className="px-2 py-2 text-center text-green-400 font-bold">{c.requoted}</td>
                            <td className="px-2 py-2 text-center text-amber-400">{c.current_customers}</td>
                            <td className="px-2 py-2 text-center text-red-400">{c.opted_out}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {campaigns.length === 0 ? (
              <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-12 text-center">
                <Target className="mx-auto text-slate-600 mb-3" size={48} />
                <h3 className="text-lg font-semibold text-slate-400">No campaigns yet</h3>
                <p className="text-sm text-slate-500 mt-1">Upload a lead list to start your first requote campaign</p>
                <button onClick={() => { setShowUpload(true); setUploadResult(null); }}
                  className="mt-4 px-4 py-2 bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/25 rounded-lg text-cyan-300 text-sm font-semibold transition">
                  <Upload size={14} className="inline mr-1.5" /> Upload Lead List
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {campaigns.map(c => (
                  <div key={c.id}
                    onClick={() => loadCampaignDetail(c.id)}
                    className="bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] rounded-xl p-5 cursor-pointer transition group">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <h3 className="text-base font-semibold group-hover:text-cyan-300 transition">{c.name}</h3>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                            c.status === 'active' ? 'bg-emerald-500/15 text-emerald-300' :
                            c.status === 'draft' ? 'bg-blue-500/15 text-blue-300' :
                            c.status === 'paused' ? 'bg-amber-500/15 text-amber-300' :
                            'bg-slate-500/15 text-slate-400'
                          }`}>{c.status.toUpperCase()}</span>
                        </div>
                        <p className="text-xs text-slate-500 mt-1">
                          {c.original_filename} · {c.total_valid} leads · Created {fmtDate(c.created_at)} by {c.created_by_name}
                        </p>
                      </div>
                      <div className="flex gap-5 text-center">
                        <div>
                          <div className="text-lg font-bold text-white">{c.total_valid}</div>
                          <div className="text-[10px] text-slate-500">LEADS</div>
                        </div>
                        <div>
                          <div className="text-lg font-bold text-cyan-400">{c.emails_sent || 0}</div>
                          <div className="text-[10px] text-slate-500">SENT</div>
                        </div>
                        <div>
                          <div className="text-lg font-bold text-emerald-400">{c.responses_received || 0}</div>
                          <div className="text-[10px] text-slate-500">RESPONDED</div>
                        </div>
                        <div>
                          <div className="text-lg font-bold text-green-400">{c.requotes_generated || 0}</div>
                          <div className="text-[10px] text-slate-500">REQUOTED</div>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── CAMPAIGN DETAIL VIEW ── */}
        {view === 'detail' && selectedCampaign && (
          <>
            {/* Stats row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
              {[
                { label: 'Total Leads', value: selectedCampaign.stats?.total_leads || 0, color: 'text-white', filter: '' },
                { label: 'Pending', value: selectedCampaign.stats?.pending || 0, color: 'text-slate-400', filter: 'ready' },
                { label: 'Touch 1 Sent', value: selectedCampaign.stats?.touch1_sent || 0, color: 'text-cyan-400', filter: 'touch1_sent' },
                { label: 'Touch 2 Sent', value: selectedCampaign.stats?.touch2_sent || 0, color: 'text-blue-400', filter: 'touch2_sent' },
                { label: 'Touch 3 Sent', value: selectedCampaign.stats?.touch3_sent || 0, color: 'text-purple-400', filter: 'touch3_sent' },
                { label: 'Current Cust.', value: selectedCampaign.stats?.current_customers || 0, color: 'text-red-400', filter: 'current_customer' },
                { label: 'Opted Out', value: selectedCampaign.stats?.opted_out || 0, color: 'text-red-300', filter: 'opted_out' },
                { label: 'Next 7 Days', value: selectedCampaign.stats?.upcoming_7_days || 0, color: 'text-amber-400', filter: 'next_7_days' },
              ].map((s, i) => (
                <div key={i}
                  onClick={() => setLeadFilter(s.filter)}
                  className={`bg-white/[0.03] border rounded-xl px-4 py-3 text-center cursor-pointer transition-all hover:bg-white/[0.06] ${leadFilter === s.filter ? 'border-cyan-500/50 bg-cyan-500/[0.06]' : 'border-white/[0.06]'}`}
                >
                  <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
                  <div className="text-[10px] text-slate-500 uppercase">{s.label}</div>
                </div>
              ))}
            </div>

            {/* Dedup / Send result banners */}
            {dedupResult && (
              <div className={`mb-4 p-3 rounded-lg text-sm ${dedupResult.error ? 'bg-red-500/10 text-red-300 border border-red-500/20' : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'}`}>
                {dedupResult.error || dedupResult.message}
              </div>
            )}
            {sendResult && (
              <div className={`mb-4 p-3 rounded-lg text-sm ${sendResult.error ? 'bg-red-500/10 text-red-300 border border-red-500/20' : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'}`}>
                <div>{sendResult.error || sendResult.message}</div>
                {sendResult.remaining > 0 && !sendResult.error && (
                  <button onClick={handleSendDue} disabled={sending}
                    className="mt-2 px-3 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/30 rounded-lg text-emerald-200 text-xs font-semibold transition disabled:opacity-50">
                    {sending ? 'Sending next batch...' : `Send Next Batch (${sendResult.remaining} remaining)`}
                  </button>
                )}
              </div>
            )}

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <div className="relative flex-1 min-w-[200px]">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input type="text" placeholder="Search leads..."
                  value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
                />
              </div>
              <select value={leadFilter} onChange={e => setLeadFilter(e.target.value)}
                className="bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
                <option value="">All Leads</option>
                <option value="next_7_days">Next 7 Days</option>
                <option value="ready">Ready to Send</option>
                <option value="touch1_sent">Touch 1 Sent</option>
                <option value="touch2_sent">Touch 2 Sent</option>
                <option value="touch3_sent">All Sent</option>
                <option value="responded">Responded</option>
                <option value="requoted">Requoted</option>
                <option value="current_customer">Current Customers</option>
                <option value="opted_out">Opted Out</option>
              </select>
              <span className="text-xs text-slate-500">{leadsTotal} leads</span>
            </div>

            {/* Leads table */}
            <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-left">
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Name</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Email</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Type</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Carrier</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">X-Date</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Status</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Touch 1</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Touch 2</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Touch 3</th>
                      <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leads.map(lead => {
                      const st = STATUS_CONFIG[lead.status] || STATUS_CONFIG.pending;
                      const xDays = daysUntil(lead.x_date);
                      return (
                        <tr key={lead.id} className={`border-b border-white/[0.03] hover:bg-white/[0.03] transition ${lead.is_current_customer ? 'opacity-50' : ''}`}>
                          <td className="px-4 py-3">
                            <div className="font-medium text-white">{lead.first_name} {lead.last_name}</div>
                            {lead.is_current_customer && (
                              <span className="text-[10px] text-red-400 flex items-center gap-1"><UserCheck size={10} /> Current customer</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-slate-300 text-xs">{lead.email}</td>
                          <td className="px-4 py-3 text-slate-400 text-xs capitalize">{lead.policy_type || '—'}</td>
                          <td className="px-4 py-3 text-slate-400 text-xs">{lead.carrier || '—'}</td>
                          <td className="px-4 py-3">
                            <div className="text-xs text-white">{fmtDate(lead.x_date)}</div>
                            {xDays !== null && (
                              <div className={`text-[10px] ${xDays <= 0 ? 'text-red-400' : xDays <= 15 ? 'text-amber-400' : 'text-slate-500'}`}>
                                {xDays <= 0 ? `${Math.abs(xDays)}d ago` : `in ${xDays}d`}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${st.bg} ${st.color}`}>
                              {st.label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {lead.touch1_sent ? (
                              <span className="text-emerald-400 flex items-center gap-1"><CheckCircle size={12} /> Sent</span>
                            ) : lead.touch1_scheduled_date ? (
                              <span className="text-slate-500">{fmtDate(lead.touch1_scheduled_date)}</span>
                            ) : '—'}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {lead.touch2_sent ? (
                              <span className="text-emerald-400 flex items-center gap-1"><CheckCircle size={12} /> Sent</span>
                            ) : lead.touch2_scheduled_date ? (
                              <span className="text-slate-500">{fmtDate(lead.touch2_scheduled_date)}</span>
                            ) : '—'}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {lead.touch3_sent ? (
                              <span className="text-emerald-400 flex items-center gap-1"><CheckCircle size={12} /> Sent</span>
                            ) : lead.touch3_scheduled_date ? (
                              <span className="text-slate-500">{fmtDate(lead.touch3_scheduled_date)}</span>
                            ) : '—'}
                          </td>
                          <td className="px-4 py-3">
                            {!lead.is_current_customer && !lead.opted_out && (
                              <div className="flex gap-1">
                                {lead.status !== 'responded' && lead.status !== 'requoted' && (
                                  <button onClick={() => markLead(lead.id, 'mark-responded')}
                                    title="Mark as Responded"
                                    className="p-1 rounded hover:bg-amber-500/20 text-amber-400/50 hover:text-amber-300 transition">
                                    <MailOpen size={14} />
                                  </button>
                                )}
                                {lead.status !== 'requoted' && (
                                  <button onClick={() => markLead(lead.id, 'mark-requoted')}
                                    title="Mark as Requoted"
                                    className="p-1 rounded hover:bg-emerald-500/20 text-emerald-400/50 hover:text-emerald-300 transition">
                                    <CheckCircle size={14} />
                                  </button>
                                )}
                                {lead.status !== 'skipped' && (
                                  <button onClick={() => markLead(lead.id, 'skip')}
                                    title="Skip this lead"
                                    className="p-1 rounded hover:bg-red-500/20 text-red-400/30 hover:text-red-300 transition">
                                    <XCircle size={14} />
                                  </button>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {leads.length === 0 && (
                      <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-500">No leads found</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {leadsTotal > 50 && (
                <div className="flex items-center justify-center gap-2 py-3 border-t border-white/[0.06]">
                  <button disabled={leadsPage <= 1}
                    onClick={() => loadLeads(selectedCampaign.id, leadsPage - 1)}
                    className="px-3 py-1 text-xs bg-white/5 rounded-lg disabled:opacity-30 hover:bg-white/10 transition">
                    Previous
                  </button>
                  <span className="text-xs text-slate-400">
                    Page {leadsPage} of {Math.ceil(leadsTotal / 50)}
                  </span>
                  <button disabled={leadsPage >= Math.ceil(leadsTotal / 50)}
                    onClick={() => loadLeads(selectedCampaign.id, leadsPage + 1)}
                    className="px-3 py-1 text-xs bg-white/5 rounded-lg disabled:opacity-30 hover:bg-white/10 transition">
                    Next
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        {/* ── UPLOAD MODAL ── */}
        {showUpload && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={e => { if (e.target === e.currentTarget) setShowUpload(false); }}>
            <div className="bg-[#0f1729] border border-white/10 rounded-2xl w-full max-w-2xl overflow-hidden max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
                <h2 className="text-lg font-semibold">
                  {uploadResult && !uploadResult.error ? '📋 Campaign Preview' : 'New Requote Campaign'}
                </h2>
                <button onClick={() => setShowUpload(false)} className="text-slate-400 hover:text-white">✕</button>
              </div>

              {/* Upload form (before upload) */}
              {!uploadResult && (
                <div className="px-6 py-5 space-y-4">
                  <div>
                    <label className="text-xs text-slate-400 font-semibold mb-1 block">Campaign Name</label>
                    <input type="text" value={campaignName} onChange={e => setCampaignName(e.target.value)}
                      placeholder="e.g. Q1 2026 Xdates Requote"
                      className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/40"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 font-semibold mb-1 block">Upload Lead List (.xlsx, .xls, .csv)</label>
                    <input type="file" ref={fileInputRef} accept=".xlsx,.xls,.csv"
                      onChange={e => setUploadFile(e.target.files?.[0] || null)}
                      className="w-full text-sm text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border file:border-white/10 file:bg-white/5 file:text-sm file:text-cyan-300 file:font-semibold hover:file:bg-white/10 file:transition file:cursor-pointer"
                    />
                    <p className="text-[10px] text-slate-500 mt-1">Supports any column layout — we'll auto-detect names, emails, X-dates, carriers, etc.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-slate-400 font-semibold mb-1 block">Touch 1 (days before X-date)</label>
                      <input type="number" value={touch1Days} onChange={e => setTouch1Days(Number(e.target.value))}
                        className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500/40"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 font-semibold mb-1 block">Touch 2 (days before X-date)</label>
                      <input type="number" value={touch2Days} onChange={e => setTouch2Days(Number(e.target.value))}
                        className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500/40"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 font-semibold mb-1 block">Touch 3 (days before X-date)</label>
                      <input type="number" value={touch3Days} onChange={e => setTouch3Days(Number(e.target.value))}
                        className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500/40"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Preview (after upload) */}
              {uploadResult && !uploadResult.error && (
                <div className="px-6 py-5 space-y-4">
                  {/* Stats grid */}
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { label: 'Uploaded', value: uploadResult.total_uploaded, color: 'text-slate-300' },
                      { label: 'Valid Leads', value: uploadResult.total_valid, color: 'text-cyan-400' },
                      { label: 'Will Email', value: uploadResult.would_receive_email, color: 'text-emerald-400' },
                      { label: 'Current Customers', value: uploadResult.nowcerts_check?.current_customers || 0, color: 'text-amber-400' },
                    ].map((s, i) => (
                      <div key={i} className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-3 text-center">
                        <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
                        <div className="text-[10px] text-slate-500 font-semibold mt-0.5">{s.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* Breakdown */}
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4 space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-400">Rows in file</span><span className="text-white font-semibold">{uploadResult.total_uploaded}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">No email (skipped)</span><span className="text-slate-500">{uploadResult.total_skipped}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Duplicates removed</span><span className="text-slate-500">{uploadResult.total_deduped}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Current customers (NowCerts)</span><span className="text-amber-400 font-semibold">{uploadResult.nowcerts_check?.current_customers || 0}</span></div>
                    <div className="flex justify-between border-t border-white/[0.06] pt-2"><span className="text-slate-300 font-semibold">Would receive emails</span><span className="text-emerald-400 font-bold text-base">{uploadResult.would_receive_email}</span></div>
                  </div>

                  {/* Current customers list */}
                  {uploadResult.nowcerts_check?.current_customers > 0 && (
                    <div className="bg-amber-500/5 border border-amber-500/15 rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <AlertTriangle size={16} className="text-amber-400" />
                        <span className="text-sm font-semibold text-amber-300">Current Customers Excluded ({uploadResult.nowcerts_check.current_customers})</span>
                      </div>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {uploadResult.nowcerts_check.current_customer_list?.map((c: any, i: number) => (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <span className="text-amber-400">●</span>
                            <span className="text-slate-300">{c.name}</span>
                            <span className="text-slate-500">{c.email}</span>
                            {c.nowcerts_match && <span className="text-amber-400/60">→ {c.nowcerts_match}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Unchecked leads — need to run Dedup */}
                  {uploadResult.nowcerts_unchecked > 0 && (
                    <div className="bg-blue-500/5 border border-blue-500/15 rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <AlertTriangle size={16} className="text-blue-400" />
                          <span className="text-sm font-semibold text-blue-300">{uploadResult.nowcerts_unchecked} leads still need NowCerts check</span>
                        </div>
                        <span className="text-xs text-slate-500">Run Dedup after confirming campaign</span>
                      </div>
                    </div>
                  )}

                  {/* Sample leads preview */}
                  {uploadResult.sample_leads?.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-slate-400 mb-2">Lead Preview (first {uploadResult.sample_leads.length})</div>
                      <div className="bg-white/[0.02] border border-white/[0.06] rounded-lg overflow-hidden">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-white/[0.06]">
                              <th className="text-left px-3 py-2 text-slate-500 font-semibold">Name</th>
                              <th className="text-left px-3 py-2 text-slate-500 font-semibold">Email</th>
                              <th className="text-left px-3 py-2 text-slate-500 font-semibold">Carrier</th>
                              <th className="text-left px-3 py-2 text-slate-500 font-semibold">X-Date</th>
                            </tr>
                          </thead>
                          <tbody>
                            {uploadResult.sample_leads.map((l: any, i: number) => (
                              <tr key={i} className="border-b border-white/[0.03]">
                                <td className="px-3 py-1.5 text-slate-300">{l.name || '—'}</td>
                                <td className="px-3 py-1.5 text-slate-400">{l.email}</td>
                                <td className="px-3 py-1.5 text-slate-400">{l.carrier || '—'}</td>
                                <td className="px-3 py-1.5 text-slate-400">{l.x_date ? new Date(l.x_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  <div className="bg-blue-500/5 border border-blue-500/15 rounded-lg p-3 text-xs text-blue-300">
                    <strong>⚡ Draft Mode:</strong> No emails will be sent until you activate. Review the preview above and click Activate to start the campaign.
                  </div>
                </div>
              )}

              {/* Error state */}
              {uploadResult?.error && (
                <div className="px-6 py-5">
                  <div className="p-3 rounded-lg text-sm bg-red-500/10 text-red-300 border border-red-500/20">
                    {uploadResult.error}
                  </div>
                </div>
              )}

              {/* Footer buttons */}
              <div className="flex justify-end gap-2 px-6 py-4 border-t border-white/[0.06]">
                {uploadResult && !uploadResult.error ? (
                  <>
                    <button onClick={async () => {
                      try { await axios.post(`${API}/api/campaigns/${uploadResult.campaign_id}/delete-draft`, {}, { headers: headers() }); } catch {}
                      setShowUpload(false); setUploadResult(null); loadCampaigns();
                    }}
                      className="px-4 py-2 text-red-400 hover:text-red-300 text-sm transition">
                      Delete Draft
                    </button>
                    <button onClick={() => { setShowUpload(false); if (uploadResult.campaign_id) loadCampaignDetail(uploadResult.campaign_id); }}
                      className="px-4 py-2 text-slate-400 hover:text-white text-sm transition">
                      View Details
                    </button>
                    <button onClick={async () => {
                      try {
                        await axios.post(`${API}/api/campaigns/${uploadResult.campaign_id}/activate`, {}, { headers: headers() });
                        setShowUpload(false); loadCampaigns();
                        if (uploadResult.campaign_id) loadCampaignDetail(uploadResult.campaign_id);
                      } catch (e: any) { alert(e.response?.data?.detail || 'Activation failed'); }
                    }}
                      className="px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/25 rounded-lg text-emerald-300 text-sm font-semibold transition">
                      ✓ Activate Campaign ({uploadResult.would_receive_email} emails)
                    </button>
                  </>
                ) : uploadResult?.error ? (
                  <button onClick={() => { setUploadResult(null); }}
                    className="px-4 py-2 text-slate-400 hover:text-white text-sm transition">Try Again</button>
                ) : (
                  <>
                    <button onClick={() => setShowUpload(false)}
                      className="px-4 py-2 text-slate-400 hover:text-white text-sm transition">Cancel</button>
                    <button onClick={handleUpload} disabled={!uploadFile || uploading}
                      className="px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/25 rounded-lg text-cyan-300 text-sm font-semibold transition disabled:opacity-40">
                      {uploading ? 'Processing & Checking NowCerts...' : 'Upload & Preview'}
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── EMAIL PREVIEW MODAL ── */}
        {showEmailPreview && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={e => { if (e.target === e.currentTarget) setShowEmailPreview(false); }}>
            <div className="bg-[#0f1729] border border-white/10 rounded-2xl w-full max-w-2xl overflow-hidden max-h-[90vh] flex flex-col">
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
                <div>
                  <h2 className="text-lg font-semibold">Email Preview — Touch {previewTouch}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">Subject: {emailPreviewSubject}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => loadEmailPreview(previewTouch === 1 ? 2 : 1)}
                    className="text-xs px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-lg text-slate-300 font-semibold transition">
                    Switch to Touch {previewTouch === 1 ? '2' : '1'}
                  </button>
                  <button onClick={() => setShowEmailPreview(false)} className="text-slate-400 hover:text-white">✕</button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto bg-[#f4f4f4]">
                <div dangerouslySetInnerHTML={{ __html: emailPreviewHtml }} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
