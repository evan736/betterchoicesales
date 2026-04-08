import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Phone, Upload, Play, Pause, BarChart2, Users, PhoneOff,
  CheckCircle, XCircle, Clock, AlertTriangle, Trash2, RefreshCw,
  PhoneForwarded, PhoneMissed, Voicemail, Ban, Flame, Zap,
} from 'lucide-react';
import axios from 'axios';
import { toast } from '../components/ui/Toast';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

const STATUS_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  pending: { icon: Clock, color: 'text-slate-400', label: 'Pending' },
  dialed: { icon: Phone, color: 'text-blue-400', label: 'Dialed' },
  transferred: { icon: PhoneForwarded, color: 'text-emerald-400', label: 'Transferred' },
  callback_scheduled: { icon: Clock, color: 'text-cyan-400', label: 'Callback' },
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
  const [dialResults, setDialResults] = useState<any[]>([]);
  const [newName, setNewName] = useState('');
  const [dncPhone, setDncPhone] = useState('');
  const [loading, setLoading] = useState(true);

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
      const params: any = { limit: 50 };
      if (statusFilter) params.status = statusFilter;
      const { data } = await axios.get(`${API}/api/dialer/campaigns/${selected.id}/leads`, { headers: headers(), params });
      setLeads(data.leads);
      setLeadsTotal(data.total);
    } catch (e) { console.error(e); }
  }, [selected, statusFilter]);

  useEffect(() => { fetchCampaigns(); }, []);
  useEffect(() => { fetchStats(); fetchLeads(); }, [selected, statusFilter]);

  const createCampaign = async () => {
    if (!newName.trim()) return;
    try {
      await axios.post(`${API}/api/dialer/campaigns`, {
        name: newName,
        agent_id: 'agent_9053034bcaf1d5142849878c2d',
        agent_name: 'Grace',
        from_number: '+16304267466',
      }, { headers: headers() });
      setNewName('');
      fetchCampaigns();
      toast.success('Campaign created');
    } catch (e) { toast.error('Failed to create campaign'); }
  };

  const toggleCampaign = async () => {
    if (!selected) return;
    const newStatus = selected.status === 'active' ? 'paused' : 'active';
    await axios.patch(`${API}/api/dialer/campaigns/${selected.id}`, { status: newStatus }, { headers: headers() });
    setSelected({ ...selected, status: newStatus });
    fetchCampaigns();
    toast.success(`Campaign ${newStatus}`);
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
      toast.success(`Uploaded: ${data.added} leads added, ${data.skipped_dup} dups, ${data.skipped_expired} expired`);
      fetchStats();
      fetchLeads();
      fetchCampaigns();
    } catch (e) { toast.error('Upload failed'); }
    if (fileRef.current) fileRef.current.value = '';
  };

  const startDialing = async () => {
    if (!selected) return;
    setDialing(true);
    setDialResults([]);
    try {
      const { data } = await axios.post(`${API}/api/dialer/campaigns/${selected.id}/dial`, null, {
        headers: headers(),
        timeout: 600000,
      });
      setDialResults(data.results || []);
      toast.success(`Dialed ${data.dialed} leads`);
      fetchStats();
      fetchLeads();
      fetchCampaigns();
    } catch (e: any) {
      toast.error(e.response?.data?.error || 'Dial session failed');
    }
    setDialing(false);
  };

  const addDNC = async () => {
    if (!dncPhone.trim()) return;
    await axios.post(`${API}/api/dialer/dnc`, { phone: dncPhone }, { headers: headers() });
    setDncPhone('');
    toast.success('Added to DNC');
    fetchStats();
    fetchLeads();
  };

  if (authLoading || loading) return <div className="min-h-screen bg-[#0a0e17]" />;

  return (
    <div className="min-h-screen bg-[#0a0e17] text-white">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Phone className="text-emerald-400" /> AI Dialer Portal
          </h1>
          <div className="flex gap-2">
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="New campaign name..."
              className="bg-[#141a2a] border border-slate-700 rounded px-3 py-2 text-sm"
              onKeyDown={e => e.key === 'Enter' && createCampaign()}
            />
            <button onClick={createCampaign} className="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium">
              + Create
            </button>
          </div>
        </div>

        {/* Campaign selector */}
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {campaigns.map(c => (
            <button
              key={c.id}
              onClick={() => setSelected(c)}
              className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition ${
                selected?.id === c.id
                  ? 'bg-emerald-600 text-white'
                  : 'bg-[#141a2a] text-slate-400 hover:text-white border border-slate-700'
              }`}
            >
              {c.name} ({c.total_leads})
            </button>
          ))}
        </div>

        {selected && (
          <>
            {/* Controls bar */}
            <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4 mb-6 flex items-center gap-4 flex-wrap">
              <button
                onClick={toggleCampaign}
                className={`flex items-center gap-2 px-4 py-2 rounded font-medium text-sm ${
                  selected.status === 'active'
                    ? 'bg-amber-600 hover:bg-amber-500'
                    : 'bg-emerald-600 hover:bg-emerald-500'
                }`}
              >
                {selected.status === 'active' ? <Pause size={16} /> : <Play size={16} />}
                {selected.status === 'active' ? 'Pause' : 'Activate'}
              </button>

              <button
                onClick={startDialing}
                disabled={dialing || selected.status !== 'active'}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 rounded font-medium text-sm"
              >
                <Zap size={16} />
                {dialing ? 'Dialing...' : 'Start Dial Session'}
              </button>

              <label className="flex items-center gap-2 bg-[#1a2035] hover:bg-[#1f2845] border border-slate-600 px-4 py-2 rounded cursor-pointer text-sm">
                <Upload size={16} />
                Upload CSV
                <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={uploadCSV} />
              </label>

              <button onClick={() => { fetchStats(); fetchLeads(); }} className="flex items-center gap-2 text-slate-400 hover:text-white px-3 py-2 text-sm">
                <RefreshCw size={16} /> Refresh
              </button>

              <div className="ml-auto flex items-center gap-2">
                <input
                  value={dncPhone}
                  onChange={e => setDncPhone(e.target.value)}
                  placeholder="Add to DNC..."
                  className="bg-[#0a0e17] border border-slate-700 rounded px-3 py-1.5 text-sm w-36"
                  onKeyDown={e => e.key === 'Enter' && addDNC()}
                />
                <button onClick={addDNC} className="text-red-400 hover:text-red-300 text-sm">
                  <Ban size={16} />
                </button>
              </div>
            </div>

            {/* Stats grid */}
            {stats && (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
                <StatCard label="Total Leads" value={stats.total} icon={<Users size={18} />} color="text-slate-300" />
                <StatCard label="Due Now" value={stats.due_now} icon={<Zap size={18} />} color="text-amber-400" />
                <StatCard label="Transferred" value={stats.statuses?.transferred || 0} icon={<PhoneForwarded size={18} />} color="text-emerald-400" />
                <StatCard label="Callbacks" value={stats.statuses?.callback_scheduled || 0} icon={<Clock size={18} />} color="text-cyan-400" />
                <StatCard label="No Answer" value={stats.statuses?.no_answer || 0} icon={<PhoneMissed size={18} />} color="text-slate-500" />
                <StatCard label="DNC" value={stats.statuses?.do_not_call || 0} icon={<Ban size={18} />} color="text-red-500" />

                {/* Age distribution */}
                <div className="col-span-2 md:col-span-4 lg:col-span-6 bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Lead Age Distribution</h3>
                  <div className="flex gap-2">
                    {Object.entries(stats.age_buckets || {}).map(([bucket, count]: any) => (
                      <div key={bucket} className="flex-1 text-center">
                        <div className="bg-emerald-500/20 rounded-t" style={{ height: `${Math.max(4, (count / stats.total) * 200)}px` }} />
                        <div className="text-xs text-slate-500 mt-1">{bucket}</div>
                        <div className="text-sm font-medium">{count}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Status filter */}
            <div className="flex gap-2 mb-4 flex-wrap">
              <button
                onClick={() => setStatusFilter('')}
                className={`px-3 py-1 rounded text-xs font-medium ${!statusFilter ? 'bg-emerald-600' : 'bg-[#141a2a] text-slate-400 border border-slate-700'}`}
              >
                All
              </button>
              {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
                <button
                  key={key}
                  onClick={() => setStatusFilter(key)}
                  className={`px-3 py-1 rounded text-xs font-medium flex items-center gap-1 ${
                    statusFilter === key ? 'bg-emerald-600' : 'bg-[#141a2a] text-slate-400 border border-slate-700'
                  }`}
                >
                  {cfg.label} {stats?.statuses?.[key] ? `(${stats.statuses[key]})` : ''}
                </button>
              ))}
            </div>

            {/* Leads table */}
            <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50 text-slate-400">
                    <th className="text-left p-3">Name</th>
                    <th className="text-left p-3">Phone</th>
                    <th className="text-left p-3">Carrier</th>
                    <th className="text-left p-3">Age</th>
                    <th className="text-left p-3">Attempts</th>
                    <th className="text-left p-3">Status</th>
                    <th className="text-left p-3">Interest</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map(l => {
                    const cfg = STATUS_CONFIG[l.status] || STATUS_CONFIG.pending;
                    const age = l.request_date ? Math.floor((Date.now() - new Date(l.request_date).getTime()) / 86400000) : '—';
                    const Icon = cfg.icon;
                    return (
                      <tr key={l.id} className="border-b border-slate-800/50 hover:bg-[#1a2035]">
                        <td className="p-3 font-medium">{l.name}</td>
                        <td className="p-3 text-slate-400">{l.phone}</td>
                        <td className="p-3 text-slate-400">{l.carrier || '—'}</td>
                        <td className="p-3">{age}d</td>
                        <td className="p-3">{l.attempts}/10</td>
                        <td className="p-3">
                          <span className={`flex items-center gap-1 ${cfg.color}`}>
                            <Icon size={14} /> {cfg.label}
                          </span>
                        </td>
                        <td className="p-3">
                          {l.interest_level === 'hot' && <span className="text-red-400">🔥 Hot</span>}
                          {l.interest_level === 'warm' && <span className="text-amber-400">🌤️ Warm</span>}
                          {l.interest_level === 'cold' && <span className="text-blue-400">❄️ Cold</span>}
                          {!l.interest_level && <span className="text-slate-600">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {leads.length === 0 && (
                <div className="p-8 text-center text-slate-500">No leads found. Upload a CSV to get started.</div>
              )}
              {leadsTotal > 50 && (
                <div className="p-3 text-center text-slate-500 text-sm">Showing 50 of {leadsTotal} leads</div>
              )}
            </div>

            {/* Dial results */}
            {dialResults.length > 0 && (
              <div className="mt-6 bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
                <h3 className="text-sm font-medium text-slate-400 mb-3">Last Session Results ({dialResults.length} calls)</h3>
                <div className="space-y-1 max-h-60 overflow-y-auto">
                  {dialResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      {r.call_id ? <CheckCircle size={14} className="text-emerald-400" /> : <XCircle size={14} className="text-red-400" />}
                      <span>{r.name}</span>
                      <span className="text-slate-500">{r.phone}</span>
                      {r.call_id && <span className="text-slate-600">Attempt {r.attempt} • {r.age}d old</span>}
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

function StatCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  return (
    <div className="bg-[#141a2a] border border-slate-700/50 rounded-lg p-4">
      <div className={`flex items-center gap-2 ${color} mb-1`}>{icon}<span className="text-xs text-slate-500">{label}</span></div>
      <div className="text-2xl font-bold">{value?.toLocaleString() || 0}</div>
    </div>
  );
}
