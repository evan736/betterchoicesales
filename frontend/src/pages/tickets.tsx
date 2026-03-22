import React, { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  Bug, Loader2, ChevronDown, ChevronUp, Clock, CheckCircle2,
  AlertTriangle, XCircle, Image, ExternalLink, Play, ArrowUpRight, Copy, ClipboardCheck
} from 'lucide-react';

const API = process.env.NEXT_PUBLIC_API_URL || '';

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  open: { bg: 'bg-red-500/20', text: 'text-red-300', label: 'Open' },
  in_progress: { bg: 'bg-amber-500/20', text: 'text-amber-300', label: 'In Progress' },
  resolved: { bg: 'bg-emerald-500/20', text: 'text-emerald-300', label: 'Resolved' },
  closed: { bg: 'bg-slate-500/20', text: 'text-slate-400', label: 'Closed' },
};

const PRIORITY_STYLES: Record<string, { bg: string; text: string }> = {
  low: { bg: 'bg-slate-500/20', text: 'text-slate-400' },
  normal: { bg: 'bg-blue-500/20', text: 'text-blue-300' },
  high: { bg: 'bg-amber-500/20', text: 'text-amber-300' },
  critical: { bg: 'bg-red-500/20', text: 'text-red-300' },
};

export default function TicketsPage() {
  const { user, loading } = useAuth();
  const [tickets, setTickets] = useState<any[]>([]);
  const [ticketLoading, setTicketLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState<string>('open');
  const [updating, setUpdating] = useState(false);
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [stats, setStats] = useState<any>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers = () => ({ Authorization: `Bearer ${token}` });

  const copyForDeveloper = (ticket: any) => {
    const screenshotUrl = ticket.has_screenshot || ticket.screenshot_data
      ? `${API}/api/tickets/${ticket.id}/screenshot`
      : null;
    const lines = [
      `## ORBIT Support Ticket #${ticket.id}`,
      `**Priority:** ${(ticket.priority || 'normal').toUpperCase()}`,
      `**Status:** ${ticket.status}`,
      `**Reporter:** ${ticket.reporter_name || ticket.reporter_username}`,
      `**Page:** ${ticket.page_url || 'N/A'}`,
      `**Created:** ${ticket.created_at ? new Date(ticket.created_at).toLocaleString() : 'Unknown'}`,
      ``,
      `### Description`,
      ticket.description || '(no description)',
    ];
    if (ticket.resolution_notes) {
      lines.push('', `### Resolution Notes`, ticket.resolution_notes);
    }
    if (screenshotUrl) {
      lines.push('', `### Screenshot`, screenshotUrl);
    }
    lines.push('', `---`, `Paste this into a Claude session for developer review.`);

    navigator.clipboard.writeText(lines.join('\n')).then(() => {
      setCopiedId(ticket.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  const loadTickets = async () => {
    setTicketLoading(true);
    try {
      const params = filter ? `?status=${filter}` : '';
      const r = await fetch(`${API}/api/tickets${params}`, { headers: headers() });
      const data = await r.json();
      setTickets(data.tickets || []);
    } catch (e) {
      console.error('Failed to load tickets:', e);
    }
    setTicketLoading(false);
  };

  const loadStats = async () => {
    try {
      const r = await fetch(`${API}/api/tickets/stats/summary`, { headers: headers() });
      setStats(await r.json());
    } catch {}
  };

  const loadDetail = async (id: number) => {
    setDetailLoading(true);
    try {
      const r = await fetch(`${API}/api/tickets/${id}`, { headers: headers() });
      setDetail(await r.json());
    } catch {}
    setDetailLoading(false);
  };

  const updateTicket = async (id: number, updates: Record<string, any>) => {
    setUpdating(true);
    try {
      const r = await fetch(`${API}/api/tickets/${id}`, {
        method: 'PATCH',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (r.ok) {
        await loadTickets();
        await loadStats();
        if (expandedId === id) loadDetail(id);
      }
    } catch (e) {
      console.error('Update failed:', e);
    }
    setUpdating(false);
  };

  useEffect(() => {
    if (user && token) { loadTickets(); loadStats(); }
  }, [user, filter]);

  const handleExpand = (id: number) => {
    if (expandedId === id) { setExpandedId(null); setDetail(null); return; }
    setExpandedId(id);
    loadDetail(id);
  };

  if (loading) return null;
  if (!user) return (
    <div className="min-h-screen">
      <div className="glass sticky top-0 z-50 border-b border-white/20 h-14" />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="h-8 w-56 rounded-lg bg-slate-200 animate-pulse mb-6" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          {[1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl bg-slate-200 animate-pulse" />)}
        </div>
        <div className="h-96 rounded-xl bg-slate-200 animate-pulse" />
      </main>
    </div>
  );

  return (
    <div className="min-h-screen page-bg">
      <Navbar />
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold page-title flex items-center gap-3">
              <Bug size={24} /> Support Tickets
            </h1>
            <p className="text-sm page-subtitle mt-1">Issues reported by the team</p>
          </div>
          {stats && (
            <div className="flex items-center gap-4 text-sm">
              <div className="text-center">
                <div className="text-lg font-bold text-red-400">{stats.open}</div>
                <div className="text-xs page-subtitle">Open</div>
              </div>
              <div className="text-center">
                <div className="text-lg font-bold text-amber-400">{stats.in_progress}</div>
                <div className="text-xs page-subtitle">In Progress</div>
              </div>
              <div className="text-center">
                <div className="text-lg font-bold page-subtitle">{stats.total}</div>
                <div className="text-xs page-subtitle">Total</div>
              </div>
            </div>
          )}
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-2 mb-4">
          {[
            { value: 'open', label: 'Open' },
            { value: 'in_progress', label: 'In Progress' },
            { value: 'resolved', label: 'Resolved' },
            { value: '', label: 'All' },
          ].map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f.value
                  ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/50'
                  : 'card-bg page-subtitle hover:text-white'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Ticket List */}
        {ticketLoading ? (
          <div className="text-center py-12 page-subtitle">
            <Loader2 size={24} className="animate-spin mx-auto mb-2" /> Loading tickets...
          </div>
        ) : tickets.length === 0 ? (
          <div className="text-center py-12 page-subtitle">
            <CheckCircle2 size={32} className="mx-auto mb-3 text-emerald-400" />
            <p className="text-sm">No {filter || ''} tickets</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tickets.map(t => {
              const isExpanded = expandedId === t.id;
              const sts = STATUS_STYLES[t.status] || STATUS_STYLES.open;
              const pri = PRIORITY_STYLES[t.priority] || PRIORITY_STYLES.normal;

              return (
                <div key={t.id} className="card-bg rounded-xl border border-white/5 overflow-hidden">
                  <button
                    onClick={() => handleExpand(t.id)}
                    className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-white/5 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-xs font-mono page-subtitle">#{t.id}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${sts.bg} ${sts.text}`}>
                        {sts.label}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${pri.bg} ${pri.text}`}>
                        {t.priority}
                      </span>
                      <span className="text-sm font-medium page-title truncate">{t.title}</span>
                      {t.has_screenshot && <Image size={13} className="text-cyan-400 flex-shrink-0" />}
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-xs page-subtitle">{t.reporter_name || t.reporter_username}</span>
                      <span className="text-xs page-subtitle">
                        {t.created_at ? new Date(t.created_at).toLocaleDateString() : ''}
                      </span>
                      {isExpanded ? <ChevronUp size={16} className="page-subtitle" /> : <ChevronDown size={16} className="page-subtitle" />}
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-white/5 p-4">
                      {detailLoading ? (
                        <div className="py-8 text-center page-subtitle"><Loader2 size={18} className="animate-spin mx-auto" /></div>
                      ) : detail ? (
                        <div className="space-y-4">
                          {/* Description */}
                          <div>
                            <label className="text-xs font-semibold page-subtitle block mb-1">Description</label>
                            <p className="text-sm page-title whitespace-pre-wrap">{detail.description}</p>
                          </div>

                          {/* Screenshot */}
                          {detail.screenshot_data && (
                            <div>
                              <label className="text-xs font-semibold page-subtitle block mb-1">Screenshot</label>
                              <img
                                src={detail.screenshot_data}
                                alt="Screenshot"
                                className="w-full max-h-96 object-contain rounded-lg border border-white/10 cursor-pointer"
                                onClick={() => window.open(detail.screenshot_data, '_blank')}
                              />
                            </div>
                          )}

                          {/* Meta */}
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                            <div><span className="page-subtitle">Reporter:</span> <span className="page-title font-medium">{detail.reporter_name}</span></div>
                            <div><span className="page-subtitle">Page:</span> <span className="page-title font-medium truncate">{detail.page_url?.replace('https://better-choice-web.onrender.com', '') || '—'}</span></div>
                            <div><span className="page-subtitle">Created:</span> <span className="page-title font-medium">{detail.created_at ? new Date(detail.created_at).toLocaleString() : '—'}</span></div>
                            {detail.resolved_at && (
                              <div><span className="page-subtitle">Resolved:</span> <span className="page-title font-medium">{new Date(detail.resolved_at).toLocaleString()} by {detail.resolved_by}</span></div>
                            )}
                          </div>

                          {/* Resolution Notes */}
                          {detail.resolution_notes && (
                            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                              <label className="text-xs font-semibold text-emerald-400 block mb-1">Resolution</label>
                              <p className="text-sm text-emerald-200">{detail.resolution_notes}</p>
                            </div>
                          )}

                          {/* Actions */}
                          {detail.status !== 'closed' && (
                            <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-white/5">
                              {detail.status === 'open' && (
                                <button
                                  onClick={() => updateTicket(t.id, { status: 'in_progress' })}
                                  disabled={updating}
                                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors"
                                >
                                  <Play size={12} /> Start Working
                                </button>
                              )}
                              {(detail.status === 'open' || detail.status === 'in_progress') && (
                                <>
                                  <input
                                    value={resolutionNotes}
                                    onChange={e => setResolutionNotes(e.target.value)}
                                    placeholder="Resolution notes (optional)..."
                                    className="flex-1 min-w-[200px] px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-white placeholder-slate-500 outline-none focus:border-emerald-500"
                                  />
                                  <button
                                    onClick={() => {
                                      updateTicket(t.id, { status: 'resolved', resolution_notes: resolutionNotes || undefined });
                                      setResolutionNotes('');
                                    }}
                                    disabled={updating}
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 transition-colors"
                                  >
                                    <CheckCircle2 size={12} /> Resolve
                                  </button>
                                </>
                              )}
                              <button
                                onClick={() => copyForDeveloper(detail)}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 transition-colors"
                              >
                                {copiedId === t.id ? <><ClipboardCheck size={12} /> Copied!</> : <><Copy size={12} /> Copy for Developer</>}
                              </button>
                              <button
                                onClick={() => updateTicket(t.id, { status: 'closed' })}
                                disabled={updating}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-500/20 text-slate-400 hover:bg-slate-500/30 transition-colors"
                              >
                                <XCircle size={12} /> Close
                              </button>
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
