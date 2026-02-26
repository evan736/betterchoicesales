import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Power, PowerOff, Zap, ExternalLink, Pause, Play, AlertTriangle,
  CheckCircle, Clock, ChevronDown, ChevronUp, Shield,
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

function timeAgo(iso: string) {
  if (!iso) return 'never';
  const d = new Date(iso);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function LeadControlCenter() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [providers, setProviders] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [confirmAction, setConfirmAction] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
    else if (user) loadProviders();
  }, [user, authLoading]);

  // SSE live refresh
  useEffect(() => {
    if (!user) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API}/api/events/stream`);
      es.addEventListener('dashboard:refresh', () => loadProviders());
      es.onerror = () => es?.close();
    } catch {}
    return () => es?.close();
  }, [user]);

  const loadProviders = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/lead-providers`, { headers: headers() });
      setProviders(res.data.providers || []);
      setSummary(res.data.summary || {});
    } catch (e) {
      console.error('Failed to load providers:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleProvider = async (id: number) => {
    setActionLoading(`toggle-${id}`);
    try {
      await axios.post(`${API}/api/lead-providers/${id}/toggle`, {}, { headers: headers() });
      await loadProviders();
    } catch (e) { console.error(e); }
    finally { setActionLoading(null); }
  };

  const pauseAll = async () => {
    setActionLoading('pause-all');
    setConfirmAction(null);
    try {
      await axios.post(`${API}/api/lead-providers/pause-all`, {}, { headers: headers() });
      await loadProviders();
    } catch (e) { console.error(e); }
    finally { setActionLoading(null); }
  };

  const unpauseAll = async () => {
    setActionLoading('unpause-all');
    setConfirmAction(null);
    try {
      await axios.post(`${API}/api/lead-providers/unpause-all`, {}, { headers: headers() });
      await loadProviders();
    } catch (e) { console.error(e); }
    finally { setActionLoading(null); }
  };

  const openAllPortals = () => {
    providers.forEach(p => {
      if (p.portal_url) window.open(p.portal_url, '_blank');
    });
  };

  if (!user) return null;

  const allPaused = providers.length > 0 && providers.every(p => p.is_paused);
  const allActive = providers.length > 0 && providers.every(p => !p.is_paused);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500/20 to-orange-500/20 flex items-center justify-center">
                <Power size={20} className="text-red-400" />
              </div>
              Lead Control Center
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Manage all lead providers from one place
            </p>
          </div>

          {/* Status pill */}
          <div className={`px-4 py-2 rounded-full text-sm font-semibold flex items-center gap-2 ${
            allPaused ? 'bg-red-500/20 text-red-300 border border-red-500/30' :
            allActive ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
            'bg-amber-500/20 text-amber-300 border border-amber-500/30'
          }`}>
            {allPaused ? <PowerOff size={14} /> : allActive ? <Zap size={14} /> : <AlertTriangle size={14} />}
            {allPaused ? 'All Paused' : allActive ? 'All Active' : `${summary.active || 0} Active · ${summary.paused || 0} Paused`}
          </div>
        </div>

        {/* Master Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
          {/* PAUSE ALL */}
          <div className="relative">
            {confirmAction === 'pause' ? (
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-center">
                <p className="text-sm text-red-300 mb-3">Pause ALL {summary.total} providers?</p>
                <div className="flex gap-2 justify-center">
                  <button
                    onClick={pauseAll}
                    disabled={actionLoading === 'pause-all'}
                    className="px-4 py-2 bg-red-500 hover:bg-red-400 rounded-lg text-sm font-semibold text-white transition disabled:opacity-50"
                  >
                    {actionLoading === 'pause-all' ? 'Pausing...' : 'Confirm Pause All'}
                  </button>
                  <button
                    onClick={() => setConfirmAction(null)}
                    className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-slate-300 transition"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmAction('pause')}
                disabled={allPaused}
                className="w-full flex items-center justify-center gap-2 px-4 py-4 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 rounded-xl text-red-300 font-semibold transition disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Pause size={18} />
                Pause All Leads
              </button>
            )}
          </div>

          {/* UNPAUSE ALL */}
          <div className="relative">
            {confirmAction === 'unpause' ? (
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 text-center">
                <p className="text-sm text-emerald-300 mb-3">Activate ALL {summary.total} providers?</p>
                <div className="flex gap-2 justify-center">
                  <button
                    onClick={unpauseAll}
                    disabled={actionLoading === 'unpause-all'}
                    className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 rounded-lg text-sm font-semibold text-white transition disabled:opacity-50"
                  >
                    {actionLoading === 'unpause-all' ? 'Activating...' : 'Confirm Unpause All'}
                  </button>
                  <button
                    onClick={() => setConfirmAction(null)}
                    className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-slate-300 transition"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmAction('unpause')}
                disabled={allActive}
                className="w-full flex items-center justify-center gap-2 px-4 py-4 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 hover:border-emerald-500/40 rounded-xl text-emerald-300 font-semibold transition disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Play size={18} />
                Unpause All Leads
              </button>
            )}
          </div>

          {/* OPEN ALL PORTALS */}
          <button
            onClick={openAllPortals}
            className="w-full flex items-center justify-center gap-2 px-4 py-4 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/20 hover:border-cyan-500/40 rounded-xl text-cyan-300 font-semibold transition"
          >
            <ExternalLink size={18} />
            Open All Portals
          </button>
        </div>

        {/* Provider notice */}
        <div className="bg-amber-500/5 border border-amber-500/15 rounded-xl p-3 mb-6 flex items-start gap-3">
          <Shield size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-amber-300/80 leading-relaxed">
            <strong>Phase 1:</strong> Status tracking is manual — update here after pausing/unpausing on each provider's site.
            <strong> Phase 2</strong> will automate this with direct API calls.
            Click "Open All Portals" to open all dashboards simultaneously.
          </p>
        </div>

        {/* Provider List */}
        {loading ? (
          <div className="space-y-3">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="h-20 rounded-xl bg-white/5 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {providers.map(p => (
              <div
                key={p.id}
                className={`rounded-xl border transition-all ${
                  p.is_paused
                    ? 'bg-red-500/[0.03] border-red-500/15'
                    : 'bg-white/[0.02] border-white/10'
                }`}
              >
                {/* Main row */}
                <div className="flex items-center gap-4 p-4">
                  {/* Emoji / status */}
                  <div className="text-2xl w-10 text-center flex-shrink-0">{p.logo_emoji}</div>

                  {/* Name + status */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{p.name}</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                        p.is_paused
                          ? 'bg-red-500/20 text-red-300'
                          : 'bg-emerald-500/20 text-emerald-300'
                      }`}>
                        {p.is_paused ? 'PAUSED' : 'ACTIVE'}
                      </span>
                    </div>
                    {p.last_status_change && (
                      <p className="text-[10px] text-slate-500 mt-0.5">
                        Changed {timeAgo(p.last_status_change)} by {p.last_status_by || 'system'}
                      </p>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {/* Open portal */}
                    {p.portal_url && (
                      <a
                        href={p.portal_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-cyan-300 transition"
                        title="Open portal"
                      >
                        <ExternalLink size={14} />
                      </a>
                    )}

                    {/* Toggle */}
                    <button
                      onClick={() => toggleProvider(p.id)}
                      disabled={actionLoading === `toggle-${p.id}`}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition disabled:opacity-50 ${
                        p.is_paused
                          ? 'bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/20'
                          : 'bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/20'
                      }`}
                      title={p.is_paused ? 'Unpause' : 'Pause'}
                    >
                      {actionLoading === `toggle-${p.id}` ? (
                        <span className="animate-spin">⟳</span>
                      ) : p.is_paused ? (
                        <><Play size={12} /> Unpause</>
                      ) : (
                        <><Pause size={12} /> Pause</>
                      )}
                    </button>

                    {/* Expand */}
                    <button
                      onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                      className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 transition"
                    >
                      {expandedId === p.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  </div>
                </div>

                {/* Expanded details */}
                {expandedId === p.id && (
                  <div className="px-4 pb-4 pt-0 border-t border-white/5">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
                      <div>
                        <p className="text-[10px] uppercase text-slate-500 mb-1">Portal URL</p>
                        <a href={p.portal_url} target="_blank" rel="noopener" className="text-xs text-cyan-400 hover:underline break-all">
                          {p.portal_url}
                        </a>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase text-slate-500 mb-1">Pause Page</p>
                        <a href={p.pause_url} target="_blank" rel="noopener" className="text-xs text-cyan-400 hover:underline break-all">
                          {p.pause_url || 'Same as portal'}
                        </a>
                      </div>
                    </div>
                    {p.notes && (
                      <div className="mt-3">
                        <p className="text-[10px] uppercase text-slate-500 mb-1">Notes</p>
                        <p className="text-xs text-slate-300 leading-relaxed">{p.notes}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
