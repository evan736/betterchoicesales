import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { reshopAPI } from '../lib/api';
import {
  Plus, Search, Loader2, ChevronDown, ChevronRight, X, User, Phone, Mail, FileText,
  DollarSign, Calendar, AlertTriangle, CheckCircle2, XCircle, Clock, RefreshCw,
  ArrowRight, Shield, Target, TrendingUp, TrendingDown, Zap, MessageSquare,
  Send, Eye, Filter, BarChart2, Users,
} from 'lucide-react';

const STAGES = [
  { key: 'proactive', label: 'Proactive', color: 'purple', icon: <Eye size={14} /> },
  { key: 'new_request', label: 'New Request', color: 'blue', icon: <Plus size={14} /> },
  { key: 'quoting', label: 'Quoting', color: 'amber', icon: <FileText size={14} /> },
  { key: 'quote_ready', label: 'Quote Ready', color: 'cyan', icon: <CheckCircle2 size={14} /> },
  { key: 'presenting', label: 'Presenting', color: 'emerald', icon: <Send size={14} /> },
];
const CLOSED_STAGES = [
  { key: 'bound', label: 'Bound', color: 'green' },
  { key: 'renewed', label: 'Renewed — Stayed', color: 'teal' },
  { key: 'lost', label: 'Lost', color: 'red' },
  { key: 'cancelled', label: 'Cancelled', color: 'slate' },
];

const SOURCES = [
  { value: 'inbound_call', label: 'Inbound Call' },
  { value: 'inbound_email', label: 'Inbound Email' },
  { value: 'producer_referral', label: 'Producer Referral' },
  { value: 'proactive_renewal', label: 'Proactive (Renewal)' },
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
  const [teamMembers, setTeamMembers] = useState<any[]>([]);
  const [noteText, setNoteText] = useState('');
  const [saving, setSaving] = useState(false);
  const [filterAssigned, setFilterAssigned] = useState<string>('all');
  const [detectingProactive, setDetectingProactive] = useState(false);
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);

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
        reshopAPI.list({ show_closed: showClosed, search: search || undefined }),
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
      alert(e.response?.data?.detail || 'Failed to move');
    }
  };

  const handleUpdate = async (reshopId: number, data: any) => {
    setSaving(true);
    try {
      await reshopAPI.update(reshopId, data);
      loadData();
      if (selectedReshop?.id === reshopId) openDetail({ id: reshopId });
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to update');
    }
    setSaving(false);
  };

  const handleAddNote = async (reshopId: number) => {
    if (!noteText.trim()) return;
    try {
      await reshopAPI.addNote(reshopId, noteText);
      setNoteText('');
      openDetail({ id: reshopId });
    } catch {}
  };

  const handleDetectProactive = async () => {
    setDetectingProactive(true);
    try {
      const r = await reshopAPI.detectProactive(60, 10);
      alert(`Scan complete: ${r.data.created} new proactive reshops created, ${r.data.skipped} already tracked, ${r.data.policies_checked} policies checked.`);
      loadData();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Detection failed');
    }
    setDetectingProactive(false);
  };

  // Group reshops by stage
  const byStage: Record<string, any[]> = {};
  for (const s of [...STAGES, ...CLOSED_STAGES]) byStage[s.key] = [];
  for (const r of reshops) {
    if (byStage[r.stage]) byStage[r.stage].push(r);
    else byStage['new_request']?.push(r);
  }

  // Filter by assigned
  const filteredByStage = (stage: string) => {
    let items = byStage[stage] || [];
    if (filterAssigned !== 'all') {
      items = items.filter(r => String(r.assigned_to) === filterAssigned || (!r.assigned_to && filterAssigned === 'unassigned'));
    }
    return items;
  };

  if (!user) return null;

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
            <p className="text-sm text-slate-500 mt-0.5">Track customer reshop requests from intake to resolution</p>
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
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              <Plus size={15} />New Reshop
            </button>
          </div>
        </div>

        {/* Stats Bar */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-5">
            <StatPill label="Active" value={stats.total_active} icon={<Target size={14} />} color="blue" />
            <StatPill label="Bound This Month" value={stats.bound_this_month} icon={<CheckCircle2 size={14} />} color="emerald" />
            <StatPill label="Lost This Month" value={stats.lost_this_month} icon={<XCircle size={14} />} color="red" />
            <StatPill label="Win Rate" value={`${stats.win_rate}%`} icon={<TrendingUp size={14} />} color="green" />
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

          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={showClosed}
              onChange={e => setShowClosed(e.target.checked)}
              className="rounded border-slate-300"
            />
            Show Closed
          </label>

          <button onClick={loadData} className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
            <RefreshCw size={16} />
          </button>
        </div>

        {/* Kanban Board */}
        {loading ? (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 size={24} className="animate-spin mr-2" />Loading pipeline...
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 400 }}>
            {STAGES.map(stage => {
              const items = filteredByStage(stage.key);
              const isDragOver = dragOverStage === stage.key;
              return (
                <div
                  key={stage.key}
                  className={`flex-shrink-0 w-[260px] transition-all ${isDragOver ? 'scale-[1.02]' : ''}`}
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
                  <div className={`flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-${stage.color}-50 border border-${stage.color}-200`}>
                    <span className={`text-${stage.color}-600`}>{stage.icon}</span>
                    <span className="text-sm font-semibold text-slate-700">{stage.label}</span>
                    <span className={`ml-auto text-xs font-bold px-1.5 py-0.5 rounded-full bg-${stage.color}-100 text-${stage.color}-700`}>
                      {items.length}
                    </span>
                  </div>
                  <div className={`space-y-2 min-h-[60px] rounded-lg transition-all ${isDragOver ? 'bg-blue-50 border-2 border-dashed border-blue-300 p-2' : ''}`}>
                    {items.map(r => (
                      <ReshopCard
                        key={r.id}
                        reshop={r}
                        onOpen={() => openDetail(r)}
                        onMove={(s: string) => handleStageMove(r.id, s)}
                        stages={STAGES}
                        canManage={isManager}
                      />
                    ))}
                    {items.length === 0 && (
                      <div className="text-xs text-slate-400 text-center py-6 border border-dashed border-slate-200 rounded-lg">
                        No items
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Closed column (collapsed) */}
            {showClosed && CLOSED_STAGES.map(stage => {
              const items = filteredByStage(stage.key);
              if (items.length === 0) return null;
              return (
                <div key={stage.key} className="flex-shrink-0 w-[240px]">
                  <div className={`flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-${stage.color}-50 border border-${stage.color}-200`}>
                    <span className="text-sm font-semibold text-slate-600">{stage.label}</span>
                    <span className="ml-auto text-xs font-bold px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600">{items.length}</span>
                  </div>
                  <div className="space-y-2">
                    {items.map(r => (
                      <ReshopCard key={r.id} reshop={r} onOpen={() => openDetail(r)} onMove={(s: string) => handleStageMove(r.id, s)} stages={STAGES} canManage={isManager} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
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
          noteText={noteText}
          setNoteText={setNoteText}
          onAddNote={() => handleAddNote(selectedReshop.id)}
          teamMembers={teamMembers}
          isManager={isManager}
          saving={saving}
        />
      )}

      {/* Create Modal */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); loadData(); }}
          isProducer={isProducer}
        />
      )}
    </div>
  );
}

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
const ReshopCard: React.FC<{
  reshop: any; onOpen: () => void; onMove: (s: string) => void;
  stages: any[]; canManage: boolean;
}> = ({ reshop, onOpen, onMove, stages, canManage }) => {
  const r = reshop;
  const daysUntilExp = r.expiration_date
    ? Math.ceil((new Date(r.expiration_date).getTime() - Date.now()) / 86400000)
    : null;
  const isUrgent = r.priority === 'urgent' || r.priority === 'high';
  const isExpiringSoon = daysUntilExp !== null && daysUntilExp <= 14 && daysUntilExp >= 0;

  // Next stage
  const currentIdx = stages.findIndex(s => s.key === r.stage);
  const nextStage = currentIdx < stages.length - 1 ? stages[currentIdx + 1] : null;

  return (
    <div
      onClick={onOpen}
      draggable={canManage}
      onDragStart={(e) => {
        if (!canManage) return;
        e.dataTransfer.setData('reshopId', String(r.id));
        e.dataTransfer.effectAllowed = 'move';
        (e.currentTarget as HTMLElement).style.opacity = '0.5';
      }}
      onDragEnd={(e) => {
        (e.currentTarget as HTMLElement).style.opacity = '1';
      }}
      className={`bg-white border rounded-lg px-3 py-2.5 cursor-pointer hover:shadow-md transition-all group ${
        canManage ? 'cursor-grab active:cursor-grabbing' : ''
      } ${
        isUrgent ? 'border-l-[3px] border-l-red-500 border-t border-r border-b border-slate-200' : 'border-slate-200'
      }`}
    >
      <div className="flex items-start justify-between mb-1.5">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-800 truncate">{r.customer_name}</div>
          {r.carrier && (
            <div className="text-xs text-slate-500 truncate">{r.carrier} — {r.line_of_business || 'Policy'}</div>
          )}
        </div>
        <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${PRIORITY_COLORS[r.priority] || 'bg-slate-300'}`} title={r.priority} />
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-500 mb-1.5">
        {r.current_premium && (
          <span className="flex items-center gap-0.5">
            <DollarSign size={10} />{Number(r.current_premium).toLocaleString()}
          </span>
        )}
        {r.policy_number && <span className="truncate max-w-[80px]">#{r.policy_number}</span>}
      </div>

      {(isExpiringSoon || r.quoted_premium) && (
        <div className="flex items-center gap-2 flex-wrap mb-1">
          {isExpiringSoon && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700">
              {daysUntilExp}d left
            </span>
          )}
          {r.quoted_premium && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">
              Quote: ${Number(r.quoted_premium).toLocaleString()}
            </span>
          )}
        </div>
      )}

      {r.assignee_name && (
        <div className={`-mx-3 -mb-2.5 px-3 py-1.5 rounded-b-lg mt-1.5 ${
          r.assignee_name.includes('Salma') ? 'bg-purple-500' :
          r.assignee_name.includes('Michelle') ? 'bg-cyan-500' :
          'bg-amber-500'
        }`}>
          <span className="text-[11px] font-bold text-white tracking-wide">
            {r.assignee_name.split(' ')[0].toUpperCase()}
          </span>
        </div>
      )}

      {/* Quick action buttons */}
      {canManage && (
        <div className="mt-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {nextStage && (
            <button
              onClick={e => { e.stopPropagation(); onMove(nextStage.key); }}
              className="flex-1 flex items-center justify-center gap-1 text-[10px] font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded py-1 transition-colors"
            >
              <ArrowRight size={10} /> {nextStage.label}
            </button>
          )}
          <button
            onClick={e => { e.stopPropagation(); onMove('renewed'); }}
            className="flex-1 flex items-center justify-center gap-1 text-[10px] font-medium text-slate-400 hover:text-green-600 hover:bg-green-50 rounded py-1 transition-colors"
          >
            <CheckCircle2 size={10} /> Skip — Renewed
          </button>
        </div>
      )}
    </div>
  );
};

// ── Detail Drawer ────────────────────────────────────────────────
const DetailDrawer: React.FC<{
  data: any; loading: boolean; onClose: () => void;
  onUpdate: (d: any) => void; onMove: (s: string) => void;
  noteText: string; setNoteText: (t: string) => void; onAddNote: () => void;
  teamMembers: any[]; isManager: boolean; saving: boolean;
}> = ({ data, loading, onClose, onUpdate, onMove, noteText, setNoteText, onAddNote, teamMembers, isManager, saving }) => {
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
                <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
                  <X size={18} />
                </button>
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
  onClose: () => void; onCreated: () => void; isProducer: boolean;
}> = ({ onClose, onCreated, isProducer }) => {
  const [form, setForm] = useState({
    customer_name: '', customer_phone: '', customer_email: '',
    policy_number: '', carrier: '', line_of_business: '',
    current_premium: '', source: isProducer ? 'producer_referral' : 'inbound_call',
    reason: '', notes: '', priority: 'normal',
  });
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.customer_name.trim()) return alert('Customer name is required');
    setCreating(true);
    try {
      await reshopAPI.create({
        ...form,
        current_premium: form.current_premium ? Number(form.current_premium) : null,
      });
      onCreated();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to create');
    }
    setCreating(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-bold text-slate-900">
            {isProducer ? 'Refer Customer for Reshop' : 'New Reshop Request'}
          </h2>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

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
          </div>

          <div>
            <label className="text-xs font-medium text-slate-600">Notes</label>
            <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              rows={3} placeholder="What did the customer say? Any specific concerns?" className="w-full mt-0.5 text-sm border border-slate-200 rounded-lg px-3 py-2 resize-y" />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={creating} className="px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50">
              {creating ? <Loader2 size={14} className="animate-spin" /> : isProducer ? 'Refer for Reshop' : 'Create Reshop'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
