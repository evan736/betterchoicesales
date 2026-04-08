import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Phone, Upload, Play, Pause, BarChart2, Users, PhoneOff,
  CheckCircle, XCircle, Clock, AlertTriangle, Trash2, RefreshCw,
  PhoneForwarded, PhoneMissed, Voicemail, Ban, Flame, Zap,
  TrendingUp, Calendar, ArrowRight, Download, Send,
} from 'lucide-react';
import axios from 'axios';
import { toast } from '../components/ui/Toast';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

function fmtDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
function fmtShort(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const STATUS_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-slate-400', label: 'Pending' },
  dialed: { icon: Phone, color: 'text-blue-400', label: 'Dialed' },
  transferred: { icon: PhoneForwarded, color: 'text-emerald-400', label: 'Transferred' },
  callback_scheduled: { icon: Clock, color: 'text-cyan-400', label: 'Callback' },
  interested: { icon: Flame, color: 'text-orange-400', label: 'Interested' },
  already_insured: { icon: CheckCircle, color: 'text-yellow-400', label: 'Has Policy' },
  soft_no: { icon: XCircle, color: 'text-amber-400', label: 'Soft No' },
  hard_no: { icon: XCircle, color: 'text-red-400', label: 'Hard No' },
  voicemail: { icon: Voicemail, color: 'text-purple-400', label: 'Voicemail' },
  no_answer: { icon: PhoneMissed, color: 'text-slate-500', label: 'No Answer' },
  wrong_number: { icon: PhoneOff, color: 'text-red-500', label: 'Wrong #' },
  do_not_call: { icon: Ban, color: 'text-red-600', label: 'DNC' },
  exhausted: { icon: Clock, color: 'text-slate-600', label: 'Exhausted' },
  expired: { icon: AlertTriangle, color: 'text-slate-600', label: 'Expired' },
};

export default function DialerPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [leads, setLeads] = useState<any[]>([]);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [dialing, setDialing] = useState(false);
  const [dialerRunning, setDialerRunning] = useState(false);
  const [dialerInfo, setDialerInfo] = useState<any>(null);
  const [dialResults, setDialResults] = useState<any[]>([]);
  const [newName, setNewName] = useState('');
  const [dncPhone, setDncPhone] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'overview' | 'leads' | 'performance'>('overview');

  const fetchCampaigns = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/dialer/campaigns`, { headers: headers() });
      setCampaigns(data);
      if (data.length > 0 && !selected) setSelected(data[0]);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  const fetchStats = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await axios.get(`${API}/api/dialer/campaigns/${selected.id}/stats`, { headers: headers() });
      setStats(data);
    } catch (e) { console.error(e); }
  }, [selected]);

  const fetchLeads = useCallback(async () => {
    if (!selected) return;
    try {
      const params: any = { limit: 100 };
      if (statusFilter) params.status = statusFilter;
      const { data } = await axios.get(`${API}/api/dialer/campaigns/${selected.id}/leads`, { headers: headers(), params });
      setLeads(data.leads);
      setLeadsTotal(data.total);
    } catch (e) { console.error(e); }
  }, [selected, statusFilter]);

  useEffect(() => { fetchCampaigns(); }, []);
  useEffect(() => { fetchStats(); fetchLeads(); fetchDialerStatus(); }, [selected, statusFilter]);

  // Poll dialer status every 30s when running
  useEffect(() => {
    if (!dialerRunning || !selected) return;
    const interval = setInterval(() => { fetchStats(); fetchDialerStatus(); }, 30000);
    return () => clearInterval(interval);
  }, [dialerRunning, selected]);

  const fetchDialerStatus = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await axios.get(`${API}/api/dialer/campaigns/${selected.id}/dialer-status`, { headers: headers() });
      setDialerRunning(data.running);
      setDialerInfo(data);
    } catch (e) { console.error(e); }
  }, [selected]);

  const createCampaign = async () => {
    if (!newName.trim()) return;
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns`, {
        name: newName, agent_id: 'agent_9053034bcaf1d5142849878c2d',
        agent_name: 'Grace', from_number: '+16304267466',
      }, { headers: headers() });
      setNewName('');
      fetchCampaigns();
      toast.success('Campaign created');
    } catch (e) { toast.error('Failed'); }
  };

  const startAutoDialer = async () => {
    if (!selected) return;
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/start`, {}, { headers: headers() });
      setDialerRunning(true);
      setSelected({ ...selected, status: 'active' });
      fetchCampaigns();
      toast.success('Auto-dialer started — Grace is dialing M-F 10:30AM-6PM CT');
    } catch (e) { toast.error('Failed to start'); }
  };

  const stopAutoDialer = async () => {
    if (!selected) return;
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/stop`, {}, { headers: headers() });
      setDialerRunning(false);
      setSelected({ ...selected, status: 'paused' });
      fetchCampaigns();
      toast.success('Auto-dialer paused');
    } catch (e) { toast.error('Failed to stop'); }
  };

  const uploadCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selected) return;
    const form = new FormData();
    form.append('file', file);
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/upload`, form, {
        headers: { ...headers(), 'Content-Type': 'multipart/form-data' },
      });
      toast.success(`${data.added} leads added, ${data.skipped_dup} dups, ${data.skipped_expired} expired`);
      fetchStats(); fetchLeads(); fetchCampaigns();
    } catch (e) { toast.error('Upload failed'); }
    if (fileRef.current) fileRef.current.value = '';
  };

  // Manual dial kept for testing
  const startDialing = async () => {
    if (!selected) return;
    setDialing(true); setDialResults([]);
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/dial`, null, {
        headers: headers(), timeout: 600000,
      });
      setDialResults(data.results || []);
      toast.success(`Dialed ${data.dialed} leads`);
      fetchStats(); fetchLeads(); fetchCampaigns();
    } catch (e: any) { toast.error(e.response?.data?.error || 'Dial failed'); }
    setDialing(false);
  };

  const markDNC = async (leadId: number) => {
    await axios.post(`${API}/api/dialer/leads/${leadId}/dnc`, {}, { headers: headers() });
    toast.success('Marked DNC');
    fetchStats(); fetchLeads();
  };

  const addDNC = async () => {
    if (!dncPhone.trim()) return;
    await axios.post(`${API}/api/dialer/dnc`, { phone: dncPhone }, { headers: headers() });
    setDncPhone(''); toast.success('Added to DNC'); fetchStats(); fetchLeads();
  };

  const exportToPipeline = async () => {
    if (!selected) return;
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/export-to-pipeline`,
        { statuses: ['transferred', 'callback_scheduled', 'interested', 'soft_no'] }, { headers: headers() });
      toast.success(`${data.exported} leads exported to pipeline`);
    } catch (e) { toast.error('Export failed'); }
  };

  if (authLoading || loading) return <div className="min-h-screen bg-[#0a0e17]" />;

  return (
    <div className="min-h-screen bg-[#0a0e17] text-white">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Phone className="text-emerald-400" /> AI Dialer Portal
          </h1>
          <div className="flex gap-2">
            <input value={newName} onChange={e => setNewName(e.target.value)}
              placeholder="New campaign..." className="bg-[#141a2a] border border-slate-700 rounded px-3 py-2 text-sm"
              onKeyDown={e => e.key === 'Enter' && createCampaign()} />
            <button onClick={createCampaign} className="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium">+ Create</button>
          </div>
        </div>

        {/* Campaign tabs */}
        <div className="flex gap-2 mb-4 overflow-x-auto pb-2">
          {campaigns.map(c => (
            <button key={c.id} onClick={() => setSelected(c)}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap ${selected?.id === c.id ? 'bg-emerald-600 text-white' : 'bg-[#141a2a] text-slate-400 hover:text-white border border-slate-700'}`}>
              {c.name} ({c.total_leads})
            </button>
          ))}
        </div>

        {selected && (
          <>
            {/* Controls */}
            <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4 mb-4 flex items-center gap-3 flex-wrap">
              {dialerRunning || selected.status === 'active' ? (
                <button onClick={stopAutoDialer}
                  className="flex items-center gap-2 px-5 py-2.5 rounded font-medium text-sm bg-red-600 hover:bg-red-500 animate-pulse">
                  <Pause size={16} /> Stop Dialer
                </button>
              ) : (
                <button onClick={startAutoDialer}
                  className="flex items-center gap-2 px-5 py-2.5 rounded font-medium text-sm bg-emerald-600 hover:bg-emerald-500">
                  <Play size={16} /> Start Auto-Dialer
                </button>
              )}
              {dialerRunning && (
                <div className="flex items-center gap-3 text-sm">
                  <span className="flex items-center gap-2 text-emerald-400">
                    <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
                    Auto-Dialing
                  </span>
                  {dialerInfo?.current_number && (
                    <span className="text-slate-500">
                      From: <span className="text-slate-300">{dialerInfo.current_number.replace('+1', '(').replace(/(\d{3})(\d{3})(\d{4})/, '$1) $2-$3')}</span>
                    </span>
                  )}
                  <span className="text-slate-500">
                    {dialerInfo?.total_numbers || 5} numbers rotating every {dialerInfo?.calls_per_number || 60} calls
                  </span>
                </div>
              )}
              <label className="flex items-center gap-2 bg-[#1a2035] hover:bg-[#1f2845] border border-slate-600 px-4 py-2 rounded cursor-pointer text-sm">
                <Upload size={16} /> Upload CSV
                <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={uploadCSV} />
              </label>
              <button onClick={exportToPipeline} className="flex items-center gap-2 bg-purple-600/30 hover:bg-purple-600/50 border border-purple-500/30 px-4 py-2 rounded text-sm text-purple-300">
                <Send size={16} /> Export to Pipeline
              </button>
              <button onClick={() => { fetchStats(); fetchLeads(); }} className="flex items-center gap-2 text-slate-400 hover:text-white px-3 py-2 text-sm">
                <RefreshCw size={16} /> Refresh
              </button>
              <div className="ml-auto flex items-center gap-2">
                <input value={dncPhone} onChange={e => setDncPhone(e.target.value)} placeholder="Add to DNC..."
                  className="bg-[#0a0e17] border border-slate-700 rounded px-3 py-1.5 text-sm w-36"
                  onKeyDown={e => e.key === 'Enter' && addDNC()} />
                <button onClick={addDNC} className="text-red-400 hover:text-red-300 text-sm"><Ban size={16} /></button>
              </div>
            </div>

            {/* Scheduling info */}
            {stats && (stats.last_dialed || stats.next_scheduled) && (
              <div className="flex gap-4 mb-4 text-sm">
                {stats.last_dialed && (
                  <span className="text-slate-400">Last dialed: <span className="text-white">{fmtDate(stats.last_dialed)}</span></span>
                )}
                {stats.next_scheduled && (
                  <span className="text-slate-400">Next scheduled: <span className="text-white">{fmtDate(stats.next_scheduled)}</span></span>
                )}
              </div>
            )}

            {/* Section tabs */}
            <div className="flex gap-1 mb-4">
              {(['overview', 'leads', 'performance'] as const).map(t => (
                <button key={t} onClick={() => setTab(t)}
                  className={`px-4 py-2 rounded-t text-sm font-medium capitalize ${tab === t ? 'bg-[#141a2a] text-white border-t border-x border-slate-700/50' : 'text-slate-500 hover:text-slate-300'}`}>
                  {t}
                </button>
              ))}
            </div>

            {/* Overview Tab */}
            {tab === 'overview' && stats && (
              <div className="space-y-4">
                {/* KPI Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
                  <KPI label="Total" value={stats.total} icon={<Users size={16} />} color="text-slate-300" />
                  <KPI label="Due Now" value={stats.due_now} icon={<Zap size={16} />} color="text-amber-400" />
                  <KPI label="Dialed" value={stats.total_dialed} icon={<Phone size={16} />} color="text-blue-400" />
                  <KPI label="Contacted" value={stats.total_contacted} icon={<CheckCircle size={16} />} color="text-cyan-400" />
                  <KPI label="Transferred" value={stats.total_transferred} icon={<PhoneForwarded size={16} />} color="text-emerald-400" />
                  <KPI label="Callbacks" value={stats.total_callbacks} icon={<Calendar size={16} />} color="text-purple-400" />
                  <KPI label="DNC" value={stats.total_dnc} icon={<Ban size={16} />} color="text-red-500" />
                  <KPI label="Avg Attempts" value={stats.avg_attempts} icon={<TrendingUp size={16} />} color="text-slate-400" />
                </div>

                {/* Rate Cards */}
                <div className="grid grid-cols-3 gap-3">
                  <RateCard label="Answer Rate" rate={stats.answer_rate} sub={`${stats.total_contacted} of ${stats.total_dialed} answered`} color="text-cyan-400" />
                  <RateCard label="Transfer Rate" rate={stats.transfer_rate} sub={`${stats.total_transferred} of ${stats.total_dialed} transferred`} color="text-emerald-400" />
                  <RateCard label="Contact Rate" rate={stats.contact_rate} sub={`${stats.total_contacted} contacts from ${stats.total_dialed} dials`} color="text-blue-400" />
                </div>

                {/* Status breakdown */}
                <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Status Breakdown</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
                    {Object.entries(STATUS_CONFIG).map(([key, cfg]) => {
                      const count = stats.statuses?.[key] || 0;
                      if (count === 0) return null;
                      const Icon = cfg.icon;
                      return (
                        <div key={key} className="flex items-center gap-2 text-sm">
                          <Icon size={14} className={cfg.color} />
                          <span className="text-slate-400">{cfg.label}</span>
                          <span className="font-medium ml-auto">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Age distribution */}
                <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Lead Age Distribution</h3>
                  <div className="flex gap-3">
                    {Object.entries(stats.age_buckets || {}).map(([bucket, count]: any) => (
                      <div key={bucket} className="flex-1 text-center">
                        <div className="bg-emerald-500/20 rounded-t" style={{ height: `${Math.max(8, (count / Math.max(stats.total, 1)) * 200)}px` }} />
                        <div className="text-xs text-slate-500 mt-1">{bucket}</div>
                        <div className="text-sm font-medium">{count?.toLocaleString()}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Performance Tab — conversion by lead age */}
            {tab === 'performance' && stats?.age_performance && (
              <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg overflow-hidden">
                <div className="p-4 border-b border-slate-700/50">
                  <h3 className="text-sm font-medium text-slate-400">Performance by Lead Age — helps you buy leads at the best time</h3>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/50 text-slate-400">
                      <th className="text-left p-3">Age Bucket</th>
                      <th className="text-right p-3">Total</th>
                      <th className="text-right p-3">Dialed</th>
                      <th className="text-right p-3">Contacted</th>
                      <th className="text-right p-3">Transferred</th>
                      <th className="text-right p-3">Contact Rate</th>
                      <th className="text-right p-3">Transfer Rate</th>
                      <th className="text-right p-3">DNC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(stats.age_performance).map(([bucket, p]: any) => (
                      <tr key={bucket} className="border-b border-slate-800/50 hover:bg-[#1a2035]">
                        <td className="p-3 font-medium">{bucket}</td>
                        <td className="p-3 text-right">{p.total}</td>
                        <td className="p-3 text-right">{p.dialed}</td>
                        <td className="p-3 text-right text-cyan-400">{p.contacted}</td>
                        <td className="p-3 text-right text-emerald-400">{p.transferred}</td>
                        <td className="p-3 text-right">
                          <span className={p.contact_rate > 20 ? 'text-emerald-400' : p.contact_rate > 10 ? 'text-amber-400' : 'text-red-400'}>
                            {p.contact_rate}%
                          </span>
                        </td>
                        <td className="p-3 text-right">
                          <span className={p.transfer_rate > 5 ? 'text-emerald-400' : p.transfer_rate > 2 ? 'text-amber-400' : 'text-slate-500'}>
                            {p.transfer_rate}%
                          </span>
                        </td>
                        <td className="p-3 text-right text-red-400">{p.dnc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Leads Tab */}
            {tab === 'leads' && (
              <div>
                {/* Status filter */}
                <div className="flex gap-2 mb-4 flex-wrap">
                  <button onClick={() => setStatusFilter('')}
                    className={`px-3 py-1 rounded text-xs font-medium ${!statusFilter ? 'bg-emerald-600' : 'bg-[#141a2a] text-slate-400 border border-slate-700'}`}>
                    All ({stats?.total || 0})
                  </button>
                  {Object.entries(STATUS_CONFIG).map(([key, cfg]) => {
                    const count = stats?.statuses?.[key] || 0;
                    if (count === 0) return null;
                    return (
                      <button key={key} onClick={() => setStatusFilter(key)}
                        className={`px-3 py-1 rounded text-xs font-medium ${statusFilter === key ? 'bg-emerald-600' : 'bg-[#141a2a] text-slate-400 border border-slate-700'}`}>
                        {cfg.label} ({count})
                      </button>
                    );
                  })}
                </div>

                {/* Leads table */}
                <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-700/50 text-slate-400 text-xs">
                        <th className="text-left p-3">Name</th>
                        <th className="text-left p-3">Phone</th>
                        <th className="text-left p-3">Age</th>
                        <th className="text-left p-3">Attempts</th>
                        <th className="text-left p-3">Status</th>
                        <th className="text-left p-3">Last Dial</th>
                        <th className="text-left p-3">Next Dial</th>
                        <th className="text-left p-3">Interest</th>
                        <th className="text-left p-3"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {leads.map(l => {
                        const cfg = STATUS_CONFIG[l.status] || STATUS_CONFIG.pending;
                        const age = l.request_date ? Math.floor((Date.now() - new Date(l.request_date).getTime()) / 86400000) : null;
                        const Icon = cfg.icon;
                        return (
                          <tr key={l.id} className="border-b border-slate-800/50 hover:bg-[#1a2035]">
                            <td className="p-3 font-medium">{l.name}</td>
                            <td className="p-3 text-slate-400 text-xs">{l.phone}</td>
                            <td className="p-3">{age !== null ? `${age}d` : '—'}</td>
                            <td className="p-3">{l.attempts}/10</td>
                            <td className="p-3">
                              <span className={`flex items-center gap-1 ${cfg.color}`}>
                                <Icon size={13} /> {cfg.label}
                              </span>
                            </td>
                            <td className="p-3 text-xs text-slate-400">{fmtShort(l.last_attempt_at)}</td>
                            <td className="p-3 text-xs text-slate-400">{fmtShort(l.next_attempt_after)}</td>
                            <td className="p-3 text-xs">
                              {l.interest_level === 'hot' && <span className="text-red-400">Hot</span>}
                              {l.interest_level === 'warm' && <span className="text-amber-400">Warm</span>}
                              {l.interest_level === 'cold' && <span className="text-blue-400">Cold</span>}
                              {!l.interest_level && <span className="text-slate-600">—</span>}
                            </td>
                            <td className="p-3">
                              {l.status !== 'do_not_call' && (
                                <button onClick={() => markDNC(l.id)} className="text-red-500/50 hover:text-red-400 text-xs" title="Mark DNC">
                                  <Ban size={14} />
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {leads.length === 0 && <div className="p-8 text-center text-slate-500">No leads found</div>}
                  {leadsTotal > 100 && <div className="p-3 text-center text-slate-500 text-xs">Showing 100 of {leadsTotal.toLocaleString()}</div>}
                </div>
              </div>
            )}

            {/* Dial results */}
            {dialResults.length > 0 && (
              <div className="mt-4 bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
                <h3 className="text-sm font-medium text-slate-400 mb-3">Session Results ({dialResults.length})</h3>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {dialResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs">
                      {r.call_id ? <CheckCircle size={12} className="text-emerald-400" /> : <XCircle size={12} className="text-red-400" />}
                      <span>{r.name}</span>
                      <span className="text-slate-500">{r.phone}</span>
                      {r.call_id && <span className="text-slate-600">#{r.attempt} • {r.age}d</span>}
                      {r.error && <span className="text-red-400">{r.error}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, icon, color }: { label: string; value: number | string; icon: React.ReactNode; color: string }) {
  return (
    <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-3">
      <div className={`flex items-center gap-1.5 ${color} mb-1`}>{icon}<span className="text-xs text-slate-500">{label}</span></div>
      <div className="text-xl font-bold">{typeof value === 'number' ? value.toLocaleString() : value}</div>
    </div>
  );
}

function RateCard({ label, rate, sub, color }: { label: string; rate: number; sub: string; color: string }) {
  return (
    <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-3xl font-bold ${color}`}>{rate}%</div>
      <div className="text-xs text-slate-500 mt-1">{sub}</div>
    </div>
  );
}
