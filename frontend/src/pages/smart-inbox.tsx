import React, { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import {
  Inbox, Send, AlertTriangle, CheckCircle, XCircle, RefreshCw,
  Search, Eye, Clock, Shield, Zap, Mail, User, FileText,
  ChevronDown, ChevronRight, ArrowRight, RotateCw, Edit3, Check, X,
  Activity, AlertCircle, Archive, MailOpen, CheckSquare, Square,
  Minimize2, Maximize2, Filter, Trash2, EyeOff, Bell
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

// ── Types ────────────────────────────────────────────────────────────────────

interface InboundEmail {
  id: number;
  created_at: string;
  from_address: string;
  subject: string;
  category: string;
  sensitivity: string;
  ai_summary: string;
  confidence_score: number;
  extracted_policy_number: string | null;
  extracted_insured_name: string | null;
  extracted_carrier: string | null;
  customer_name: string | null;
  customer_email: string | null;
  match_method: string | null;
  match_confidence: number | null;
  status: string;
  nowcerts_note_logged: boolean;
  error_message: string | null;
  attachment_count: number;
  has_outbound: boolean;
  body_plain?: string;
  body_html?: string;
  ai_analysis?: any;
  outbound_messages?: OutboundMessage[];
  is_read?: boolean;
  is_archived?: boolean;
}

interface OutboundMessage {
  id: number;
  created_at: string;
  to_email: string;
  to_name: string | null;
  subject: string;
  body_html: string;
  body_plain: string;
  ai_rationale: string | null;
  status: string;
  sensitivity: string;
  sent_at: string | null;
  approved_by: string | null;
  rejected_reason: string | null;
  send_error: string | null;
}

interface InboxStats {
  received_24h: number;
  received_7d: number;
  pending_approval: number;
  auto_sent_24h: number;
  failed: number;
  matched_7d: number;
  unmatched_7d: number;
  category_breakdown: Record<string, number>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const categoryColors: Record<string, string> = {
  non_payment: '#f87171', cancellation: '#ef4444', non_renewal: '#f97316',
  underwriting_requirement: '#fbbf24', renewal_notice: '#a78bfa', policy_change: '#60a5fa',
  claim_notice: '#f43f5e', billing_inquiry: '#38bdf8', customer_request: '#22d3ee',
  general_inquiry: '#94a3b8', endorsement: '#818cf8', new_business_confirmation: '#34d399',
  audit_notice: '#e879f9', other: '#64748b',
};

const sensitivityConfig: Record<string, { color: string; icon: any; label: string }> = {
  routine: { color: '#34d399', icon: Zap, label: 'Routine' },
  moderate: { color: '#fbbf24', icon: Shield, label: 'Moderate' },
  sensitive: { color: '#f97316', icon: AlertTriangle, label: 'Sensitive' },
  critical: { color: '#ef4444', icon: AlertCircle, label: 'Critical' },
};

const statusConfig: Record<string, { color: string; label: string }> = {
  received: { color: '#94a3b8', label: 'Received' },
  parsing: { color: '#60a5fa', label: 'Parsing...' },
  parsed: { color: '#38bdf8', label: 'Parsed' },
  customer_matched: { color: '#22d3ee', label: 'Matched' },
  customer_not_found: { color: '#f97316', label: 'No Match' },
  logged: { color: '#a78bfa', label: 'Logged' },
  outbound_queued: { color: '#fbbf24', label: 'Queued' },
  outbound_sent: { color: '#34d399', label: 'Sent' },
  outbound_approved: { color: '#34d399', label: 'Approved' },
  outbound_rejected: { color: '#f87171', label: 'Rejected' },
  completed: { color: '#22d3ee', label: 'Complete' },
  failed: { color: '#ef4444', label: 'Failed' },
  skipped: { color: '#64748b', label: 'Skipped' },
};

function timeAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 172800) return 'yesterday';
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatCategory(cat: string): string {
  return (cat || 'other').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function getDateGroup(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday.getTime() - 86400000);
  const startOfWeek = new Date(startOfToday.getTime() - startOfToday.getDay() * 86400000);

  if (d >= startOfToday) return 'Today';
  if (d >= startOfYesterday) return 'Yesterday';
  if (d >= startOfWeek) return 'This Week';
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric' });
}

// Check if email needs attention (queued, failed, or pending approval)
function needsAttention(email: InboundEmail): boolean {
  return email.status === 'failed' ||
    email.status === 'outbound_queued' ||
    email.has_outbound && email.status !== 'outbound_sent' && email.status !== 'completed' && email.status !== 'outbound_rejected';
}

// ── Local state helpers for read/archive (client-side until backend supports it) ──

const READ_KEY = 'orbit_smart_inbox_read';
const ARCHIVE_KEY = 'orbit_smart_inbox_archived';

function getStoredSet(key: string): Set<number> {
  try {
    const raw = typeof window !== 'undefined' ? localStorage.getItem(key) : null;
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}

function storeSet(key: string, set: Set<number>) {
  try {
    localStorage.setItem(key, JSON.stringify([...set]));
  } catch {}
}

// ── Main Component ───────────────────────────────────────────────────────────

export default function SmartInboxPage() {
  const [tab, setTab] = useState<'inbox' | 'queue' | 'stats'>('inbox');
  const [emails, setEmails] = useState<InboundEmail[]>([]);
  const [queue, setQueue] = useState<OutboundMessage[]>([]);
  const [stats, setStats] = useState<InboxStats | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<InboundEmail | null>(null);
  const [search, setSearch] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterSensitivity, setFilterSensitivity] = useState('');
  const [loading, setLoading] = useState(false);
  const [editingOutbound, setEditingOutbound] = useState<number | null>(null);
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');

  // New features state
  const [readIds, setReadIds] = useState<Set<number>>(new Set());
  const [archivedIds, setArchivedIds] = useState<Set<number>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [compact, setCompact] = useState(false);
  const [viewFilter, setViewFilter] = useState<'all' | 'unread' | 'attention' | 'archived'>('all');
  const [showArchived, setShowArchived] = useState(false);
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const batchRef = useRef<HTMLDivElement>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers = { Authorization: `Bearer ${token}` };

  // Load read/archive state from localStorage
  useEffect(() => {
    setReadIds(getStoredSet(READ_KEY));
    setArchivedIds(getStoredSet(ARCHIVE_KEY));
  }, []);

  const markRead = (ids: number[]) => {
    setReadIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.add(id));
      storeSet(READ_KEY, next);
      return next;
    });
  };

  const markUnread = (ids: number[]) => {
    setReadIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.delete(id));
      storeSet(READ_KEY, next);
      return next;
    });
  };

  const archiveEmails = (ids: number[]) => {
    setArchivedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.add(id));
      storeSet(ARCHIVE_KEY, next);
      return next;
    });
    // Also mark as read
    markRead(ids);
    // Deselect archived items
    setSelectedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.delete(id));
      return next;
    });
    if (selectedEmail && ids.includes(selectedEmail.id)) setSelectedEmail(null);
  };

  const unarchiveEmails = (ids: number[]) => {
    setArchivedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.delete(id));
      storeSet(ARCHIVE_KEY, next);
      return next;
    });
  };

  // Selection helpers
  const toggleSelect = (id: number, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    const visible = getFilteredEmails();
    if (selectedIds.size === visible.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(visible.map(e => e.id)));
    }
  };

  // Close batch menu on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (batchRef.current && !batchRef.current.contains(e.target as Node)) {
        setBatchMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── API calls ──

  const fetchEmails = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { limit: 100 };
      if (search) params.search = search;
      if (filterCategory) params.category = filterCategory;
      if (filterSensitivity) params.sensitivity = filterSensitivity;
      const res = await axios.get(`${API}/api/smart-inbox/emails`, { params, headers });
      setEmails(res.data.emails || []);
    } catch (err) { console.error('Failed to fetch emails', err); }
    setLoading(false);
  }, [search, filterCategory, filterSensitivity]);

  const fetchQueue = async () => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/queue`, { params: { status: 'pending_approval' }, headers });
      setQueue(res.data.queue || []);
    } catch (err) { console.error('Failed to fetch queue', err); }
  };

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/stats`, { headers });
      setStats(res.data);
    } catch (err) { console.error('Failed to fetch stats', err); }
  };

  const fetchEmailDetail = async (id: number) => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/emails/${id}`, { headers });
      setSelectedEmail(res.data);
      markRead([id]);
    } catch (err) { console.error('Failed to fetch email detail', err); }
  };

  useEffect(() => {
    fetchEmails(); fetchQueue(); fetchStats();
  }, []);

  useEffect(() => { fetchEmails(); }, [search, filterCategory, filterSensitivity]);

  const approveOutbound = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/approve`, {}, { headers });
      fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) { alert(err.response?.data?.detail || 'Approve failed'); }
  };

  const rejectOutbound = async (id: number) => {
    const reason = prompt('Rejection reason (optional):');
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/reject`, null, { headers, params: { reason } });
      fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) { alert(err.response?.data?.detail || 'Reject failed'); }
  };

  const editAndSend = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/edit`, {
        subject: editSubject,
        body_html: `<div style="font-family: -apple-system, sans-serif;">${editBody.replace(/\n/g, '<br>')}</div>`,
        body_plain: editBody, send: true,
      }, { headers });
      setEditingOutbound(null); fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) { alert(err.response?.data?.detail || 'Edit & send failed'); }
  };

  const reprocess = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/reprocess/${id}`, {}, { headers });
      fetchEmails();
    } catch (err) { console.error('Reprocess failed', err); }
  };

  // ── Filtered emails ──

  const getFilteredEmails = useCallback(() => {
    return emails.filter(e => {
      const isArchived = archivedIds.has(e.id);
      if (viewFilter === 'archived') return isArchived;
      if (isArchived) return false;
      if (viewFilter === 'unread') return !readIds.has(e.id);
      if (viewFilter === 'attention') return needsAttention(e);
      return true;
    });
  }, [emails, archivedIds, readIds, viewFilter]);

  // Group emails by date
  const getGroupedEmails = useCallback(() => {
    const filtered = getFilteredEmails();
    const groups: { label: string; emails: InboundEmail[] }[] = [];
    const groupMap = new Map<string, InboundEmail[]>();
    const order: string[] = [];

    for (const e of filtered) {
      const group = getDateGroup(e.created_at);
      if (!groupMap.has(group)) { groupMap.set(group, []); order.push(group); }
      groupMap.get(group)!.push(e);
    }
    for (const label of order) groups.push({ label, emails: groupMap.get(label)! });
    return groups;
  }, [getFilteredEmails]);

  const filteredEmails = getFilteredEmails();
  const groupedEmails = getGroupedEmails();
  const unreadCount = emails.filter(e => !readIds.has(e.id) && !archivedIds.has(e.id)).length;
  const attentionCount = emails.filter(e => needsAttention(e) && !archivedIds.has(e.id)).length;
  const archivedCount = emails.filter(e => archivedIds.has(e.id)).length;

  // ── Batch action handlers ──

  const batchMarkRead = () => { markRead([...selectedIds]); setSelectedIds(new Set()); setBatchMenuOpen(false); };
  const batchMarkUnread = () => { markUnread([...selectedIds]); setSelectedIds(new Set()); setBatchMenuOpen(false); };
  const batchArchive = () => { archiveEmails([...selectedIds]); setBatchMenuOpen(false); };
  const batchUnarchive = () => { unarchiveEmails([...selectedIds]); setSelectedIds(new Set()); setBatchMenuOpen(false); };

  // ── Render ──

  const s = {
    glass: {
      background: 'rgba(15, 23, 42, 0.4)',
      border: '1px solid rgba(34, 211, 238, 0.1)',
      borderRadius: 10,
      backdropFilter: 'blur(8px)',
    },
    glassHover: {
      background: 'rgba(34, 211, 238, 0.08)',
      border: '1px solid rgba(34, 211, 238, 0.25)',
    },
    btn: (active: boolean) => ({
      padding: '6px 12px', border: 'none', borderRadius: 6, cursor: 'pointer',
      fontSize: 12, fontWeight: 600 as const, transition: 'all 0.15s',
      background: active ? 'rgba(34, 211, 238, 0.15)' : 'rgba(15, 23, 42, 0.4)',
      color: active ? '#22d3ee' : '#64748b',
      borderWidth: 1, borderStyle: 'solid' as const,
      borderColor: active ? 'rgba(34, 211, 238, 0.3)' : 'rgba(100, 116, 139, 0.2)',
    }),
  };

  return (
    <>
      <Head><title>Smart Inbox — ORBIT</title></Head>
      <div style={{
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #0a0e1a 0%, #0f172a 50%, #0c1220 100%)',
        color: '#e2e8f0',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      }}>
        {/* ═══ HEADER ═══ */}
        <div style={{
          padding: '16px 24px',
          borderBottom: '1px solid rgba(34, 211, 238, 0.12)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(12px)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 38, height: 38, borderRadius: 8,
              background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 16px rgba(34, 211, 238, 0.25)',
            }}>
              <Inbox size={20} color="#0f172a" />
            </div>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: '#f1f5f9' }}>Smart Inbox</h1>
              <p style={{ fontSize: 11, color: '#64748b', margin: 0 }}>
                AI-Powered Email Processing • <span
                  style={{ color: '#22d3ee', cursor: 'pointer' }}
                  onClick={() => navigator.clipboard.writeText('process@mail.betterchoiceins.com')}
                  title="Click to copy"
                >process@mail.betterchoiceins.com</span>
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {queue.length > 0 && (
              <button onClick={() => setTab('queue')} style={{
                background: 'rgba(251, 191, 36, 0.12)', border: '1px solid rgba(251, 191, 36, 0.25)',
                borderRadius: 8, padding: '6px 14px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6, animation: 'pulse 2s infinite',
              }}>
                <AlertTriangle size={14} color="#fbbf24" />
                <span style={{ color: '#fbbf24', fontWeight: 600, fontSize: 13 }}>{queue.length} awaiting approval</span>
              </button>
            )}
            <button onClick={() => { fetchEmails(); fetchQueue(); fetchStats(); }} style={{
              background: 'rgba(34, 211, 238, 0.08)', border: '1px solid rgba(34, 211, 238, 0.2)',
              borderRadius: 8, padding: '6px 14px', color: '#22d3ee', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 500,
            }}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>

        {/* ═══ TABS ═══ */}
        <div style={{
          display: 'flex', gap: 0, padding: '0 24px',
          borderBottom: '1px solid rgba(34, 211, 238, 0.08)',
          background: 'rgba(15, 23, 42, 0.4)',
        }}>
          {[
            { key: 'inbox', label: 'Inbox', icon: Inbox, count: unreadCount || null },
            { key: 'queue', label: 'Approval Queue', icon: Clock, count: queue.length || null },
            { key: 'stats', label: 'Analytics', icon: Activity, count: null },
          ].map(t => (
            <button key={t.key} onClick={() => setTab(t.key as any)} style={{
              padding: '12px 20px', border: 'none', cursor: 'pointer',
              background: tab === t.key ? 'rgba(34, 211, 238, 0.06)' : 'transparent',
              borderBottom: tab === t.key ? '2px solid #22d3ee' : '2px solid transparent',
              color: tab === t.key ? '#22d3ee' : '#64748b',
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 13, fontWeight: 500, transition: 'all 0.2s',
            }}>
              <t.icon size={15} />
              {t.label}
              {t.count !== null && t.count > 0 && (
                <span style={{
                  background: t.key === 'queue' ? '#fbbf24' : 'rgba(34, 211, 238, 0.2)',
                  color: t.key === 'queue' ? '#0f172a' : '#22d3ee',
                  borderRadius: 10, padding: '1px 7px', fontSize: 11, fontWeight: 700,
                }}>{t.count}</span>
              )}
            </button>
          ))}
        </div>

        <div style={{ padding: '16px 24px' }}>
          {/* ═══ INBOX TAB ═══ */}
          {tab === 'inbox' && (
            <div style={{ display: 'flex', gap: 16 }}>
              {/* Left: Email List */}
              <div style={{ flex: selectedEmail ? '0 0 520px' : '1', display: 'flex', flexDirection: 'column' }}>
                {/* ── Toolbar ── */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                  {/* Search */}
                  <div style={{ flex: 1, minWidth: 180, position: 'relative' }}>
                    <Search size={14} style={{ position: 'absolute', left: 10, top: 9, color: '#64748b' }} />
                    <input value={search} onChange={e => setSearch(e.target.value)}
                      placeholder="Search emails, customers, policies..."
                      style={{
                        width: '100%', padding: '7px 10px 7px 32px',
                        background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(34, 211, 238, 0.12)',
                        borderRadius: 7, color: '#e2e8f0', fontSize: 12, outline: 'none',
                      }}
                    />
                  </div>
                  {/* Category filter */}
                  <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} style={{
                    padding: '7px 10px', background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(34, 211, 238, 0.12)', borderRadius: 7,
                    color: '#e2e8f0', fontSize: 12,
                  }}>
                    <option value="">All Categories</option>
                    {Object.keys(categoryColors).map(c => <option key={c} value={c}>{formatCategory(c)}</option>)}
                  </select>
                  {/* Sensitivity filter */}
                  <select value={filterSensitivity} onChange={e => setFilterSensitivity(e.target.value)} style={{
                    padding: '7px 10px', background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(34, 211, 238, 0.12)', borderRadius: 7,
                    color: '#e2e8f0', fontSize: 12,
                  }}>
                    <option value="">All Sensitivity</option>
                    <option value="routine">Routine</option>
                    <option value="moderate">Moderate</option>
                    <option value="sensitive">Sensitive</option>
                    <option value="critical">Critical</option>
                  </select>
                  {/* Compact toggle */}
                  <button onClick={() => setCompact(!compact)} style={{
                    ...s.btn(compact), display: 'flex', alignItems: 'center', gap: 4,
                  }} title={compact ? 'Expand view' : 'Compact view'}>
                    {compact ? <Maximize2 size={12} /> : <Minimize2 size={12} />}
                  </button>
                </div>

                {/* ── View filters (All / Unread / Needs Attention / Archived) ── */}
                <div style={{ display: 'flex', gap: 6, marginBottom: 12, alignItems: 'center' }}>
                  {([
                    { key: 'all', label: 'All', count: emails.filter(e => !archivedIds.has(e.id)).length },
                    { key: 'unread', label: 'Unread', count: unreadCount },
                    { key: 'attention', label: 'Needs Attention', count: attentionCount },
                    { key: 'archived', label: 'Archived', count: archivedCount },
                  ] as const).map(f => (
                    <button key={f.key} onClick={() => { setViewFilter(f.key); setSelectedIds(new Set()); }} style={{
                      ...s.btn(viewFilter === f.key),
                      display: 'flex', alignItems: 'center', gap: 5,
                    }}>
                      {f.key === 'attention' && <Bell size={11} />}
                      {f.key === 'archived' && <Archive size={11} />}
                      {f.label}
                      {f.count > 0 && (
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: '0 5px', borderRadius: 8,
                          background: viewFilter === f.key ? 'rgba(34, 211, 238, 0.2)' : 'rgba(100, 116, 139, 0.15)',
                          color: viewFilter === f.key ? '#22d3ee' : '#94a3b8',
                        }}>{f.count}</span>
                      )}
                    </button>
                  ))}

                  {/* Spacer */}
                  <div style={{ flex: 1 }} />

                  {/* Batch actions */}
                  {selectedIds.size > 0 && (
                    <div ref={batchRef} style={{ position: 'relative' }}>
                      <button onClick={() => setBatchMenuOpen(!batchMenuOpen)} style={{
                        padding: '6px 12px', background: 'rgba(34, 211, 238, 0.12)',
                        border: '1px solid rgba(34, 211, 238, 0.3)', borderRadius: 6,
                        color: '#22d3ee', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                        display: 'flex', alignItems: 'center', gap: 5,
                      }}>
                        {selectedIds.size} selected <ChevronDown size={12} />
                      </button>
                      {batchMenuOpen && (
                        <div style={{
                          position: 'absolute', right: 0, top: '100%', marginTop: 4,
                          background: 'rgba(15, 23, 42, 0.95)', border: '1px solid rgba(34, 211, 238, 0.2)',
                          borderRadius: 8, padding: 4, minWidth: 160, zIndex: 50,
                          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                        }}>
                          <button onClick={batchMarkRead} style={batchItemStyle}>
                            <Eye size={13} /> Mark as Read
                          </button>
                          <button onClick={batchMarkUnread} style={batchItemStyle}>
                            <EyeOff size={13} /> Mark as Unread
                          </button>
                          {viewFilter === 'archived' ? (
                            <button onClick={batchUnarchive} style={batchItemStyle}>
                              <MailOpen size={13} /> Unarchive
                            </button>
                          ) : (
                            <button onClick={batchArchive} style={batchItemStyle}>
                              <Archive size={13} /> Archive
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* ── Select All toggle ── */}
                {filteredEmails.length > 0 && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
                    borderBottom: '1px solid rgba(34, 211, 238, 0.06)', marginBottom: 4,
                  }}>
                    <button onClick={selectAll} style={{
                      background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                      color: selectedIds.size === filteredEmails.length ? '#22d3ee' : '#475569',
                      display: 'flex', alignItems: 'center',
                    }}>
                      {selectedIds.size === filteredEmails.length && selectedIds.size > 0
                        ? <CheckSquare size={15} />
                        : <Square size={15} />}
                    </button>
                    <span style={{ fontSize: 11, color: '#64748b' }}>
                      {filteredEmails.length} email{filteredEmails.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                )}

                {/* ── Email List ── */}
                {loading ? (
                  <div style={{ textAlign: 'center', padding: 40, color: '#64748b' }}>
                    <RefreshCw size={20} style={{ animation: 'spin 1s linear infinite' }} />
                    <p style={{ fontSize: 13, marginTop: 8 }}>Loading...</p>
                  </div>
                ) : filteredEmails.length === 0 ? (
                  <div style={{
                    textAlign: 'center', padding: 48, ...s.glass,
                  }}>
                    {viewFilter === 'archived' ? (
                      <>
                        <Archive size={36} color="#334155" />
                        <p style={{ color: '#64748b', marginTop: 12, fontSize: 14 }}>No archived emails</p>
                      </>
                    ) : viewFilter === 'unread' ? (
                      <>
                        <CheckCircle size={36} color="#34d399" />
                        <p style={{ color: '#34d399', marginTop: 12, fontSize: 14, fontWeight: 600 }}>All caught up!</p>
                        <p style={{ color: '#64748b', fontSize: 12 }}>No unread emails.</p>
                      </>
                    ) : viewFilter === 'attention' ? (
                      <>
                        <CheckCircle size={36} color="#34d399" />
                        <p style={{ color: '#34d399', marginTop: 12, fontSize: 14, fontWeight: 600 }}>Nothing needs attention</p>
                        <p style={{ color: '#64748b', fontSize: 12 }}>All items are resolved.</p>
                      </>
                    ) : (
                      <>
                        <Inbox size={36} color="#334155" />
                        <p style={{ color: '#64748b', marginTop: 12, fontSize: 14 }}>No emails yet</p>
                        <p style={{ color: '#475569', fontSize: 12, maxWidth: 360, margin: '6px auto 0' }}>
                          Forward emails to <strong style={{ color: '#22d3ee' }}>process@mail.betterchoiceins.com</strong>
                        </p>
                      </>
                    )}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                    {groupedEmails.map(group => (
                      <div key={group.label}>
                        {/* Date group header */}
                        <div style={{
                          padding: '8px 8px 4px',
                          fontSize: 11, fontWeight: 700, color: '#475569',
                          textTransform: 'uppercase', letterSpacing: 0.8,
                          borderBottom: '1px solid rgba(34, 211, 238, 0.04)',
                        }}>
                          {group.label}
                        </div>
                        {group.emails.map(email => {
                          const isRead = readIds.has(email.id);
                          const isSelected = selectedIds.has(email.id);
                          const isActive = selectedEmail?.id === email.id;
                          const sensConf = sensitivityConfig[email.sensitivity] || sensitivityConfig.routine;
                          const statConf = statusConfig[email.status] || { color: '#64748b', label: email.status };
                          const attention = needsAttention(email);

                          return (
                            <div key={email.id} onClick={() => fetchEmailDetail(email.id)}
                              style={{
                                padding: compact ? '8px 10px' : '12px 14px',
                                cursor: 'pointer',
                                background: isActive
                                  ? 'rgba(34, 211, 238, 0.08)'
                                  : isRead
                                    ? 'rgba(15, 23, 42, 0.15)'
                                    : 'rgba(15, 23, 42, 0.35)',
                                borderBottom: '1px solid rgba(34, 211, 238, 0.04)',
                                borderLeft: `3px solid ${attention ? '#fbbf24' : categoryColors[email.category] || '#64748b'}`,
                                transition: 'all 0.12s',
                                display: 'flex', alignItems: 'flex-start', gap: 10,
                                opacity: isRead && !isActive ? 0.75 : 1,
                              }}
                              onMouseEnter={e => {
                                if (!isActive) {
                                  (e.currentTarget as HTMLDivElement).style.background = 'rgba(34, 211, 238, 0.05)';
                                }
                              }}
                              onMouseLeave={e => {
                                if (!isActive) {
                                  (e.currentTarget as HTMLDivElement).style.background = isRead
                                    ? 'rgba(15, 23, 42, 0.15)' : 'rgba(15, 23, 42, 0.35)';
                                }
                              }}
                            >
                              {/* Checkbox */}
                              <button onClick={(e) => toggleSelect(email.id, e)} style={{
                                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                                color: isSelected ? '#22d3ee' : '#334155', flexShrink: 0, marginTop: compact ? 0 : 2,
                                display: 'flex', alignItems: 'center',
                              }}>
                                {isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                              </button>

                              {/* Unread dot */}
                              <div style={{
                                width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                                marginTop: compact ? 4 : 6,
                                background: isRead ? 'transparent' : '#22d3ee',
                                boxShadow: isRead ? 'none' : '0 0 6px rgba(34, 211, 238, 0.5)',
                              }} />

                              {/* Content */}
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: compact ? 2 : 4 }}>
                                  <span style={{
                                    fontSize: 13, fontWeight: isRead ? 400 : 700,
                                    color: isRead ? '#94a3b8' : '#f1f5f9',
                                    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                  }}>
                                    {email.subject || '(no subject)'}
                                  </span>
                                  <span style={{ fontSize: 10, color: '#475569', marginLeft: 8, whiteSpace: 'nowrap', flexShrink: 0 }}>
                                    {timeAgo(email.created_at)}
                                  </span>
                                </div>

                                {/* Badges row */}
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                  <span style={{
                                    fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                                    background: `${categoryColors[email.category] || '#64748b'}18`,
                                    color: categoryColors[email.category] || '#64748b',
                                    textTransform: 'uppercase', letterSpacing: 0.5,
                                  }}>
                                    {formatCategory(email.category)}
                                  </span>
                                  <span style={{ fontSize: 10, color: sensConf.color, display: 'flex', alignItems: 'center', gap: 2 }}>
                                    <sensConf.icon size={9} />{sensConf.label}
                                  </span>
                                  <span style={{ fontSize: 10, color: statConf.color }}>• {statConf.label}</span>
                                  {email.customer_name && (
                                    <span style={{ fontSize: 10, color: '#34d399', display: 'flex', alignItems: 'center', gap: 2 }}>
                                      <User size={9} />{email.customer_name}
                                    </span>
                                  )}
                                  {email.nowcerts_note_logged && <span style={{ fontSize: 9, color: '#a78bfa' }}>📋</span>}
                                  {attention && (
                                    <span style={{
                                      fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                                      background: 'rgba(251, 191, 36, 0.15)', color: '#fbbf24',
                                    }}>ACTION</span>
                                  )}
                                </div>

                                {/* Summary — only in expanded mode */}
                                {!compact && email.ai_summary && (
                                  <p style={{
                                    fontSize: 11, color: isRead ? '#64748b' : '#94a3b8',
                                    margin: '4px 0 0', lineHeight: 1.4,
                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                  }}>
                                    {email.ai_summary}
                                  </p>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* ═══ Right: Email Detail ═══ */}
              {selectedEmail && (
                <div style={{
                  flex: 1, minWidth: 380,
                  ...s.glass, overflow: 'hidden', display: 'flex', flexDirection: 'column',
                }}>
                  {/* Detail Header */}
                  <div style={{
                    padding: '14px 18px',
                    borderBottom: '1px solid rgba(34, 211, 238, 0.08)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <h3 style={{ margin: 0, fontSize: 15, color: '#f1f5f9', lineHeight: 1.3 }}>{selectedEmail.subject}</h3>
                      <p style={{ margin: '3px 0 0', fontSize: 11, color: '#64748b' }}>
                        From: {selectedEmail.from_address}
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      {!archivedIds.has(selectedEmail.id) && (
                        <button onClick={() => archiveEmails([selectedEmail.id])} style={{
                          background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: 4,
                        }} title="Archive">
                          <Archive size={16} />
                        </button>
                      )}
                      {archivedIds.has(selectedEmail.id) && (
                        <button onClick={() => unarchiveEmails([selectedEmail.id])} style={{
                          background: 'none', border: 'none', color: '#22d3ee', cursor: 'pointer', padding: 4,
                        }} title="Unarchive">
                          <MailOpen size={16} />
                        </button>
                      )}
                      <button onClick={() => setSelectedEmail(null)} style={{
                        background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: 4,
                      }}>
                        <X size={16} />
                      </button>
                    </div>
                  </div>

                  <div style={{ padding: 18, overflowY: 'auto', flex: 1 }}>
                    {/* AI Analysis Card */}
                    <div style={{
                      background: 'rgba(34, 211, 238, 0.04)', border: '1px solid rgba(34, 211, 238, 0.12)',
                      borderRadius: 8, padding: 14, marginBottom: 14,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                        <Zap size={14} color="#22d3ee" />
                        <span style={{ fontSize: 12, fontWeight: 600, color: '#22d3ee' }}>AI Analysis</span>
                        {selectedEmail.confidence_score && (
                          <span style={{ fontSize: 10, color: '#64748b' }}>
                            {(selectedEmail.confidence_score * 100).toFixed(0)}% confidence
                          </span>
                        )}
                      </div>
                      <p style={{ fontSize: 12, color: '#e2e8f0', margin: '0 0 10px', lineHeight: 1.5 }}>
                        {selectedEmail.ai_summary}
                      </p>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11 }}>
                        {selectedEmail.extracted_carrier && (
                          <div style={{ color: '#94a3b8' }}>
                            <span style={{ color: '#64748b' }}>Carrier:</span> {selectedEmail.extracted_carrier}
                          </div>
                        )}
                        {selectedEmail.extracted_policy_number && (
                          <div style={{ color: '#94a3b8' }}>
                            <span style={{ color: '#64748b' }}>Policy:</span> {selectedEmail.extracted_policy_number}
                          </div>
                        )}
                        {selectedEmail.customer_name && (
                          <div style={{ color: '#34d399' }}>
                            <span style={{ color: '#64748b' }}>Customer:</span> {selectedEmail.customer_name}
                            {selectedEmail.match_method && <span style={{ color: '#64748b' }}> (via {selectedEmail.match_method})</span>}
                          </div>
                        )}
                        {selectedEmail.extracted_insured_name && !selectedEmail.customer_name && (
                          <div style={{ color: '#f97316' }}>
                            <span style={{ color: '#64748b' }}>Insured:</span> {selectedEmail.extracted_insured_name} (unmatched)
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Reprocess button for failed */}
                    {selectedEmail.status === 'failed' && (
                      <button onClick={() => reprocess(selectedEmail.id)} style={{
                        width: '100%', padding: '8px 14px', marginBottom: 14,
                        background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)',
                        borderRadius: 8, color: '#f87171', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                        fontSize: 12, fontWeight: 500,
                      }}>
                        <RotateCw size={13} /> Reprocess Failed Email
                        {selectedEmail.error_message && (
                          <span style={{ fontSize: 10, color: '#ef4444', marginLeft: 6 }}>({selectedEmail.error_message})</span>
                        )}
                      </button>
                    )}

                    {/* Outbound Messages */}
                    {selectedEmail.outbound_messages && selectedEmail.outbound_messages.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <h4 style={{ fontSize: 12, color: '#64748b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
                          <Send size={13} /> Outbound Communication
                        </h4>
                        {selectedEmail.outbound_messages.map(msg => (
                          <div key={msg.id} style={{
                            background: 'rgba(15, 23, 42, 0.4)',
                            border: `1px solid ${msg.status === 'pending_approval' ? 'rgba(251, 191, 36, 0.25)' : 'rgba(34, 211, 238, 0.08)'}`,
                            borderRadius: 8, padding: 14, marginBottom: 8,
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                              <span style={{ fontSize: 11, color: '#94a3b8' }}>To: {msg.to_email}</span>
                              <span style={{
                                fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4,
                                background: msg.status === 'pending_approval' ? 'rgba(251, 191, 36, 0.12)' :
                                  msg.status === 'sent' || msg.status === 'auto_sent' ? 'rgba(52, 211, 153, 0.12)' : 'rgba(100, 116, 139, 0.12)',
                                color: msg.status === 'pending_approval' ? '#fbbf24' :
                                  msg.status === 'sent' || msg.status === 'auto_sent' ? '#34d399' : '#64748b',
                              }}>
                                {msg.status.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            </div>
                            <p style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0', margin: '0 0 3px' }}>{msg.subject}</p>
                            {msg.ai_rationale && (
                              <p style={{ fontSize: 10, color: '#64748b', margin: '0 0 6px', fontStyle: 'italic' }}>AI: {msg.ai_rationale}</p>
                            )}
                            <div style={{
                              background: 'rgba(255,255,255,0.02)', borderRadius: 6, padding: 10, marginBottom: 10,
                              fontSize: 12, color: '#cbd5e1', lineHeight: 1.5, maxHeight: 180, overflowY: 'auto',
                            }} dangerouslySetInnerHTML={{ __html: msg.body_html }} />

                            {/* Approval Actions */}
                            {(msg.status === 'pending_approval' || msg.status === 'draft') && editingOutbound !== msg.id && (
                              <div style={{ display: 'flex', gap: 6 }}>
                                <button onClick={() => approveOutbound(msg.id)} style={{
                                  flex: 1, padding: '7px 14px',
                                  background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                                  border: 'none', borderRadius: 6, color: '#0f172a',
                                  fontWeight: 600, fontSize: 12, cursor: 'pointer',
                                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
                                }}>
                                  <Check size={13} /> Approve & Send
                                </button>
                                <button onClick={() => {
                                  setEditingOutbound(msg.id); setEditSubject(msg.subject); setEditBody(msg.body_plain || '');
                                }} style={{
                                  padding: '7px 14px', background: 'rgba(167, 139, 250, 0.08)',
                                  border: '1px solid rgba(167, 139, 250, 0.25)', borderRadius: 6,
                                  color: '#a78bfa', cursor: 'pointer', fontSize: 12,
                                  display: 'flex', alignItems: 'center', gap: 5,
                                }}>
                                  <Edit3 size={13} /> Edit
                                </button>
                                <button onClick={() => rejectOutbound(msg.id)} style={{
                                  padding: '7px 14px', background: 'rgba(239, 68, 68, 0.08)',
                                  border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 6,
                                  color: '#f87171', cursor: 'pointer', fontSize: 12,
                                  display: 'flex', alignItems: 'center', gap: 5,
                                }}>
                                  <X size={13} /> Reject
                                </button>
                              </div>
                            )}

                            {/* Edit Mode */}
                            {editingOutbound === msg.id && (
                              <div style={{ marginTop: 8 }}>
                                <input value={editSubject} onChange={e => setEditSubject(e.target.value)} style={{
                                  width: '100%', padding: 7, marginBottom: 6,
                                  background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(34, 211, 238, 0.15)',
                                  borderRadius: 6, color: '#e2e8f0', fontSize: 12,
                                }} />
                                <textarea value={editBody} onChange={e => setEditBody(e.target.value)} rows={6} style={{
                                  width: '100%', padding: 7,
                                  background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(34, 211, 238, 0.15)',
                                  borderRadius: 6, color: '#e2e8f0', fontSize: 12,
                                  resize: 'vertical', fontFamily: 'inherit',
                                }} />
                                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                                  <button onClick={() => editAndSend(msg.id)} style={{
                                    flex: 1, padding: '7px 14px',
                                    background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                                    border: 'none', borderRadius: 6, color: '#0f172a',
                                    fontWeight: 600, fontSize: 12, cursor: 'pointer',
                                  }}>Save & Send</button>
                                  <button onClick={() => setEditingOutbound(null)} style={{
                                    padding: '7px 14px', background: 'rgba(100, 116, 139, 0.12)',
                                    border: '1px solid rgba(100, 116, 139, 0.25)',
                                    borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 12,
                                  }}>Cancel</button>
                                </div>
                              </div>
                            )}

                            {msg.sent_at && (
                              <p style={{ fontSize: 10, color: '#34d399', margin: '6px 0 0' }}>
                                ✓ Sent {timeAgo(msg.sent_at)}
                                {msg.approved_by && ` • Approved by ${msg.approved_by}`}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Email Body */}
                    <div>
                      <h4 style={{ fontSize: 12, color: '#64748b', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
                        <Mail size={13} /> Original Email
                      </h4>
                      <div style={{
                        background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(34, 211, 238, 0.04)',
                        borderRadius: 8, padding: 14,
                        fontSize: 12, color: '#cbd5e1', lineHeight: 1.6,
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      }}>
                        {selectedEmail.body_plain || '(no content)'}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ═══ QUEUE TAB ═══ */}
          {tab === 'queue' && (
            <div>
              {queue.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 48, ...s.glass }}>
                  <CheckCircle size={40} color="#34d399" />
                  <p style={{ color: '#34d399', marginTop: 12, fontWeight: 600, fontSize: 15 }}>All caught up!</p>
                  <p style={{ color: '#64748b', fontSize: 12 }}>No messages waiting for approval.</p>
                </div>
              ) : (
                queue.map(msg => (
                  <div key={msg.id} style={{
                    ...s.glass, padding: 18, marginBottom: 10,
                    borderLeft: '3px solid #fbbf24',
                    borderColor: 'rgba(251, 191, 36, 0.2)',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <div>
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{msg.subject}</span>
                        <p style={{ fontSize: 11, color: '#94a3b8', margin: '3px 0 0' }}>
                          To: {msg.to_name || msg.to_email} • {timeAgo(msg.created_at)}
                        </p>
                      </div>
                      <span style={{
                        fontSize: 10, padding: '3px 8px', borderRadius: 4,
                        background: 'rgba(251, 191, 36, 0.12)', color: '#fbbf24', fontWeight: 600,
                      }}>PENDING</span>
                    </div>
                    {msg.ai_rationale && (
                      <p style={{ fontSize: 11, color: '#64748b', margin: '0 0 10px', fontStyle: 'italic' }}>💡 {msg.ai_rationale}</p>
                    )}
                    <div style={{
                      background: 'rgba(255,255,255,0.02)', borderRadius: 8, padding: 14, marginBottom: 14,
                      fontSize: 12, color: '#cbd5e1', maxHeight: 180, overflowY: 'auto',
                    }} dangerouslySetInnerHTML={{ __html: msg.body_html }} />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button onClick={() => approveOutbound(msg.id)} style={{
                        flex: 1, padding: '9px 18px',
                        background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                        border: 'none', borderRadius: 8, color: '#0f172a',
                        fontWeight: 600, fontSize: 13, cursor: 'pointer',
                      }}>✓ Approve & Send</button>
                      <button onClick={() => rejectOutbound(msg.id)} style={{
                        padding: '9px 18px', background: 'rgba(239, 68, 68, 0.08)',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                        borderRadius: 8, color: '#f87171', cursor: 'pointer', fontSize: 13,
                      }}>✕ Reject</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* ═══ STATS TAB ═══ */}
          {tab === 'stats' && stats && (
            <div>
              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20,
              }}>
                {[
                  { label: 'Received (24h)', value: stats.received_24h, color: '#22d3ee', icon: Inbox },
                  { label: 'Received (7d)', value: stats.received_7d, color: '#60a5fa', icon: Mail },
                  { label: 'Pending Approval', value: stats.pending_approval, color: '#fbbf24', icon: Clock },
                  { label: 'Auto-Sent (24h)', value: stats.auto_sent_24h, color: '#34d399', icon: Send },
                  { label: 'Matched (7d)', value: stats.matched_7d, color: '#a78bfa', icon: User },
                  { label: 'Unmatched (7d)', value: stats.unmatched_7d, color: '#f97316', icon: AlertTriangle },
                  { label: 'Failed', value: stats.failed, color: '#ef4444', icon: XCircle },
                ].map((stat, i) => (
                  <div key={i} style={{ ...s.glass, padding: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <stat.icon size={14} color={stat.color} />
                      <span style={{ fontSize: 11, color: '#64748b' }}>{stat.label}</span>
                    </div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: stat.color }}>{stat.value}</div>
                  </div>
                ))}
              </div>

              {Object.keys(stats.category_breakdown).length > 0 && (
                <div style={{ ...s.glass, padding: 20 }}>
                  <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 14 }}>Category Breakdown (7 days)</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {Object.entries(stats.category_breakdown)
                      .sort((a, b) => b[1] - a[1])
                      .map(([cat, count]) => {
                        const maxCount = Math.max(...Object.values(stats.category_breakdown));
                        return (
                          <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ width: 140, fontSize: 12, color: '#94a3b8' }}>{formatCategory(cat)}</span>
                            <div style={{ flex: 1, height: 6, background: 'rgba(15, 23, 42, 0.8)', borderRadius: 4 }}>
                              <div style={{
                                width: `${(count / maxCount) * 100}%`, height: '100%',
                                background: categoryColors[cat] || '#64748b', borderRadius: 4,
                                transition: 'width 0.3s',
                              }} />
                            </div>
                            <span style={{ width: 36, textAlign: 'right', fontSize: 12, fontWeight: 600, color: categoryColors[cat] || '#64748b' }}>
                              {count}
                            </span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <style jsx global>{`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
          }
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    </>
  );
}

// Batch menu item style
const batchItemStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8,
  width: '100%', padding: '8px 12px', border: 'none', borderRadius: 4,
  background: 'transparent', color: '#cbd5e1', cursor: 'pointer',
  fontSize: 12, textAlign: 'left' as const,
  transition: 'background 0.1s',
};
