// UW Tracker — kanban-style page for managing carrier underwriting requirements.
//
// Five columns: Pending Assignment | Assigned | Due This Week | Overdue | Completed.
// Click a card → drawer with full email + PDF preview + assign/complete buttons.
// Email forward intake at uw@mail.betterchoiceins.com (Mailgun route → /api/uw/inbound).

import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import api from '../lib/api';
import {
  Plus, Search, Loader2, X, AlertCircle, CheckCircle2, XCircle, Clock,
  RefreshCw, FileText, Calendar, User as UserIcon, Mail, AlertTriangle,
  ChevronRight, Eye, Building2, Paperclip, ExternalLink, RotateCcw,
} from 'lucide-react';
import { toast } from '../components/ui/Toast';

interface UWItem {
  id: number;
  title: string;
  customer_name?: string;
  customer_email?: string;
  policy_number?: string;
  carrier?: string;
  line_of_business?: string;
  description?: string;
  required_action?: string;
  consequence?: string;
  due_date?: string;
  days_until_due?: number | null;
  is_overdue: boolean;
  assigned_to?: number;
  assignee_name?: string;
  assignee_email?: string;
  assigned_at?: string;
  assignment_note?: string;
  status: string;
  completed_at?: string;
  completer_name?: string;
  completion_note?: string;
  intake_email_subject?: string;
  intake_email_from?: string;
  intake_email_carrier_from?: string;
  intake_email_body_text?: string;
  intake_email_body_html?: string;
  intake_received_at?: string;
  ai_confidence?: number;
  account_premium?: number | null;
  attachment_count?: number;
  attachments?: Array<{ index: number; filename: string; content_type: string; size_bytes: number }>;
  activity?: Array<{ action: string; detail?: string; user_name?: string; created_at?: string }>;
  created_at?: string;
}

const COLUMNS = [
  { key: 'pending_assignment', label: 'Pending Assignment', color: '#a855f7', icon: <Clock size={14} /> },
  { key: 'assigned', label: 'Assigned', color: '#0ea5e9', icon: <UserIcon size={14} /> },
  { key: 'due_soon', label: 'Due This Week', color: '#f59e0b', icon: <AlertCircle size={14} /> },
  { key: 'overdue', label: 'Overdue', color: '#dc2626', icon: <AlertTriangle size={14} /> },
  { key: 'completed', label: 'Recently Completed', color: '#10b981', icon: <CheckCircle2 size={14} /> },
];

const SEVERITY_COLORS: Record<string, string> = {
  high: '#dc2626',
  medium: '#f59e0b',
  low: '#0ea5e9',
};

export default function UWTracker() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role && ['admin', 'manager'].includes(user.role.toLowerCase());

  const [items, setItems] = useState<UWItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterAssignee, setFilterAssignee] = useState<string>('all');
  const [team, setTeam] = useState<any[]>([]);

  const [selectedItem, setSelectedItem] = useState<UWItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<UWItem | null>(null);

  const [showCreateModal, setShowCreateModal] = useState(false);

  // Load data
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/uw/items', { params: { include_completed: true, limit: 300 } });
      setItems(r.data.items || []);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to load UW items');
    }
    setLoading(false);
  }, []);

  const loadTeam = async () => {
    try {
      const r = await api.get('/api/reshops/team/members');
      const rows = r.data.members || r.data.users || r.data || [];
      setTeam(Array.isArray(rows) ? rows : []);
    } catch {}
  };

  useEffect(() => {
    if (user) {
      loadData();
      loadTeam();
    }
  }, [user, loadData]);

  // Auto-open if URL has ?item=<id>
  useEffect(() => {
    if (router.isReady && router.query.item && items.length > 0) {
      const id = parseInt(router.query.item as string);
      const found = items.find(i => i.id === id);
      if (found) openDetail(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, router.query.item, items.length]);

  const openDetail = async (item: UWItem) => {
    setSelectedItem(item);
    setDetailLoading(true);
    try {
      const r = await api.get(`/api/uw/items/${item.id}`);
      setDetail(r.data);
    } catch (e: any) {
      toast.error('Failed to load item detail');
    }
    setDetailLoading(false);
  };

  const closeDetail = () => {
    setSelectedItem(null);
    setDetail(null);
    // Strip ?item from URL
    if (router.query.item) {
      const { item, ...rest } = router.query;
      router.replace({ pathname: router.pathname, query: rest }, undefined, { shallow: true });
    }
  };

  // Categorize items into kanban columns
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const oneWeek = new Date(today);
  oneWeek.setDate(today.getDate() + 7);

  const filterMatch = (item: UWItem) => {
    if (search) {
      const s = search.toLowerCase();
      const haystack = [
        item.customer_name, item.policy_number, item.title, item.carrier,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(s)) return false;
    }
    if (filterAssignee !== 'all') {
      if (filterAssignee === 'unassigned' && item.assigned_to) return false;
      if (filterAssignee !== 'unassigned' && String(item.assigned_to) !== filterAssignee) return false;
    }
    return true;
  };

  const colItems = (key: string): UWItem[] => {
    const filtered = items.filter(filterMatch);
    if (key === 'pending_assignment') {
      return filtered.filter(i => i.status === 'pending_assignment');
    }
    if (key === 'completed') {
      // Show last 7 days completed
      const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 7);
      return filtered.filter(i => i.status === 'completed' && i.completed_at && new Date(i.completed_at) >= cutoff);
    }
    if (key === 'overdue') {
      return filtered.filter(i => i.is_overdue && !['completed', 'dismissed'].includes(i.status));
    }
    if (key === 'due_soon') {
      return filtered.filter(i => {
        if (['completed', 'dismissed', 'pending_assignment'].includes(i.status)) return false;
        if (!i.due_date) return false;
        if (i.is_overdue) return false;
        const due = new Date(i.due_date);
        return due >= today && due <= oneWeek;
      });
    }
    if (key === 'assigned') {
      return filtered.filter(i => {
        if (['completed', 'dismissed', 'pending_assignment'].includes(i.status)) return false;
        if (i.is_overdue) return false;
        // exclude due-this-week which has its own column
        if (i.due_date) {
          const due = new Date(i.due_date);
          if (due >= today && due <= oneWeek) return false;
        }
        return true;
      });
    }
    return [];
  };

  const stats = {
    total: items.filter(i => !['completed', 'dismissed'].includes(i.status)).length,
    pending: items.filter(i => i.status === 'pending_assignment').length,
    overdue: items.filter(i => i.is_overdue && !['completed', 'dismissed'].includes(i.status)).length,
    due_this_week: colItems('due_soon').length,
  };

  if (!user) return <div className="p-8 text-slate-500">Loading...</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-[1600px] mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <FileText size={26} className="text-cyan-500" />
              UW Tracker
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Forward UW emails to <span className="font-mono text-cyan-600 select-all">uw@mail.betterchoiceins.com</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={loadData} className="text-slate-500 hover:text-slate-700 p-2 hover:bg-slate-100 rounded">
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={() => setShowCreateModal(true)} className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white text-sm font-semibold rounded-lg shadow-sm">
              <Plus size={15} /> Add UW Item
            </button>
          </div>
        </div>

        {/* Stats bar */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatPill label="Open" value={stats.total} icon={<FileText size={16} />} color="slate" />
          <StatPill label="Pending Assignment" value={stats.pending} icon={<Clock size={16} />} color="purple" />
          <StatPill label="Due This Week" value={stats.due_this_week} icon={<Calendar size={16} />} color="amber" />
          <StatPill label="Overdue" value={stats.overdue} icon={<AlertTriangle size={16} />} color="red" />
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 mb-5 flex-wrap">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search customer, policy, carrier..."
              className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 bg-white"
              style={{ color: '#0f172a' }}
            />
          </div>
          <select
            value={filterAssignee} onChange={e => setFilterAssignee(e.target.value)}
            className="px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white"
            style={{ color: '#0f172a' }}
          >
            <option value="all">All Assignees</option>
            <option value="unassigned">Unassigned</option>
            {team.filter(u => !['beacon.ai', 'admin'].includes((u.username || '').toLowerCase())).map(u => (
              <option key={u.id} value={u.id}>{u.full_name || u.name}</option>
            ))}
          </select>
        </div>

        {/* Kanban */}
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 size={28} className="animate-spin text-slate-400" />
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4" style={{ minHeight: 400 }}>
            {COLUMNS.map(col => {
              const cards = colItems(col.key);
              return (
                <div key={col.key} className="flex-shrink-0 w-[260px]">
                  <div className="rounded-lg p-2.5 mb-2.5 flex items-center justify-between"
                       style={{ background: col.color + '15', border: `1px solid ${col.color}30` }}>
                    <div className="flex items-center gap-1.5 text-xs font-bold" style={{ color: col.color }}>
                      {col.icon}
                      <span className="uppercase tracking-wide">{col.label}</span>
                    </div>
                    <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-white"
                          style={{ color: col.color, border: `1px solid ${col.color}30` }}>
                      {cards.length}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {cards.map(card => <UWCard key={card.id} item={card} onClick={() => openDetail(card)} />)}
                    {cards.length === 0 && (
                      <div className="text-[11px] text-slate-400 text-center py-4 italic">—</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Detail drawer */}
      {selectedItem && (
        <UWDetailDrawer
          item={detail || selectedItem}
          loading={detailLoading}
          team={team}
          isAdmin={!!isAdmin}
          currentUserId={user.id}
          onClose={closeDetail}
          onUpdated={() => { loadData(); openDetail(selectedItem); }}
        />
      )}

      {/* Create modal */}
      {showCreateModal && (
        <UWCreateModal team={team} onClose={() => setShowCreateModal(false)} onCreated={() => { setShowCreateModal(false); loadData(); }} />
      )}
    </div>
  );
}

// ─── Card ──────────────────────────────────────────────────────────
const UWCard: React.FC<{ item: UWItem; onClick: () => void }> = ({ item, onClick }) => {
  const dueLabel = item.due_date
    ? new Date(item.due_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : 'no deadline';

  let badgeColor = '#64748b';
  let badgeText = '';
  if (item.due_date) {
    const days = item.days_until_due ?? 999;
    if (days < 0) { badgeColor = '#dc2626'; badgeText = `${-days}d over`; }
    else if (days === 0) { badgeColor = '#dc2626'; badgeText = 'today'; }
    else if (days <= 3) { badgeColor = '#f59e0b'; badgeText = `${days}d`; }
    else if (days <= 7) { badgeColor = '#0ea5e9'; badgeText = `${days}d`; }
    else { badgeColor = '#64748b'; badgeText = `${days}d`; }
  }

  return (
    <div onClick={onClick}
         className="bg-white rounded-lg border border-slate-200 p-2.5 cursor-pointer hover:border-cyan-300 hover:shadow-md transition-all"
         style={{
           borderLeft: item.is_overdue ? '3px solid #dc2626' : item.status === 'pending_assignment' ? '3px solid #a855f7' : undefined,
         }}>
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="text-sm font-bold text-slate-900 leading-tight flex-1 truncate">
          {item.customer_name || '(unmatched)'}
        </div>
        {item.due_date && (
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white whitespace-nowrap" style={{ background: badgeColor }}>
            {badgeText}
          </span>
        )}
      </div>
      <div className="text-xs text-slate-500 mb-1.5 truncate flex items-center gap-1.5 flex-wrap">
        <span>{item.carrier || '?'} {item.policy_number && `· #${item.policy_number}`}</span>
        {item.account_premium != null && item.account_premium > 0 && (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 whitespace-nowrap"
                title="Total active premium for this account">
            ${Math.round(item.account_premium).toLocaleString()}
          </span>
        )}
      </div>
      <div className="text-xs text-slate-600 mb-2 line-clamp-2 leading-snug">
        {item.title || item.required_action || '(no description)'}
      </div>
      <div className="flex items-center justify-between text-[11px]">
        <div className="text-slate-500">{dueLabel}</div>
        {item.assignee_name ? (
          <div className="flex items-center gap-1 text-cyan-600">
            <UserIcon size={10} />{item.assignee_name.split(' ')[0]}
          </div>
        ) : (
          <span className="text-purple-600 font-semibold">unassigned</span>
        )}
      </div>
      {(item.attachment_count ?? 0) > 0 && (
        <div className="mt-1.5 text-[10px] text-slate-400 flex items-center gap-1">
          <Paperclip size={10} />{item.attachment_count} attachment{item.attachment_count! > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
};

// ─── Detail Drawer ─────────────────────────────────────────────────
const UWDetailDrawer: React.FC<{
  item: UWItem;
  loading: boolean;
  team: any[];
  isAdmin: boolean;
  currentUserId?: number;
  onClose: () => void;
  onUpdated: () => void;
}> = ({ item, loading, team, isAdmin, currentUserId, onClose, onUpdated }) => {
  const [selectedAssignee, setSelectedAssignee] = useState<string>('');
  const [assignNote, setAssignNote] = useState('');
  const [completing, setCompleting] = useState(false);
  const [completionNote, setCompletionNote] = useState('');
  const [showAttachment, setShowAttachment] = useState<number | null>(null);
  const [editingDueDate, setEditingDueDate] = useState(false);
  const [newDueDate, setNewDueDate] = useState(item.due_date || '');

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;

  const handleAssign = async () => {
    if (!selectedAssignee) {
      toast.error('Pick someone to assign to');
      return;
    }
    try {
      await api.post(`/api/uw/items/${item.id}/assign`, {
        assignee_id: parseInt(selectedAssignee),
        note: assignNote || undefined,
      });
      toast.success('Assigned — notification email sent');
      setSelectedAssignee('');
      setAssignNote('');
      onUpdated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Assignment failed');
    }
  };

  const handleComplete = async () => {
    setCompleting(true);
    try {
      await api.post(`/api/uw/items/${item.id}/complete`, { note: completionNote || undefined });
      toast.success('Marked complete');
      setCompletionNote('');
      onUpdated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to complete');
    }
    setCompleting(false);
  };

  const handleReopen = async () => {
    try {
      await api.post(`/api/uw/items/${item.id}/reopen`);
      toast.success('Reopened');
      onUpdated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to reopen');
    }
  };

  const handleDismiss = async () => {
    if (!confirm('Dismiss this item? (e.g. spam, duplicate, wrong-channel) — can be reopened later.')) return;
    try {
      await api.post(`/api/uw/items/${item.id}/dismiss`, { note: 'Dismissed by admin' });
      toast.success('Dismissed');
      onUpdated();
      onClose();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to dismiss');
    }
  };

  const handleSaveDueDate = async () => {
    try {
      await api.patch(`/api/uw/items/${item.id}`, { due_date: newDueDate || null });
      toast.success('Due date updated');
      setEditingDueDate(false);
      onUpdated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to update');
    }
  };

  const dueLabel = item.due_date ? new Date(item.due_date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }) : 'no deadline';

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative ml-auto w-full max-w-2xl bg-white shadow-2xl flex flex-col h-full overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-slate-200 bg-slate-50">
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide">UW ITEM #{item.id}</div>
            <h2 className="text-lg font-bold text-slate-900 mt-0.5">{item.customer_name || '(unmatched customer)'}</h2>
            <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-2 flex-wrap">
              <span>
                {item.carrier || '?'} {item.policy_number && `· #${item.policy_number}`}
                {item.line_of_business && ` · ${item.line_of_business}`}
              </span>
              {item.account_premium != null && item.account_premium > 0 && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-700"
                      title="Total active premium across all of this customer's policies">
                  Account: ${Math.round(item.account_premium).toLocaleString()}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1">
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {loading && <div className="text-center text-slate-400 py-8"><Loader2 size={20} className="inline animate-spin" /></div>}

          {/* Status pill + Due date */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-bold px-2.5 py-1 rounded uppercase tracking-wide ${
              item.status === 'pending_assignment' ? 'bg-purple-100 text-purple-700' :
              item.status === 'completed' ? 'bg-emerald-100 text-emerald-700' :
              item.is_overdue ? 'bg-red-100 text-red-700' :
              'bg-cyan-100 text-cyan-700'
            }`}>
              {item.is_overdue && item.status !== 'completed' ? 'overdue' : item.status.replace('_', ' ')}
            </span>
            {item.due_date && (
              <span className="text-xs text-slate-600 flex items-center gap-1">
                <Calendar size={12} /> Due {dueLabel}
                {item.days_until_due !== null && item.days_until_due !== undefined && (
                  <span className={`ml-1 font-semibold ${item.is_overdue ? 'text-red-600' : item.days_until_due <= 3 ? 'text-amber-600' : 'text-slate-500'}`}>
                    ({item.days_until_due < 0 ? `${-item.days_until_due}d over` : `${item.days_until_due}d`})
                  </span>
                )}
              </span>
            )}
            {!editingDueDate ? (
              <button onClick={() => setEditingDueDate(true)} className="text-[10px] text-cyan-600 hover:underline">edit due date</button>
            ) : (
              <span className="flex items-center gap-1">
                <input type="date" value={newDueDate || ''} onChange={e => setNewDueDate(e.target.value)}
                       className="text-xs px-2 py-0.5 border border-slate-300 rounded" style={{ color: '#0f172a' }} />
                <button onClick={handleSaveDueDate} className="text-[10px] bg-cyan-500 text-white px-2 py-0.5 rounded">save</button>
                <button onClick={() => setEditingDueDate(false)} className="text-[10px] text-slate-500 px-1">cancel</button>
              </span>
            )}
          </div>

          {/* Required Action */}
          <div className="rounded-lg bg-amber-50 border border-amber-200 p-3">
            <div className="text-[10px] font-bold text-amber-700 uppercase tracking-wide mb-1">Required Action</div>
            <div className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{item.required_action || '(none extracted)'}</div>
            {item.consequence && (
              <div className="mt-2 pt-2 border-t border-amber-200">
                <div className="text-[10px] font-bold text-red-700 uppercase tracking-wide mb-1">If Not Completed</div>
                <div className="text-xs text-slate-700">{item.consequence}</div>
              </div>
            )}
          </div>

          {/* Assignment section */}
          {item.status === 'pending_assignment' && isAdmin && (
            <div className="rounded-lg border border-purple-200 bg-purple-50 p-4">
              <div className="text-xs font-bold text-purple-700 uppercase tracking-wide mb-2">Assign to:</div>
              <select value={selectedAssignee} onChange={e => setSelectedAssignee(e.target.value)}
                      className="w-full px-3 py-2 text-sm border border-purple-200 rounded-lg bg-white mb-2"
                      style={{ color: '#0f172a' }}>
                <option value="">— Pick a team member —</option>
                {team.filter(u => !['beacon.ai', 'admin'].includes((u.username || '').toLowerCase())).map(u => (
                  <option key={u.id} value={u.id}>{u.full_name || u.name}</option>
                ))}
              </select>
              <input value={assignNote} onChange={e => setAssignNote(e.target.value)}
                     placeholder="Optional note (e.g., 'Customer is calling — handle today')"
                     className="w-full px-3 py-2 text-sm border border-purple-200 rounded-lg bg-white mb-2"
                     style={{ color: '#0f172a' }} />
              <button onClick={handleAssign} disabled={!selectedAssignee}
                      className={`w-full py-2 rounded-lg text-sm font-semibold ${selectedAssignee ? 'bg-purple-600 hover:bg-purple-700 text-white' : 'bg-slate-200 text-slate-400 cursor-not-allowed'}`}>
                Assign &amp; Send Email
              </button>
            </div>
          )}

          {item.assignee_name && item.status !== 'completed' && (
            <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 flex items-center justify-between">
              <div className="text-xs">
                <span className="text-slate-500">Assigned to:</span>{' '}
                <span className="font-semibold text-slate-900">{item.assignee_name}</span>
              </div>
              {isAdmin && (
                <button onClick={() => { /* Show reassign UI inline */
                  const newId = prompt('New assignee user ID? (admin override)');
                  if (newId) {
                    api.post(`/api/uw/items/${item.id}/assign`, { assignee_id: parseInt(newId) })
                      .then(() => { toast.success('Reassigned'); onUpdated(); })
                      .catch((e: any) => toast.error(e.response?.data?.detail || 'Failed'));
                  }
                }} className="text-[10px] text-cyan-600 hover:underline">reassign</button>
              )}
            </div>
          )}

          {/* Complete button */}
          {item.status !== 'completed' && item.status !== 'dismissed' && (item.assigned_to === currentUserId || isAdmin) && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <div className="text-xs font-bold text-emerald-700 uppercase tracking-wide mb-2">Mark Complete</div>
              <textarea value={completionNote} onChange={e => setCompletionNote(e.target.value)}
                        placeholder="Optional: what was done? (e.g., 'Photos sent to underwriter on 4/30')"
                        rows={2}
                        className="w-full px-3 py-2 text-sm border border-emerald-200 rounded-lg bg-white mb-2 resize-none"
                        style={{ color: '#0f172a' }} />
              <button onClick={handleComplete} disabled={completing}
                      className="w-full py-2 rounded-lg text-sm font-semibold bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50">
                {completing ? 'Saving...' : '✓ Mark Complete'}
              </button>
            </div>
          )}

          {item.status === 'completed' && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
                <CheckCircle2 size={16} /> Completed by {item.completer_name}
              </div>
              {item.completion_note && (
                <div className="text-xs text-slate-700 mt-1.5 italic">"{item.completion_note}"</div>
              )}
              {isAdmin && (
                <button onClick={handleReopen} className="mt-2 text-xs text-emerald-700 hover:underline flex items-center gap-1">
                  <RotateCcw size={11} /> reopen
                </button>
              )}
            </div>
          )}

          {/* Attachments */}
          {item.attachments && item.attachments.length > 0 && (
            <div>
              <div className="text-xs font-bold text-slate-700 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <Paperclip size={12} /> Attachments ({item.attachments.length})
              </div>
              <div className="space-y-2">
                {item.attachments.map(att => (
                  <div key={att.index} className="border border-slate-200 rounded-lg overflow-hidden">
                    <div className="flex items-center justify-between p-2.5 bg-slate-50">
                      <div className="text-xs flex items-center gap-2 truncate">
                        <FileText size={14} className="text-cyan-500 flex-shrink-0" />
                        <span className="font-medium text-slate-700 truncate">{att.filename}</span>
                        <span className="text-[10px] text-slate-400 flex-shrink-0">
                          {att.size_bytes ? `${Math.round(att.size_bytes / 1024)} KB` : ''}
                        </span>
                      </div>
                      <button onClick={() => setShowAttachment(showAttachment === att.index ? null : att.index)}
                              className="text-[11px] text-cyan-600 hover:underline flex items-center gap-1 flex-shrink-0 ml-2">
                        {showAttachment === att.index ? 'hide' : <><Eye size={10} /> preview</>}
                      </button>
                    </div>
                    {showAttachment === att.index && (
                      <div className="bg-slate-100 p-2">
                        <iframe
                          src={`${apiBase}/api/uw/items/${item.id}/attachment/${att.index}?token=${token}`}
                          className="w-full h-[500px] border-0 rounded"
                          title={att.filename}
                        />
                        <a href={`${apiBase}/api/uw/items/${item.id}/attachment/${att.index}?token=${token}`}
                           target="_blank" rel="noopener noreferrer"
                           className="text-[11px] text-cyan-600 hover:underline mt-1 inline-flex items-center gap-1">
                          <ExternalLink size={10} /> open in new tab
                        </a>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Original email */}
          {(item.intake_email_subject || item.intake_email_body_text) && (
            <div>
              <div className="text-xs font-bold text-slate-700 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <Mail size={12} /> Original Email
              </div>
              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <div className="bg-slate-50 px-3 py-2 text-[11px] text-slate-600 border-b border-slate-200">
                  <div><strong>From:</strong> {item.intake_email_carrier_from || item.intake_email_from || '?'}</div>
                  <div><strong>Forwarded by:</strong> {item.intake_email_from || '?'}</div>
                  <div><strong>Subject:</strong> {item.intake_email_subject || '(no subject)'}</div>
                </div>
                <div className="p-3 max-h-[300px] overflow-y-auto text-xs text-slate-700 whitespace-pre-wrap leading-relaxed">
                  {item.intake_email_body_text || '(no plain text body)'}
                </div>
              </div>
            </div>
          )}

          {/* Activity log */}
          {item.activity && item.activity.length > 0 && (
            <div>
              <div className="text-xs font-bold text-slate-700 uppercase tracking-wide mb-2">Activity</div>
              <div className="space-y-1.5">
                {item.activity.map((a, i) => (
                  <div key={i} className="text-[11px] text-slate-600 flex items-baseline gap-2">
                    <span className="text-slate-400 font-mono flex-shrink-0">
                      {a.created_at ? new Date(a.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : ''}
                    </span>
                    <span><strong className="text-slate-700">{a.user_name}</strong> {a.action}{a.detail && ` — ${a.detail}`}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Admin actions */}
          {isAdmin && item.status !== 'completed' && item.status !== 'dismissed' && (
            <div className="pt-3 border-t border-slate-200">
              <button onClick={handleDismiss} className="text-xs text-red-600 hover:underline">
                Dismiss this item (spam / wrong-channel)
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Manual Create Modal ──────────────────────────────────────────
const UWCreateModal: React.FC<{ team: any[]; onClose: () => void; onCreated: () => void }> = ({ team, onClose, onCreated }) => {
  const [form, setForm] = useState({
    title: '', customer_name: '', policy_number: '', carrier: '',
    line_of_business: '', required_action: '', due_date: '', assignee_id: '',
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.title.trim()) { toast.error('Title required'); return; }
    setSaving(true);
    try {
      const payload: any = { ...form };
      if (form.assignee_id) payload.assignee_id = parseInt(form.assignee_id);
      else delete payload.assignee_id;
      Object.keys(payload).forEach(k => { if (payload[k] === '') delete payload[k]; });
      await api.post('/api/uw/items', payload);
      toast.success('UW item created');
      onCreated();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to create');
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-bold text-slate-900">Add UW Item Manually</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X size={20} /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <Field label="Title *">
            <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}
                   placeholder="e.g., Tree trimming required"
                   className="input-field" style={{ color: '#0f172a' }} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Customer">
              <input value={form.customer_name} onChange={e => setForm({ ...form, customer_name: e.target.value })}
                     placeholder="John Smith" className="input-field" style={{ color: '#0f172a' }} />
            </Field>
            <Field label="Policy #">
              <input value={form.policy_number} onChange={e => setForm({ ...form, policy_number: e.target.value })}
                     placeholder="" className="input-field" style={{ color: '#0f172a' }} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Carrier">
              <input value={form.carrier} onChange={e => setForm({ ...form, carrier: e.target.value })}
                     placeholder="Grange / NatGen / etc." className="input-field" style={{ color: '#0f172a' }} />
            </Field>
            <Field label="LOB">
              <select value={form.line_of_business} onChange={e => setForm({ ...form, line_of_business: e.target.value })}
                      className="input-field" style={{ color: '#0f172a' }}>
                <option value="">—</option>
                <option value="home">Home</option>
                <option value="auto">Auto</option>
                <option value="commercial">Commercial</option>
                <option value="umbrella">Umbrella</option>
                <option value="other">Other</option>
              </select>
            </Field>
          </div>
          <Field label="Required Action">
            <textarea value={form.required_action} onChange={e => setForm({ ...form, required_action: e.target.value })}
                      rows={3} placeholder="What needs to be done"
                      className="input-field resize-none" style={{ color: '#0f172a' }} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Due Date">
              <input type="date" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })}
                     className="input-field" style={{ color: '#0f172a' }} />
            </Field>
            <Field label="Assign To">
              <select value={form.assignee_id} onChange={e => setForm({ ...form, assignee_id: e.target.value })}
                      className="input-field" style={{ color: '#0f172a' }}>
                <option value="">— pending assignment —</option>
                {team.filter(u => !['beacon.ai', 'admin'].includes((u.username || '').toLowerCase())).map(u => (
                  <option key={u.id} value={u.id}>{u.full_name || u.name}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="flex gap-2 pt-3 border-t border-slate-100">
            <button onClick={submit} disabled={saving} className="flex-1 py-2.5 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-semibold disabled:opacity-50">
              {saving ? 'Saving...' : 'Create'}
            </button>
            <button onClick={onClose} className="px-5 py-2.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-semibold">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Stat Pill ─────────────────────────────────────────────────────
const StatPill: React.FC<{ label: string; value: number; icon: React.ReactNode; color: string }> = ({ label, value, icon, color }) => (
  <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-white border border-slate-200">
    <span className={`text-${color}-500`}>{icon}</span>
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-bold text-slate-800">{value}</div>
    </div>
  </div>
);

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div>
    <label className="block text-xs font-semibold text-slate-700 mb-1">{label}</label>
    {children}
  </div>
);
