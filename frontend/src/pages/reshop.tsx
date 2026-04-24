import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { reshopAPI } from '../lib/api';
import {
  Plus, Search, Loader2, ChevronDown, ChevronRight, X, User, Phone, Mail, FileText,
  DollarSign, Calendar, AlertTriangle, AlertCircle, CheckCircle2, XCircle, Clock, RefreshCw,
  ArrowRight, Shield, Target, TrendingUp, TrendingDown, Zap, MessageSquare,
  Send, Eye, Filter, BarChart2, Users, Trash2,
} from 'lucide-react';
import { toast } from '../components/ui/Toast';

const STAGES = [
  { key: 'proactive', label: 'Proactive', color: 'purple', icon: <Eye size={14} /> },
  { key: 'new_request', label: 'Urgent Requests', color: 'red', icon: <Plus size={14} /> },
  { key: 'quoting', label: 'Quoting', color: 'amber', icon: <FileText size={14} /> },
  { key: 'quote_ready', label: 'Quote Ready', color: 'cyan', icon: <CheckCircle2 size={14} /> },
  { key: 'presenting', label: 'Quote Presented', color: 'emerald', icon: <Send size={14} /> },
  { key: 'bound', label: 'Rewrote / Renewed', color: 'green', icon: <CheckCircle2 size={14} /> },
  { key: 'lost', label: 'Lost', color: 'red', icon: <XCircle size={14} /> },
];
const CLOSED_STAGES: typeof STAGES = [];

const SOURCES = [
  { value: 'inbound_call', label: 'Inbound Call' },
  { value: 'inbound_email', label: 'Inbound Email' },
  { value: 'producer_referral', label: 'Producer Referral' },
  { value: 'proactive_renewal', label: 'Proactive (Renewal)' },
  { value: 'non_renewal', label: 'Non-Renewal Pending' },
  { value: 'nonpay_escalation', label: 'Non-Pay Escalation' },
  { value: 'walk_in', label: 'Walk-in' },
  { value: 'other', label: 'Other' },
];

const REASONS = [
  { value: 'price_increase', label: 'Price Increase' },
  { value: 'service_issue', label: 'Service Issue' },
  { value: 'coverage_change', label: 'Coverage Change' },
  { value: 'shopping', label: 'Just Shopping' },
  { value: 'nonpay', label: 'Non-Payment' },
  { value: 'renewal_increase', label: 'Renewal Increase' },
  { value: 'non_renewal', label: 'Non-Renewal by Carrier' },
  { value: 'other', label: 'Other' },
];

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'bg-red-500',
  high: 'bg-orange-500',
  normal: 'bg-blue-500',
  low: 'bg-slate-400',
};

export default function ReshopPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [reshops, setReshops] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showClosed, setShowClosed] = useState(false);
  const [selectedReshop, setSelectedReshop] = useState<any>(null);
  const [detailData, setDetailData] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showNonRenewal, setShowNonRenewal] = useState(false);
  const [teamMembers, setTeamMembers] = useState<any[]>([]);
  const [noteText, setNoteText] = useState('');
  const [saving, setSaving] = useState(false);
  const [filterAssigned, setFilterAssigned] = useState<string>('all');
  const [detectingProactive, setDetectingProactive] = useState(false);
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);
  const [attemptTarget, setAttemptTarget] = useState<{ reshop: any; attemptNumber: number } | null>(null);
  const [attemptSaving, setAttemptSaving] = useState(false);

  // Pipeline / Report view toggle
  const [viewMode, setViewMode] = useState<'pipeline' | 'report'>('pipeline');
  const [reportData, setReportData] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportPreset, setReportPreset] = useState<'this_month' | 'last_month' | 'ytd' | 'custom'>('this_month');
  const [reportStart, setReportStart] = useState<string>('');
  const [reportEnd, setReportEnd] = useState<string>('');

  const isManager = user?.role === 'admin' || user?.role === 'retention_specialist' || user?.role === 'manager';
  const isProducer = user?.role === 'producer';

  useEffect(() => {
    if (!user) { router.push('/'); return; }
    loadData();
    loadTeam();
  }, [user]);

  // SSE live updates
  useEffect(() => {
    if (!user) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${baseUrl}/api/events/stream`);
      es.addEventListener('reshop:new', () => loadData());
      es.addEventListener('reshop:updated', () => loadData());
      es.onerror = () => es?.close();
    } catch {}
    return () => es?.close();
  }, [user]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [reshopsRes, statsRes] = await Promise.all([
        reshopAPI.list({ show_closed: true, search: search || undefined }),
        reshopAPI.stats(),
      ]);
      setReshops(reshopsRes.data.reshops);
      setStats(statsRes.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [showClosed, search]);

  useEffect(() => { if (user) loadData(); }, [showClosed]);

  const loadTeam = async () => {
    try {
      const r = await reshopAPI.teamMembers();
      setTeamMembers(r.data.members);
    } catch {}
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  const openDetail = async (reshop: any) => {
    setSelectedReshop(reshop);
    setDetailLoading(true);
    try {
      const r = await reshopAPI.get(reshop.id);
      setDetailData(r.data);
    } catch {}
    setDetailLoading(false);
  };

  const handleStageMove = async (reshopId: number, newStage: string) => {
    try {
      await reshopAPI.moveStage(reshopId, newStage);
      loadData();
      if (selectedReshop?.id === reshopId) openDetail({ id: reshopId });
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to move');
    }
  };

  const handleUpdate = async (reshopId: number, data: any) => {
    setSaving(true);
    try {
      await reshopAPI.update(reshopId, data);
      loadData();
      if (selectedReshop?.id === reshopId) openDetail({ id: reshopId });
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to update');
    }
    setSaving(false);
  };

  const handleDelete = async (reshopId: number, customerName: string) => {
    if (!confirm(`Delete reshop for ${customerName}? This cannot be undone.`)) return;
    try {
      await reshopAPI.remove(reshopId);
      toast.success(`Deleted reshop for ${customerName}`);
      if (selectedReshop?.id === reshopId) {
        setSelectedReshop(null);
        setDetailData(null);
      }
      loadData();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to delete');
    }
  };

  const handleAddNote = async (reshopId: number) => {
    if (!noteText.trim()) return;
    try {
      await reshopAPI.addNote(reshopId, noteText);
      setNoteText('');
      openDetail({ id: reshopId });
    } catch {}
  };

  const handleLogAttempt = async (answered: boolean) => {
    if (!attemptTarget) return;
    setAttemptSaving(true);
    try {
      const res = await reshopAPI.logAttempt(
        attemptTarget.reshop.id,
        attemptTarget.attemptNumber,
        answered,
      );
      const email = res.data?.email || {};
      if (email.sent) {
        toast.success(`Attempt ${attemptTarget.attemptNumber} logged — ${answered ? 'thank-you' : 'follow-up'} email sent`);
      } else if (!attemptTarget.reshop.customer_email) {
        toast.warning(`Attempt ${attemptTarget.attemptNumber} logged — no customer email on file, email skipped`);
      } else {
        toast.warning(`Attempt ${attemptTarget.attemptNumber} logged — email failed: ${email.error || 'unknown'}`);
      }
      setAttemptTarget(null);
      loadData();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to log attempt');
    }
    setAttemptSaving(false);
  };

  const handleDetectProactive = async () => {
    setDetectingProactive(true);
    try {
      const r = await reshopAPI.detectProactive(60, 10);
      toast.success(`Scan complete: ${r.data.created} new proactive reshops created, ${r.data.skipped} already tracked, ${r.data.policies_checked} policies checked.`);
      loadData();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Detection failed');
    }
    setDetectingProactive(false);
  };

  // Compute ISO date strings for a given preset
  const computePresetRange = (preset: string): [string, string] => {
    const now = new Date();
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    if (preset === 'last_month') {
      const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const last = new Date(now.getFullYear(), now.getMonth(), 0);
      return [iso(first), iso(last)];
    }
    if (preset === 'ytd') {
      return [iso(new Date(now.getFullYear(), 0, 1)), iso(now)];
    }
    // this_month default
    return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)];
  };

  const loadReport = useCallback(async (preset?: string, customStart?: string, customEnd?: string) => {
    setReportLoading(true);
    try {
      let startStr = customStart;
      let endStr = customEnd;
      if (preset && preset !== 'custom') {
        const [s, e] = computePresetRange(preset);
        startStr = s;
        endStr = e;
        setReportStart(s);
        setReportEnd(e);
      }
      const r = await reshopAPI.outcomeReport(startStr, endStr);
      setReportData(r.data);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to load report');
    }
    setReportLoading(false);
  }, []);

  // Load the report the first time the user switches to the tab
  useEffect(() => {
    if (viewMode === 'report' && !reportData) {
      loadReport('this_month');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode]);

  // Group reshops by stage
  const byStage: Record<string, any[]> = {};
  for (const s of [...STAGES, ...CLOSED_STAGES]) byStage[s.key] = [];
  const now = Date.now();
  const HOURS_48 = 48 * 60 * 60 * 1000;
  for (const r of reshops) {
    // Map old stages to new columns
    let stage = r.stage;
    if (stage === 'renewed') stage = 'bound';           // renewed → rewrote/renewed
    if (stage === 'cancelled') stage = 'lost';           // cancelled → lost

    // Hide bound/lost items after 48 hours
    if (stage === 'bound' || stage === 'lost') {
      const closedTime = new Date(r.completed_at || r.stage_updated_at || r.updated_at || r.created_at).getTime();
      if (now - closedTime > HOURS_48) continue;
    }

    if (byStage[stage]) byStage[stage].push(r);
    else byStage['new_request']?.push(r);
  }

  // Filter by assigned
  const filteredByStage = (stage: string) => {
    let items = byStage[stage] || [];
    if (filterAssigned !== 'all') {
      items = items.filter(r => String(r.assigned_to) === filterAssigned || (!r.assigned_to && filterAssigned === 'unassigned'));
    }
    // Sort by renewal date (earliest first — most urgent at top)
    items.sort((a, b) => {
      const dateA = a.renewal_date || a.expiration_date || '';
      const dateB = b.renewal_date || b.expiration_date || '';
      if (!dateA && !dateB) return 0;
      if (!dateA) return 1;
      if (!dateB) return -1;
      return new Date(dateA).getTime() - new Date(dateB).getTime();
    });
    return items;
  };

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
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <div className="max-w-[1600px] mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <Target size={24} className="text-blue-600" />
              Reshop Pipeline
            </h1>
          </div>
          <div className="flex items-center gap-3">
            {isManager && (
              <button
                onClick={handleDetectProactive}
                disabled={detectingProactive}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-lg hover:bg-purple-100 transition-colors disabled:opacity-50"
              >
                {detectingProactive ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                Scan Renewals
              </button>
            )}
            <button
              onClick={() => setShowNonRenewal(true)}
              className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors shadow-sm"
            >
              <AlertCircle size={15} />Non-Renewal
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              <Plus size={15} />New Reshop
            </button>
          </div>
        </div>

        {/* View toggle: Pipeline / Report */}
        <div className="flex items-center gap-1 p-1 bg-white border border-slate-200 rounded-lg mb-5 w-fit">
          <button
            onClick={() => setViewMode('pipeline')}
            className={`px-4 py-1.5 text-sm font-semibold rounded-md transition-colors ${
              viewMode === 'pipeline'
                ? 'bg-slate-900 text-white shadow-sm'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            Pipeline
          </button>
          <button
            onClick={() => setViewMode('report')}
            className={`px-4 py-1.5 text-sm font-semibold rounded-md transition-colors ${
              viewMode === 'report'
                ? 'bg-slate-900 text-white shadow-sm'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            Report
          </button>
        </div>

        {viewMode === 'pipeline' && (<>
        {/* Stats Bar */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <StatPill label="Active" value={stats.total_active} icon={<Target size={14} />} color="blue" />
            <StatPill
              label="This Month"
              value={`${stats.bound_this_month}W / ${stats.lost_this_month}L · ${stats.win_rate}%`}
              icon={<TrendingUp size={14} />}
              color="emerald"
            />
            <StatPill label="Savings" value={`$${(stats.savings_this_month || 0).toLocaleString()}`} icon={<DollarSign size={14} />} color="emerald" />
            <StatPill label="Urgent / Expiring Soon" value={`${stats.urgent_count} / ${stats.expiring_soon}`} icon={<AlertTriangle size={14} />} color="amber" />
          </div>
        )}

        {/* Controls */}
        <div className="flex items-center gap-3 mb-5">
          <form onSubmit={handleSearch} className="flex-1 flex gap-2">
            <div className="relative flex-1 max-w-sm">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search by name, policy, carrier..."
                className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:border-blue-300 focus:ring-1 focus:ring-blue-200 outline-none"
              />
            </div>
            <button type="submit" className="px-3 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50">
              Search
            </button>
          </form>

          <select
            value={filterAssigned}
            onChange={e => setFilterAssigned(e.target.value)}
            className="px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white"
          >
            <option value="all">All Assignees</option>
            <option value="unassigned">Unassigned</option>
            {teamMembers.map(m => (
              <option key={m.id} value={String(m.id)}>{m.name}</option>
            ))}
          </select>

          <button onClick={loadData} className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
            <RefreshCw size={16} />
          </button>
        </div>

        {/* Kanban Board */}
        {loading ? (
          <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 400 }}>
            {STAGES.map(s => (
              <div key={s.key} className="flex-shrink-0" style={{ width: 240 }}>
                <div className="rounded-lg p-2 mb-2 h-9 bg-slate-200 animate-pulse" />
                {[1,2,3].map(i => (
                  <div key={i} className="rounded-lg mb-2 p-4 bg-slate-200 animate-pulse" style={{ height: 100 }} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 400 }}>
            {STAGES.map(stage => {
              const items = filteredByStage(stage.key);
              const isDragOver = dragOverStage === stage.key;
              return (
                <div
                  key={stage.key}
                  className={`flex-shrink-0 w-[240px] transition-all ${isDragOver ? 'scale-[1.01]' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    setDragOverStage(stage.key);
                  }}
                  onDragLeave={() => setDragOverStage(null)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOverStage(null);
                    const reshopId = parseInt(e.dataTransfer.getData('reshopId'));
                    if (reshopId) handleStageMove(reshopId, stage.key);
                  }}
                >
                  {/* Column header — single clean row with subtle count badge */}
                  <div className="reshop-col-header mb-3">
                    <span className={`text-${stage.color}-500 flex-shrink-0`}>{stage.icon}</span>
                    <span className="reshop-col-header__label">{stage.label}</span>
                    <span className="reshop-col-header__count">
                      {items.length}
                    </span>
                  </div>
                  {/* Column body — transparent so white cards pop; drag target still highlighted */}
                  <div className={`space-y-2 min-h-[100px] p-1 rounded-lg transition-all ${
                    isDragOver
                      ? 'bg-blue-50 border-2 border-dashed border-blue-300'
                      : ''
                  }`}>
                    {items.map(r => (
                      <ReshopCard
                        key={r.id}
                        reshop={r}
                        onOpen={() => openDetail(r)}
                        onMove={(s: string) => handleStageMove(r.id, s)}
                        onDelete={() => handleDelete(r.id, r.customer_name)}
                        onAttempt={(n: number) => setAttemptTarget({ reshop: r, attemptNumber: n })}
                        stages={STAGES}
                        canManage={isManager}
                      />
                    ))}
                    {items.length === 0 && (
                      <div className="text-[11px] text-slate-400 text-center py-4 italic">
                        —
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

          </div>
        )}
        </>)}

        {viewMode === 'report' && (
          <ReshopOutcomeReport
            data={reportData}
            loading={reportLoading}
            preset={reportPreset}
            startDate={reportStart}
            endDate={reportEnd}
            onPresetChange={(p: any) => {
              setReportPreset(p);
              if (p !== 'custom') loadReport(p);
            }}
            onCustomDateChange={(s: string, e: string) => {
              setReportStart(s);
              setReportEnd(e);
              if (s && e) loadReport('custom', s, e);
            }}
            onRefresh={() => loadReport(reportPreset, reportStart, reportEnd)}
          />
        )}
      </div>

      {/* Detail Drawer */}
      {selectedReshop && (
        <DetailDrawer
          data={detailData}
          loading={detailLoading}
          onClose={() => { setSelectedReshop(null); setDetailData(null); }}
          onUpdate={(d: any) => handleUpdate(selectedReshop.id, d)}
          onMove={(s: string) => handleStageMove(selectedReshop.id, s)}
          onDelete={() => handleDelete(selectedReshop.id, detailData?.customer_name || selectedReshop.customer_name || 'this customer')}
          noteText={noteText}
          setNoteText={setNoteText}
          onAddNote={() => handleAddNote(selectedReshop.id)}
          teamMembers={teamMembers}
          isManager={isManager}
          saving={saving}
        />
      )}

      {/* Attempt modal */}
      {attemptTarget && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={() => !attemptSaving && setAttemptTarget(null)}>
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                <span className="text-blue-700 font-bold">{attemptTarget.attemptNumber}</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900">Log Attempt {attemptTarget.attemptNumber}</h3>
                <p className="text-xs text-slate-500">{attemptTarget.reshop.customer_name}</p>
              </div>
            </div>
            <div className="border-t border-slate-100 pt-4 mb-5">
              <p className="text-slate-700 text-sm mb-1">Did they answer?</p>
              {!attemptTarget.reshop.customer_email && (
                <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-2">
                  ⚠ No email on file — attempt will be logged but no email sent.
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handleLogAttempt(true)}
                disabled={attemptSaving}
                className="flex flex-col items-center justify-center py-4 rounded-lg bg-emerald-50 border-2 border-emerald-200 hover:bg-emerald-100 hover:border-emerald-400 transition-all disabled:opacity-50 disabled:cursor-wait"
              >
                <span className="text-2xl mb-1">✓</span>
                <span className="text-sm font-bold text-emerald-700">Yes — they answered</span>
                <span className="text-[10px] text-emerald-600 mt-0.5">Sends thank-you email</span>
              </button>
              <button
                onClick={() => handleLogAttempt(false)}
                disabled={attemptSaving}
                className="flex flex-col items-center justify-center py-4 rounded-lg bg-slate-50 border-2 border-slate-200 hover:bg-slate-100 hover:border-slate-400 transition-all disabled:opacity-50 disabled:cursor-wait"
              >
                <span className="text-2xl mb-1">✗</span>
                <span className="text-sm font-bold text-slate-700">No — no answer</span>
                <span className="text-[10px] text-slate-500 mt-0.5">Sends "we tried" email</span>
              </button>
            </div>
            <button
              onClick={() => setAttemptTarget(null)}
              disabled={attemptSaving}
              className="mt-4 w-full text-center text-xs text-slate-500 hover:text-slate-700 py-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); loadData(); }}
          isProducer={isProducer}
        />
      )}

      {/* Non-Renewal Modal */}
      {showNonRenewal && (
        <CreateModal
          onClose={() => setShowNonRenewal(false)}
          onCreated={() => { setShowNonRenewal(false); loadData(); }}
          isProducer={isProducer}
          nonRenewalMode
        />
      )}
    </div>
  );
}

// ── Outcome Report ───────────────────────────────────────────────
const ReshopOutcomeReport: React.FC<{
  data: any;
  loading: boolean;
  preset: string;
  startDate: string;
  endDate: string;
  onPresetChange: (p: string) => void;
  onCustomDateChange: (s: string, e: string) => void;
  onRefresh: () => void;
}> = ({ data, loading, preset, startDate, endDate, onPresetChange, onCustomDateChange, onRefresh }) => {
  const PRESETS = [
    { key: 'this_month', label: 'This Month' },
    { key: 'last_month', label: 'Last Month' },
    { key: 'ytd', label: 'Year to Date' },
    { key: 'custom', label: 'Custom Range' },
  ];

  const fmtDate = (iso?: string) => {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch { return iso; }
  };

  const fmtMoney = (n?: number | null) => {
    if (n === null || n === undefined) return '—';
    return `$${Math.round(n).toLocaleString()}`;
  };

  const s = data?.summary;
  const agents = data?.by_agent || [];
  const details = data?.details || [];

  return (
    <div className="space-y-5">
      {/* Range controls */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <div className="flex items-center gap-2 flex-wrap">
          {PRESETS.map(p => (
            <button
              key={p.key}
              onClick={() => onPresetChange(p.key)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
                preset === p.key
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {p.label}
            </button>
          ))}
          {preset === 'custom' && (
            <div className="flex items-center gap-2 ml-2">
              <input
                type="date"
                value={startDate}
                onChange={e => onCustomDateChange(e.target.value, endDate)}
                className="px-2 py-1 text-xs border border-slate-300 rounded"
                style={{ color: '#0f172a', backgroundColor: '#ffffff' }}
              />
              <span className="text-xs text-slate-500">→</span>
              <input
                type="date"
                value={endDate}
                onChange={e => onCustomDateChange(startDate, e.target.value)}
                className="px-2 py-1 text-xs border border-slate-300 rounded"
                style={{ color: '#0f172a', backgroundColor: '#ffffff' }}
              />
            </div>
          )}
          <button
            onClick={onRefresh}
            className="ml-auto p-1.5 text-slate-400 hover:text-slate-600 rounded hover:bg-slate-100"
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>
        {data?.window && (
          <div className="text-xs text-slate-500 mt-2.5">
            Showing outcomes from <strong className="text-slate-700">{fmtDate(data.window.start_date)}</strong> through <strong className="text-slate-700">{fmtDate(data.window.end_date)}</strong>
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-400">Loading report...</div>
      ) : !data ? (
        <div className="text-center py-12 text-slate-400">No data yet. Pick a range above.</div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs text-slate-500 font-medium uppercase tracking-wide">Rewrote</div>
              <div className="text-3xl font-bold text-emerald-600 mt-1 tabular-nums">{s.rewrote}</div>
              <div className="text-[11px] text-slate-500 mt-0.5">policies saved</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs text-slate-500 font-medium uppercase tracking-wide">Lost</div>
              <div className="text-3xl font-bold text-red-500 mt-1 tabular-nums">{s.lost}</div>
              <div className="text-[11px] text-slate-500 mt-0.5">policies not saved</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs text-slate-500 font-medium uppercase tracking-wide">Win Rate</div>
              <div className="text-3xl font-bold text-slate-900 mt-1 tabular-nums">{s.win_rate}%</div>
              <div className="text-[11px] text-slate-500 mt-0.5">{s.total_resolved} resolved</div>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs text-slate-500 font-medium uppercase tracking-wide">Savings</div>
              <div className="text-3xl font-bold text-emerald-600 mt-1 tabular-nums">{fmtMoney(s.total_savings)}</div>
              <div className="text-[11px] text-slate-500 mt-0.5">premium retained</div>
            </div>
          </div>

          {/* Per-agent breakdown */}
          {agents.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100">
                <h3 className="text-sm font-semibold text-slate-900">By Agent</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50">
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Agent</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Rewrote</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Lost</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Total</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Win Rate</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Savings</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {agents.map((a: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 font-medium text-slate-800">{a.agent_name}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-emerald-600 font-semibold">{a.rewrote}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-red-500 font-semibold">{a.lost}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-slate-700">{a.total}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-slate-700">{a.win_rate}%</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-emerald-700 font-medium">{fmtMoney(a.savings)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Detail list */}
          {details.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Detail ({details.length})</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50">
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Resolved</th>
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Customer</th>
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Carrier</th>
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Agent</th>
                      <th className="text-left px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Outcome</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Premium</th>
                      <th className="text-right px-4 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide">Savings</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {details.map((d: any) => (
                      <tr key={d.id} className="hover:bg-slate-50">
                        <td className="px-4 py-2 text-xs text-slate-500 tabular-nums">{fmtDate(d.completed_at)}</td>
                        <td className="px-4 py-2 font-medium text-slate-800">{d.customer_name || '—'}</td>
                        <td className="px-4 py-2 text-slate-600">
                          {d.carrier || '—'}
                          {d.policy_number && <span className="text-slate-400 text-xs ml-1">#{d.policy_number}</span>}
                        </td>
                        <td className="px-4 py-2 text-slate-600">{d.assignee_name || '—'}</td>
                        <td className="px-4 py-2">
                          {d.stage === 'lost' ? (
                            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-red-50 text-red-700 border border-red-200">Lost</span>
                          ) : (
                            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">Rewrote</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-slate-700">{fmtMoney(d.current_premium)}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-emerald-700 font-medium">
                          {d.stage !== 'lost' ? fmtMoney(d.premium_savings) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ── Stat Pill ────────────────────────────────────────────────────
const StatPill: React.FC<{ label: string; value: any; icon: React.ReactNode; color: string }> = ({ label, value, icon, color }) => (
  <div className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-white border border-slate-200`}>
    <span className={`text-${color}-500`}>{icon}</span>
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-bold text-slate-800">{value}</div>
    </div>
  </div>
);

// ── Reshop Card ──────────────────────────────────────────────────
// Overdue-lead policy: reshops whose expiration date is 7+ days in the past
// force the owning agent to mark the lead Renewed/Rewrote (stage='bound') or
// Lost before they can do anything else with the card. New hires are exempt
// for their first 30 days. Currently the only new hire being exempted is
// April Wilson (hired 2026-04-22). Her exemption expires 2026-05-22.
const OVERDUE_DAYS_THRESHOLD = 7;
const APRIL_USER_ID = 19;
const APRIL_EXEMPTION_EXPIRES = new Date('2026-05-22T00:00:00');

function isUserExemptFromForcedResolution(userId: number | undefined): boolean {
  if (userId === APRIL_USER_ID && Date.now() < APRIL_EXEMPTION_EXPIRES.getTime()) {
    return true;
  }
  return false;
}

const ReshopCard: React.FC<{
  reshop: any; onOpen: () => void; onMove: (s: string) => void;
  onDelete: () => void;
  onAttempt: (attemptNumber: number) => void;
  stages: any[]; canManage: boolean;
}> = ({ reshop, onOpen, onMove, onDelete, onAttempt, stages, canManage }) => {
  const r = reshop;
  const daysUntilExp = r.expiration_date
    ? Math.ceil((new Date(r.expiration_date).getTime() - Date.now()) / 86400000)
    : null;
  const isUrgent = r.priority === 'urgent' || r.priority === 'high';
  const isExpiringSoon = daysUntilExp !== null && daysUntilExp <= 14 && daysUntilExp >= 0;
  const isNonRenewal = r.source === 'non_renewal';

  // Forced-decision logic: expired 7+ days ago AND still open (not bound/lost)
  const isOpen = !['bound','lost','cancelled','renewed'].includes(r.stage);
  const isOverdue = daysUntilExp !== null && daysUntilExp <= -OVERDUE_DAYS_THRESHOLD && isOpen;
  // Exempt: assignee is in their grace period (April during onboarding)
  const assigneeExempt = isUserExemptFromForcedResolution(r.assigned_to);
  // Show banner only if overdue AND assignee isn't exempt
  const forceResolve = isOverdue && !assigneeExempt;

  // Next stage
  const currentIdx = stages.findIndex(s => s.key === r.stage);
  const nextStage = currentIdx < stages.length - 1 ? stages[currentIdx + 1] : null;

  return (
    <div
      onClick={forceResolve ? (e) => e.stopPropagation() : onOpen}
      draggable={canManage && !forceResolve}
      onDragStart={(e) => {
        if (!canManage || forceResolve) { e.preventDefault(); return; }
        e.dataTransfer.setData('reshopId', String(r.id));
        e.dataTransfer.effectAllowed = 'move';
        (e.currentTarget as HTMLElement).style.opacity = '0.5';
      }}
      onDragEnd={(e) => {
        (e.currentTarget as HTMLElement).style.opacity = '1';
      }}
      className={`reshop-card group transition-all ${
        forceResolve
          ? 'reshop-card--force'
          : isNonRenewal
            ? 'reshop-card--nonrenewal'
            : isUrgent
              ? 'reshop-card--urgent'
              : ''
      } ${
        !forceResolve && canManage ? 'cursor-grab active:cursor-grabbing' : ''
      } ${!forceResolve ? 'cursor-pointer' : ''}`}
    >
      {/* Customer identity strip — ALWAYS visible, even in force-resolve state.
          Agents need to know WHO they're deciding on. */}
      {forceResolve && (
        <div className="flex items-center gap-2 mb-2 pb-2" style={{ borderBottom: '1px solid rgba(239, 68, 68, 0.3)' }}>
          {r.assignee_name && (
            <div
              title={r.assignee_name}
              className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white ${
                r.assignee_name.includes('Salma') ? 'bg-purple-500' :
                r.assignee_name.includes('Michelle') ? 'bg-cyan-500' :
                r.assignee_name.includes('April') ? 'bg-amber-500' :
                'bg-slate-400'
              }`}
            >
              {r.assignee_name.split(' ').map((n: string) => n[0]).slice(0, 2).join('')}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="reshop-card__name truncate">{r.customer_name}</div>
            {(r.carrier || r.line_of_business || r.policy_number) && (
              <div className="reshop-card__subtitle truncate">
                {[
                  r.carrier,
                  r.line_of_business,
                  r.policy_number ? `#${r.policy_number}` : null,
                ].filter(Boolean).join(' · ')}
              </div>
            )}
            {(r.current_premium || r.renewal_premium) && (
              <div className="flex items-center gap-1.5 mt-1">
                {r.current_premium && (
                  <span className="reshop-card__premium">
                    ${Number(r.current_premium).toLocaleString()}
                  </span>
                )}
                {r.renewal_premium && r.current_premium && Number(r.renewal_premium) > Number(r.current_premium) && (
                  <span className="reshop-card__premium-hike">
                    → ${Number(r.renewal_premium).toLocaleString()}
                    <span className="text-[10px] ml-0.5">
                      +{Math.round(((Number(r.renewal_premium) - Number(r.current_premium)) / Number(r.current_premium)) * 100)}%
                    </span>
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Forced-decision banner — shown when lead is 7+ days past expiration */}
      {forceResolve && (
        <div className="mb-0 px-2 py-2 bg-red-600 text-white rounded">
          <div className="flex items-center gap-1.5 mb-1.5">
            <AlertCircle size={12} className="flex-shrink-0" />
            <span className="text-[11px] font-bold tracking-wide uppercase">
              Expired {Math.abs(daysUntilExp!)} days ago
            </span>
          </div>
          <p className="text-[10px] mb-2 text-red-50 leading-tight">
            Resolve this lead to continue working others.
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              onClick={(e) => { e.stopPropagation(); onMove('bound'); }}
              disabled={!canManage}
              className="px-2 py-1.5 text-[11px] font-bold rounded bg-white text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 transition-colors"
            >
              ✓ Renewed/Rewrote
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onMove('lost'); }}
              disabled={!canManage}
              className="px-2 py-1.5 text-[11px] font-bold rounded bg-white text-slate-700 hover:bg-slate-100 disabled:opacity-50 transition-colors"
            >
              ✗ Lost
            </button>
          </div>
        </div>
      )}
      {/* Card body — hides when the forced-decision banner is active */}
      {!forceResolve && (
        <>
          {/* Top row: small assignee chip + customer name + non-renewal pill + priority dot */}
          <div className="flex items-start gap-2 mb-1">
            {r.assignee_name && (
              <div
                title={r.assignee_name}
                className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white ${
                  r.assignee_name.includes('Salma') ? 'bg-purple-500' :
                  r.assignee_name.includes('Michelle') ? 'bg-cyan-500' :
                  r.assignee_name.includes('April') ? 'bg-amber-500' :
                  'bg-slate-400'
                }`}
              >
                {r.assignee_name.split(' ').map((n: string) => n[0]).slice(0, 2).join('')}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <div className="reshop-card__name truncate">{r.customer_name}</div>
                {isNonRenewal && (
                  <span className="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500 text-white tracking-wide">
                    NON-RENEWAL
                  </span>
                )}
                <div
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${PRIORITY_COLORS[r.priority] || 'bg-slate-300'}`}
                  title={`Priority: ${r.priority}`}
                />
              </div>
              {(r.carrier || r.line_of_business || r.policy_number) && (
                <div className="reshop-card__subtitle truncate mt-0.5">
                  {[
                    r.carrier,
                    r.line_of_business,
                    r.policy_number ? `#${r.policy_number}` : null,
                  ].filter(Boolean).join(' · ')}
                </div>
              )}
            </div>
          </div>

          {/* Meta row: current premium, premium change (if applicable), exp date */}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {r.current_premium && (
              <span className="reshop-card__premium">
                ${Number(r.current_premium).toLocaleString()}
              </span>
            )}
            {r.renewal_premium && r.current_premium && Number(r.renewal_premium) > Number(r.current_premium) && (
              <span className="reshop-card__premium-hike">
                → ${Number(r.renewal_premium).toLocaleString()}
                <span className="text-[10px] ml-0.5 font-black">
                  +{Math.round(((Number(r.renewal_premium) - Number(r.current_premium)) / Number(r.current_premium)) * 100)}%
                </span>
              </span>
            )}
            {r.expiration_date && (
              <span className="reshop-card__meta-muted flex items-center gap-0.5">
                <Calendar size={10} />
                {new Date(r.expiration_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </span>
            )}
          </div>

          {/* Status badges row — only show when there's something meaningful */}
          {(isExpiringSoon || r.quoted_premium) && (
            <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
              {isExpiringSoon && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  daysUntilExp !== null && daysUntilExp <= 7 ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                }`}>
                  {daysUntilExp}d left
                </span>
              )}
              {r.quoted_premium && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 tabular-nums">
                  Quote: ${Number(r.quoted_premium).toLocaleString()}
                </span>
              )}
            </div>
          )}

          {/* 3-attempt tracker — no label, just 3 circles */}
          <div className="flex items-center gap-1.5 mt-2">
            {[1, 2, 3].map(n => {
              const at = r[`attempt_${n}_at`];
              const answered = r[`attempt_${n}_answered`];
              const prevFilled = n === 1 || r[`attempt_${n-1}_at`];
              const isClickable = canManage && !at && prevFilled;
              const title = at
                ? `Attempt ${n} — ${answered ? 'Customer answered' : 'No answer'} at ${new Date(at).toLocaleString()}`
                : !prevFilled
                  ? `Log attempt ${n - 1} first`
                  : `Log attempt ${n}`;
              return (
                <button
                  key={n}
                  onClick={e => { e.stopPropagation(); if (isClickable) onAttempt(n); }}
                  disabled={!isClickable}
                  title={title}
                  className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold transition-all ${
                    at
                      ? answered
                        ? 'bg-emerald-500 text-white'
                        : 'bg-slate-400 text-white'
                      : isClickable
                        ? 'bg-white border border-slate-300 text-slate-400 hover:border-blue-500 hover:text-blue-600'
                        : 'bg-transparent border border-dashed border-slate-300 text-slate-300 cursor-not-allowed'
                  }`}
                >
                  {at ? (answered ? '✓' : '✗') : n}
                </button>
              );
            })}
          </div>

          {/* Quick actions — only visible on hover */}
          {canManage && (
            <div className="mt-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {nextStage && (
                <button
                  onClick={e => { e.stopPropagation(); onMove(nextStage.key); }}
                  className="flex-1 flex items-center justify-center gap-1 text-[10px] font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded py-1 transition-colors"
                >
                  <ArrowRight size={10} /> {nextStage.label}
                </button>
              )}
              <button
                onClick={e => { e.stopPropagation(); onMove('bound'); }}
                className="flex-1 flex items-center justify-center gap-1 text-[10px] font-semibold text-slate-500 hover:text-emerald-600 hover:bg-emerald-50 rounded py-1 transition-colors"
              >
                <CheckCircle2 size={10} /> Rewrote
              </button>
              <button
                onClick={e => { e.stopPropagation(); onDelete(); }}
                title="Delete reshop"
                aria-label="Delete reshop"
                className="flex items-center justify-center text-slate-400 hover:text-red-600 hover:bg-red-50 rounded py-1 px-1.5 transition-colors"
              >
                <Trash2 size={10} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// ── Detail Drawer ────────────────────────────────────────────────
const DetailDrawer: React.FC<{
  data: any; loading: boolean; onClose: () => void;
  onUpdate: (d: any) => void; onMove: (s: string) => void;
  onDelete: () => void;
  noteText: string; setNoteText: (t: string) => void; onAddNote: () => void;
  teamMembers: any[]; isManager: boolean; saving: boolean;
}> = ({ data, loading, onClose, onUpdate, onMove, onDelete, noteText, setNoteText, onAddNote, teamMembers, isManager, saving }) => {
  const r = data?.reshop;
  const activities = data?.activities || [];

  if (!r && !loading) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-[480px] bg-white shadow-2xl overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={24} className="animate-spin text-slate-400" />
          </div>
        ) : r ? (
          <div>
            {/* Header */}
            <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 z-10">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-slate-900">{r.customer_name}</h2>
                <div className="flex items-center gap-1">
                  {isManager && (
                    <button
                      onClick={onDelete}
                      title="Delete reshop"
                      aria-label="Delete reshop"
                      className="p-1.5 text-slate-400 hover:text-red-600 rounded-lg hover:bg-red-50 transition-colors"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                  <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
                    <X size={18} />
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                  r.stage === 'bound' ? 'bg-green-100 text-green-700' :
                  r.stage === 'lost' ? 'bg-red-100 text-red-700' :
                  'bg-blue-100 text-blue-700'
                }`}>
                  {r.stage?.replace(/_/g, ' ').toUpperCase()}
                </span>
                <span className={`w-2 h-2 rounded-full ${PRIORITY_COLORS[r.priority]}`} />
                <span className="text-xs text-slate-500 capitalize">{r.priority}</span>
              </div>
            </div>

            {/* Stage buttons */}
            {isManager && (
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50">
                <div className="text-xs font-medium text-slate-500 mb-2">Move to stage:</div>
                <div className="flex flex-wrap gap-1.5">
                  {[...STAGES, ...CLOSED_STAGES].map(s => (
                    <button
                      key={s.key}
                      onClick={() => onMove(s.key)}
                      disabled={r.stage === s.key}
                      className={`text-xs px-2 py-1 rounded font-medium transition-colors ${
                        r.stage === s.key
                          ? 'bg-slate-200 text-slate-500 cursor-default'
                          : 'bg-white border border-slate-200 text-slate-700 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700'
                      }`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Customer Info */}
            <div className="px-5 py-4 border-b border-slate-100">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Customer</h3>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <DetailField icon={<Phone size={12} />} label="Phone" value={r.customer_phone} />
                <DetailField icon={<Mail size={12} />} label="Email" value={r.customer_email} />
                <DetailField icon={<FileText size={12} />} label="Policy" value={r.policy_number} />
                <DetailField icon={<Shield size={12} />} label="Carrier" value={r.carrier} />
                <DetailField icon={<DollarSign size={12} />} label="Current Premium" value={r.current_premium ? `$${Number(r.current_premium).toLocaleString()}` : null} />
                <DetailField icon={<Calendar size={12} />} label="Expires" value={r.expiration_date ? new Date(r.expiration_date).toLocaleDateString() : null} />
              </div>
            </div>

            {/* Assignment & Workflow */}
            {isManager && (
              <div className="px-5 py-4 border-b border-slate-100">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Workflow</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-500">Assigned To</label>
                    <select
                      value={r.assigned_to || ''}
                      onChange={e => onUpdate({ assigned_to: e.target.value ? Number(e.target.value) : null })}
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    >
                      <option value="">Unassigned</option>
                      {teamMembers.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-500">Priority</label>
                    <select
                      value={r.priority}
                      onChange={e => onUpdate({ priority: e.target.value })}
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    >
                      <option value="low">Low</option>
                      <option value="normal">Normal</option>
                      <option value="high">High</option>
                      <option value="urgent">Urgent</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-500">Quoter</label>
                    <input
                      value={r.quoter || ''}
                      onChange={e => onUpdate({ quoter: e.target.value })}
                      placeholder="Who's quoting"
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500">Presenter</label>
                    <input
                      value={r.presenter || ''}
                      onChange={e => onUpdate({ presenter: e.target.value })}
                      placeholder="Who presents"
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <label className="text-xs text-slate-500">Reason</label>
                  <select
                    value={r.reason || ''}
                    onChange={e => onUpdate({ reason: e.target.value })}
                    className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                  >
                    <option value="">Select reason...</option>
                    {REASONS.map(reason => <option key={reason.value} value={reason.value}>{reason.label}</option>)}
                  </select>
                </div>
                <div className="mt-2">
                  <label className="text-xs text-slate-500">Source</label>
                  <div className="text-sm text-slate-700 mt-0.5">
                    {SOURCES.find(s => s.value === r.source)?.label || r.source || '—'}
                    {r.referred_by && <span className="text-slate-500"> (via {r.referred_by})</span>}
                  </div>
                </div>
              </div>
            )}

            {/* Quote Details */}
            <div className="px-5 py-4 border-b border-slate-100">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Quote</h3>
              {isManager ? (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-500">Quoted Carrier</label>
                    <input
                      value={r.quoted_carrier || ''}
                      onChange={e => onUpdate({ quoted_carrier: e.target.value })}
                      placeholder="Carrier name"
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500">Quoted Premium</label>
                    <input
                      type="number"
                      value={r.quoted_premium || ''}
                      onChange={e => onUpdate({ quoted_premium: e.target.value ? Number(e.target.value) : null })}
                      placeholder="0.00"
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5"
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="text-xs text-slate-500">Quote Notes</label>
                    <textarea
                      value={r.quote_notes || ''}
                      onChange={e => onUpdate({ quote_notes: e.target.value })}
                      rows={2}
                      placeholder="Coverage details, options presented..."
                      className="w-full mt-0.5 text-sm border border-slate-200 rounded px-2 py-1.5 resize-y"
                    />
                  </div>
                </div>
              ) : (
                <div className="text-sm text-slate-600">
                  {r.quoted_carrier ? `${r.quoted_carrier} — $${Number(r.quoted_premium || 0).toLocaleString()}` : 'No quote yet'}
                </div>
              )}
              {r.premium_savings && Number(r.premium_savings) > 0 && (
                <div className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-emerald-600">
                  <TrendingDown size={14} />Savings: ${Number(r.premium_savings).toLocaleString()}/yr
                </div>
              )}
            </div>

            {/* Notes */}
            <div className="px-5 py-4 border-b border-slate-100">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Notes</h3>
              {isManager && (
                <div className="mb-3">
                  <textarea
                    value={r.notes || ''}
                    onChange={e => onUpdate({ notes: e.target.value })}
                    rows={2}
                    placeholder="General notes about this reshop..."
                    className="w-full text-sm border border-slate-200 rounded px-2 py-1.5 resize-y"
                  />
                </div>
              )}
              {r.notes && !isManager && <p className="text-sm text-slate-600 mb-3">{r.notes}</p>}
            </div>

            {/* Activity Log */}
            <div className="px-5 py-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Activity</h3>
              {/* Add note */}
              <div className="flex gap-2 mb-4">
                <input
                  value={noteText}
                  onChange={e => setNoteText(e.target.value)}
                  placeholder="Add a note..."
                  className="flex-1 text-sm border border-slate-200 rounded px-2 py-1.5"
                  onKeyDown={e => e.key === 'Enter' && onAddNote()}
                />
                <button onClick={onAddNote} className="px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 rounded transition-colors">
                  <MessageSquare size={14} />
                </button>
              </div>

              <div className="space-y-2.5">
                {activities.map((a: any) => (
                  <div key={a.id} className="flex gap-2.5">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                      a.action === 'stage_change' ? 'bg-blue-100 text-blue-600' :
                      a.action === 'note' ? 'bg-slate-100 text-slate-500' :
                      a.action === 'quoted' ? 'bg-emerald-100 text-emerald-600' :
                      a.action === 'assigned' ? 'bg-purple-100 text-purple-600' :
                      'bg-slate-100 text-slate-400'
                    }`}>
                      {a.action === 'stage_change' ? <ArrowRight size={11} /> :
                       a.action === 'note' ? <MessageSquare size={11} /> :
                       a.action === 'quoted' ? <DollarSign size={11} /> :
                       a.action === 'assigned' ? <User size={11} /> :
                       <Clock size={11} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-slate-800">
                        <span className="font-medium">{a.user_name}</span>
                        {' '}{a.detail || a.action.replace(/_/g, ' ')}
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                      </div>
                    </div>
                  </div>
                ))}
                {activities.length === 0 && (
                  <div className="text-xs text-slate-400 text-center py-4">No activity yet</div>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

// ── Detail Field ─────────────────────────────────────────────────
const DetailField: React.FC<{ icon: React.ReactNode; label: string; value: any }> = ({ icon, label, value }) => (
  <div>
    <div className="flex items-center gap-1 text-xs text-slate-400 mb-0.5">{icon}{label}</div>
    <div className="text-sm text-slate-700">{value || '—'}</div>
  </div>
);

// ── Create Modal ─────────────────────────────────────────────────
const CreateModal: React.FC<{
  onClose: () => void; onCreated: () => void; isProducer: boolean; nonRenewalMode?: boolean;
}> = ({ onClose, onCreated, isProducer, nonRenewalMode = false }) => {
  const [form, setForm] = useState({
    customer_name: '', customer_phone: '', customer_email: '',
    policy_number: '', carrier: '', line_of_business: '',
    current_premium: '', source: nonRenewalMode ? 'non_renewal' : isProducer ? 'producer_referral' : 'inbound_call',
    reason: nonRenewalMode ? 'non_renewal' : '', notes: '', priority: nonRenewalMode ? 'normal' : 'normal',
    expiration_date: '',
  });
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.customer_name.trim()) return toast.info('Customer name is required');
    if (nonRenewalMode && !form.expiration_date) return toast.info('Non-renewal date is required');
    setCreating(true);
    try {
      await reshopAPI.create({
        ...form,
        current_premium: form.current_premium ? Number(form.current_premium) : null,
        expiration_date: form.expiration_date || null,
        source_detail: nonRenewalMode ? 'Non-renewal notice from carrier' : undefined,
      });
      onCreated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to create');
    }
    setCreating(false);
  };

  const title = nonRenewalMode ? 'Non-Renewal Pending' : isProducer ? 'Refer Customer for Reshop' : 'New Reshop Request';
  const submitLabel = nonRenewalMode ? 'Add Non-Renewal' : isProducer ? 'Refer for Reshop' : 'Create Reshop';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className={`flex items-center justify-between px-5 py-4 border-b ${nonRenewalMode ? 'border-amber-200 bg-amber-50' : 'border-slate-200'}`}>
          <h2 className={`text-lg font-bold ${nonRenewalMode ? 'text-amber-900' : 'text-slate-900'}`}>
            {title}
          </h2>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        {nonRenewalMode && (
          <div className="mx-5 mt-4 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
            This will add the customer to the reshop pipeline as a non-renewal. The retention team will reshop before the non-renewal date.
          </div>
        )}

        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-medium text-slate-600">Customer Name *</label>
              <input value={form.customer_name} onChange={e => setForm(f => ({ ...f, customer_name: e.target.value }))}
                className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" required />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Phone</label>
              <input value={form.customer_phone} onChange={e => setForm(f => ({ ...f, customer_phone: e.target.value }))}
                className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Email</label>
              <input value={form.customer_email} onChange={e => setForm(f => ({ ...f, customer_email: e.target.value }))}
                className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Policy Number</label>
              <input value={form.policy_number} onChange={e => setForm(f => ({ ...f, policy_number: e.target.value }))}
                className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Carrier</label>
              <input value={form.carrier} onChange={e => setForm(f => ({ ...f, carrier: e.target.value }))}
                className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Line of Business</label>
              <input value={form.line_of_business} onChange={e => setForm(f => ({ ...f, line_of_business: e.target.value }))}
                placeholder="Auto, Home, etc." className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600">Current Premium</label>
              <input type="number" value={form.current_premium} onChange={e => setForm(f => ({ ...f, current_premium: e.target.value }))}
                placeholder="0.00" className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2" />
            </div>
            {nonRenewalMode ? (
              <div className="col-span-2">
                <label className="text-xs font-medium text-amber-700">Non-Renewal Date *</label>
                <input type="date" value={form.expiration_date} onChange={e => setForm(f => ({ ...f, expiration_date: e.target.value }))}
                  className="w-full mt-0.5 text-sm border border-amber-300 rounded-lg px-3 py-2 bg-amber-50" required />
              </div>
            ) : (
              <>
                <div>
                  <label className="text-xs font-medium text-slate-600">Source</label>
                  <select value={form.source} onChange={e => setForm(f => ({ ...f, source: e.target.value }))}
                    className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2">
                    {SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-slate-600">Reason</label>
                  <select value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                    className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2">
                    <option value="">Select...</option>
                    {REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-slate-600">Priority</label>
                  <select value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
                    className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2">
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>
              </>
            )}
          </div>

          <div>
            <label className="text-xs font-medium text-slate-600">Notes</label>
            <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              rows={3} placeholder={nonRenewalMode ? "Reason for non-renewal, any details from the carrier notice..." : "What did the customer say? Any specific concerns?"} className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2 resize-y" />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={creating} className={`px-4 py-2 text-sm font-semibold text-white rounded-lg transition-colors disabled:opacity-50 ${nonRenewalMode ? 'bg-amber-600 hover:bg-amber-700' : 'bg-blue-600 hover:bg-blue-700'}`}>
              {creating ? <Loader2 size={14} className="animate-spin" /> : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
