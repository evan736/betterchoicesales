import React, { useState, useEffect, useCallback } from 'react';
import Head from 'next/head';
import {
  Inbox, Send, AlertTriangle, CheckCircle, XCircle, RefreshCw,
  Search, Filter, Eye, Clock, Shield, Zap, Mail, User, FileText,
  ChevronDown, ChevronRight, ArrowRight, RotateCw, Edit3, Check, X,
  Activity, TrendingUp, AlertCircle, Archive
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
  non_payment: '#f87171',
  cancellation: '#ef4444',
  non_renewal: '#f97316',
  underwriting_requirement: '#fbbf24',
  renewal_notice: '#a78bfa',
  policy_change: '#60a5fa',
  claim_notice: '#f43f5e',
  billing_inquiry: '#38bdf8',
  customer_request: '#22d3ee',
  general_inquiry: '#94a3b8',
  endorsement: '#818cf8',
  new_business_confirmation: '#34d399',
  audit_notice: '#e879f9',
  other: '#64748b',
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
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatCategory(cat: string): string {
  return (cat || 'other').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
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

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers = { Authorization: `Bearer ${token}` };

  const fetchEmails = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { limit: 50 };
      if (search) params.search = search;
      if (filterCategory) params.category = filterCategory;
      if (filterSensitivity) params.sensitivity = filterSensitivity;
      const res = await axios.get(`${API}/api/smart-inbox/emails`, { params, headers });
      setEmails(res.data.emails || []);
    } catch (err) {
      console.error('Failed to fetch emails', err);
    }
    setLoading(false);
  }, [search, filterCategory, filterSensitivity]);

  const fetchQueue = async () => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/queue`, { params: { status: 'pending_approval' }, headers });
      setQueue(res.data.queue || []);
    } catch (err) {
      console.error('Failed to fetch queue', err);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/stats`, { headers });
      setStats(res.data);
    } catch (err) {
      console.error('Failed to fetch stats', err);
    }
  };

  const fetchEmailDetail = async (id: number) => {
    try {
      const res = await axios.get(`${API}/api/smart-inbox/emails/${id}`, { headers });
      setSelectedEmail(res.data);
    } catch (err) {
      console.error('Failed to fetch email detail', err);
    }
  };

  useEffect(() => {
    fetchEmails();
    fetchQueue();
    fetchStats();
  }, []);

  useEffect(() => {
    fetchEmails();
  }, [search, filterCategory, filterSensitivity]);

  const approveOutbound = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/approve`, {}, { headers });
      fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Approve failed');
    }
  };

  const rejectOutbound = async (id: number) => {
    const reason = prompt('Rejection reason (optional):');
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/reject`, null, { headers, params: { reason } });
      fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Reject failed');
    }
  };

  const editAndSend = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/queue/${id}/edit`, {
        subject: editSubject,
        body_html: `<div style="font-family: -apple-system, sans-serif;">${editBody.replace(/\n/g, '<br>')}</div>`,
        body_plain: editBody,
        send: true,
      }, { headers });
      setEditingOutbound(null);
      fetchQueue();
      if (selectedEmail) fetchEmailDetail(selectedEmail.id);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Edit & send failed');
    }
  };

  const reprocess = async (id: number) => {
    try {
      await axios.post(`${API}/api/smart-inbox/reprocess/${id}`, {}, { headers });
      fetchEmails();
    } catch (err) {
      console.error('Reprocess failed', err);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <>
      <Head><title>Smart Inbox — ORBIT</title></Head>
      <div style={{
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #0a0e1a 0%, #0f172a 50%, #0c1220 100%)',
        color: '#e2e8f0',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      }}>
        {/* Header */}
        <div style={{
          padding: '24px 32px',
          borderBottom: '1px solid rgba(34, 211, 238, 0.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'rgba(15, 23, 42, 0.8)',
          backdropFilter: 'blur(12px)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 42, height: 42, borderRadius: 10,
              background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 20px rgba(34, 211, 238, 0.3)',
            }}>
              <Inbox size={22} color="#0f172a" />
            </div>
            <div>
              <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: '#f1f5f9' }}>
                Smart Inbox
              </h1>
              <p style={{ fontSize: 12, color: '#64748b', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                AI-Powered Email Processing • 
                <span 
                  onClick={() => { navigator.clipboard.writeText('process@mail.betterchoiceins.com'); }}
                  style={{ color: '#22d3ee', cursor: 'pointer', borderBottom: '1px dashed rgba(34,211,238,0.4)' }}
                  title="Click to copy"
                >
                  process@mail.betterchoiceins.com
                </span>
                <span 
                  onClick={() => { navigator.clipboard.writeText('process@mail.betterchoiceins.com'); alert('Copied!'); }}
                  style={{ cursor: 'pointer', fontSize: 11, color: '#64748b' }}
                  title="Copy to clipboard"
                >📋</span>
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {queue.length > 0 && (
              <div style={{
                background: 'rgba(251, 191, 36, 0.15)',
                border: '1px solid rgba(251, 191, 36, 0.3)',
                borderRadius: 8, padding: '8px 16px',
                display: 'flex', alignItems: 'center', gap: 8,
                animation: 'pulse 2s infinite',
              }}>
                <AlertTriangle size={16} color="#fbbf24" />
                <span style={{ color: '#fbbf24', fontWeight: 600, fontSize: 14 }}>
                  {queue.length} awaiting approval
                </span>
              </div>
            )}
            <button onClick={() => { fetchEmails(); fetchQueue(); fetchStats(); }} style={{
              background: 'rgba(34, 211, 238, 0.1)',
              border: '1px solid rgba(34, 211, 238, 0.2)',
              borderRadius: 8, padding: '8px 16px',
              color: '#22d3ee', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 13, fontWeight: 500,
            }}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div style={{
          display: 'flex', gap: 0, padding: '0 32px',
          borderBottom: '1px solid rgba(34, 211, 238, 0.1)',
          background: 'rgba(15, 23, 42, 0.4)',
        }}>
          {[
            { key: 'inbox', label: 'Inbox', icon: Inbox, count: emails.length },
            { key: 'queue', label: 'Approval Queue', icon: Clock, count: queue.length },
            { key: 'stats', label: 'Analytics', icon: Activity, count: null },
          ].map(t => (
            <button key={t.key} onClick={() => setTab(t.key as any)} style={{
              padding: '14px 24px', border: 'none', cursor: 'pointer',
              background: tab === t.key ? 'rgba(34, 211, 238, 0.08)' : 'transparent',
              borderBottom: tab === t.key ? '2px solid #22d3ee' : '2px solid transparent',
              color: tab === t.key ? '#22d3ee' : '#64748b',
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 14, fontWeight: 500, transition: 'all 0.2s',
            }}>
              <t.icon size={16} />
              {t.label}
              {t.count !== null && t.count > 0 && (
                <span style={{
                  background: t.key === 'queue' ? '#fbbf24' : 'rgba(34, 211, 238, 0.2)',
                  color: t.key === 'queue' ? '#0f172a' : '#22d3ee',
                  borderRadius: 10, padding: '2px 8px', fontSize: 11, fontWeight: 700,
                }}>
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div style={{ padding: '24px 32px' }}>
          {/* ── INBOX TAB ───────────────────────────────────────────────── */}
          {tab === 'inbox' && (
            <div style={{ display: 'flex', gap: 24 }}>
              {/* Left: Email List */}
              <div style={{ flex: selectedEmail ? '0 0 480px' : '1' }}>
                {/* Filters */}
                <div style={{
                  display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap',
                }}>
                  <div style={{
                    flex: 1, minWidth: 200, position: 'relative',
                  }}>
                    <Search size={16} style={{ position: 'absolute', left: 12, top: 10, color: '#64748b' }} />
                    <input
                      value={search} onChange={e => setSearch(e.target.value)}
                      placeholder="Search emails, customers, policies..."
                      style={{
                        width: '100%', padding: '8px 12px 8px 36px',
                        background: 'rgba(15, 23, 42, 0.6)',
                        border: '1px solid rgba(34, 211, 238, 0.15)',
                        borderRadius: 8, color: '#e2e8f0', fontSize: 13,
                        outline: 'none',
                      }}
                    />
                  </div>
                  <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} style={{
                    padding: '8px 12px', background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(34, 211, 238, 0.15)',
                    borderRadius: 8, color: '#e2e8f0', fontSize: 13,
                  }}>
                    <option value="">All Categories</option>
                    {Object.keys(categoryColors).map(c => (
                      <option key={c} value={c}>{formatCategory(c)}</option>
                    ))}
                  </select>
                  <select value={filterSensitivity} onChange={e => setFilterSensitivity(e.target.value)} style={{
                    padding: '8px 12px', background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(34, 211, 238, 0.15)',
                    borderRadius: 8, color: '#e2e8f0', fontSize: 13,
                  }}>
                    <option value="">All Sensitivity</option>
                    <option value="routine">Routine</option>
                    <option value="moderate">Moderate</option>
                    <option value="sensitive">Sensitive</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>

                {/* Email List */}
                {loading ? (
                  <div style={{ textAlign: 'center', padding: 40, color: '#64748b' }}>
                    <RefreshCw size={24} style={{ animation: 'spin 1s linear infinite' }} />
                    <p>Loading...</p>
                  </div>
                ) : emails.length === 0 ? (
                  <div style={{
                    textAlign: 'center', padding: 60,
                    background: 'rgba(15, 23, 42, 0.4)',
                    border: '1px solid rgba(34, 211, 238, 0.1)',
                    borderRadius: 12,
                  }}>
                    <Inbox size={48} color="#334155" />
                    <p style={{ color: '#64748b', marginTop: 16 }}>No emails yet</p>
                    <p style={{ color: '#475569', fontSize: 13, maxWidth: 400, margin: '8px auto 0' }}>
                      Forward emails to <strong style={{ color: '#22d3ee' }}>process@mail.betterchoiceins.com</strong> and
                      they'll appear here with AI analysis.
                    </p>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {emails.map(email => {
                      const sensConf = sensitivityConfig[email.sensitivity] || sensitivityConfig.routine;
                      const statConf = statusConfig[email.status] || { color: '#64748b', label: email.status };
                      const isSelected = selectedEmail?.id === email.id;

                      return (
                        <div key={email.id} onClick={() => fetchEmailDetail(email.id)} style={{
                          padding: '14px 16px', cursor: 'pointer',
                          background: isSelected ? 'rgba(34, 211, 238, 0.08)' : 'rgba(15, 23, 42, 0.3)',
                          border: `1px solid ${isSelected ? 'rgba(34, 211, 238, 0.3)' : 'rgba(34, 211, 238, 0.05)'}`,
                          borderRadius: 8, transition: 'all 0.15s',
                          borderLeft: `3px solid ${categoryColors[email.category] || '#64748b'}`,
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                            <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {email.subject || '(no subject)'}
                            </span>
                            <span style={{ fontSize: 11, color: '#64748b', marginLeft: 8, whiteSpace: 'nowrap' }}>
                              {timeAgo(email.created_at)}
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                            {/* Category badge */}
                            <span style={{
                              fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                              background: `${categoryColors[email.category] || '#64748b'}20`,
                              color: categoryColors[email.category] || '#64748b',
                              textTransform: 'uppercase', letterSpacing: 0.5,
                            }}>
                              {formatCategory(email.category)}
                            </span>
                            {/* Sensitivity */}
                            <span style={{ fontSize: 10, color: sensConf.color, display: 'flex', alignItems: 'center', gap: 3 }}>
                              <sensConf.icon size={10} />{sensConf.label}
                            </span>
                            {/* Status */}
                            <span style={{ fontSize: 10, color: statConf.color }}>
                              • {statConf.label}
                            </span>
                            {/* Customer match */}
                            {email.customer_name && (
                              <span style={{ fontSize: 10, color: '#34d399', display: 'flex', alignItems: 'center', gap: 3 }}>
                                <User size={10} />{email.customer_name}
                              </span>
                            )}
                            {email.nowcerts_note_logged && (
                              <span style={{ fontSize: 10, color: '#a78bfa' }}>📋 Logged</span>
                            )}
                          </div>
                          {email.ai_summary && (
                            <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0', lineHeight: 1.4 }}>
                              {email.ai_summary}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Right: Email Detail */}
              {selectedEmail && (
                <div style={{
                  flex: 1, minWidth: 400,
                  background: 'rgba(15, 23, 42, 0.5)',
                  border: '1px solid rgba(34, 211, 238, 0.1)',
                  borderRadius: 12, overflow: 'hidden',
                }}>
                  {/* Detail Header */}
                  <div style={{
                    padding: '16px 20px',
                    borderBottom: '1px solid rgba(34, 211, 238, 0.1)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                  }}>
                    <div style={{ flex: 1 }}>
                      <h3 style={{ margin: 0, fontSize: 16, color: '#f1f5f9' }}>{selectedEmail.subject}</h3>
                      <p style={{ margin: '4px 0 0', fontSize: 12, color: '#64748b' }}>
                        From: {selectedEmail.from_address}
                      </p>
                    </div>
                    <button onClick={() => setSelectedEmail(null)} style={{
                      background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: 4,
                    }}>
                      <X size={18} />
                    </button>
                  </div>

                  <div style={{ padding: 20, overflowY: 'auto', maxHeight: 'calc(100vh - 280px)' }}>
                    {/* AI Analysis Card */}
                    <div style={{
                      background: 'rgba(34, 211, 238, 0.05)',
                      border: '1px solid rgba(34, 211, 238, 0.15)',
                      borderRadius: 10, padding: 16, marginBottom: 16,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                        <Zap size={16} color="#22d3ee" />
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#22d3ee' }}>AI Analysis</span>
                        {selectedEmail.confidence_score && (
                          <span style={{ fontSize: 11, color: '#64748b' }}>
                            {(selectedEmail.confidence_score * 100).toFixed(0)}% confidence
                          </span>
                        )}
                      </div>
                      <p style={{ fontSize: 13, color: '#e2e8f0', margin: '0 0 12px', lineHeight: 1.5 }}>
                        {selectedEmail.ai_summary}
                      </p>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        {selectedEmail.extracted_carrier && (
                          <div style={{ fontSize: 12, color: '#94a3b8' }}>
                            <span style={{ color: '#64748b' }}>Carrier:</span> {selectedEmail.extracted_carrier}
                          </div>
                        )}
                        {selectedEmail.extracted_policy_number && (
                          <div style={{ fontSize: 12, color: '#94a3b8' }}>
                            <span style={{ color: '#64748b' }}>Policy:</span> {selectedEmail.extracted_policy_number}
                          </div>
                        )}
                        {selectedEmail.customer_name && (
                          <div style={{ fontSize: 12, color: '#34d399' }}>
                            <span style={{ color: '#64748b' }}>Customer:</span> {selectedEmail.customer_name}
                            {selectedEmail.match_method && <span style={{ color: '#64748b' }}> (via {selectedEmail.match_method})</span>}
                          </div>
                        )}
                        {selectedEmail.extracted_insured_name && !selectedEmail.customer_name && (
                          <div style={{ fontSize: 12, color: '#f97316' }}>
                            <span style={{ color: '#64748b' }}>Insured:</span> {selectedEmail.extracted_insured_name} (unmatched)
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Status + Actions */}
                    {selectedEmail.status === 'failed' && (
                      <button onClick={() => reprocess(selectedEmail.id)} style={{
                        width: '100%', padding: '10px 16px', marginBottom: 16,
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        borderRadius: 8, color: '#f87171', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                        fontSize: 13, fontWeight: 500,
                      }}>
                        <RotateCw size={14} /> Reprocess Failed Email
                        {selectedEmail.error_message && (
                          <span style={{ fontSize: 11, color: '#ef4444', marginLeft: 8 }}>
                            ({selectedEmail.error_message})
                          </span>
                        )}
                      </button>
                    )}

                    {/* Outbound Messages */}
                    {selectedEmail.outbound_messages && selectedEmail.outbound_messages.length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <h4 style={{ fontSize: 13, color: '#64748b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                          <Send size={14} /> Outbound Communication
                        </h4>
                        {selectedEmail.outbound_messages.map(msg => (
                          <div key={msg.id} style={{
                            background: 'rgba(15, 23, 42, 0.4)',
                            border: `1px solid ${msg.status === 'pending_approval' ? 'rgba(251, 191, 36, 0.3)' : 'rgba(34, 211, 238, 0.1)'}`,
                            borderRadius: 10, padding: 16, marginBottom: 8,
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                              <span style={{ fontSize: 12, color: '#94a3b8' }}>To: {msg.to_email}</span>
                              <span style={{
                                fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                                background: msg.status === 'pending_approval' ? 'rgba(251, 191, 36, 0.15)' : 
                                           msg.status === 'sent' || msg.status === 'auto_sent' ? 'rgba(52, 211, 153, 0.15)' : 'rgba(100, 116, 139, 0.15)',
                                color: msg.status === 'pending_approval' ? '#fbbf24' : 
                                       msg.status === 'sent' || msg.status === 'auto_sent' ? '#34d399' : '#64748b',
                              }}>
                                {msg.status.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            </div>
                            <p style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', margin: '0 0 4px' }}>
                              {msg.subject}
                            </p>
                            {msg.ai_rationale && (
                              <p style={{ fontSize: 11, color: '#64748b', margin: '0 0 8px', fontStyle: 'italic' }}>
                                AI: {msg.ai_rationale}
                              </p>
                            )}

                            {/* Preview */}
                            <div style={{
                              background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: 12, marginBottom: 12,
                              fontSize: 13, color: '#cbd5e1', lineHeight: 1.5, maxHeight: 200, overflowY: 'auto',
                            }} dangerouslySetInnerHTML={{ __html: msg.body_html }} />

                            {/* Approval Actions */}
                            {(msg.status === 'pending_approval' || msg.status === 'draft') && editingOutbound !== msg.id && (
                              <div style={{ display: 'flex', gap: 8 }}>
                                <button onClick={() => approveOutbound(msg.id)} style={{
                                  flex: 1, padding: '8px 16px',
                                  background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                                  border: 'none', borderRadius: 6, color: '#0f172a',
                                  fontWeight: 600, fontSize: 13, cursor: 'pointer',
                                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                                }}>
                                  <Check size={14} /> Approve & Send
                                </button>
                                <button onClick={() => {
                                  setEditingOutbound(msg.id);
                                  setEditSubject(msg.subject);
                                  setEditBody(msg.body_plain || '');
                                }} style={{
                                  padding: '8px 16px',
                                  background: 'rgba(167, 139, 250, 0.1)',
                                  border: '1px solid rgba(167, 139, 250, 0.3)',
                                  borderRadius: 6, color: '#a78bfa', cursor: 'pointer',
                                  fontSize: 13, display: 'flex', alignItems: 'center', gap: 6,
                                }}>
                                  <Edit3 size={14} /> Edit
                                </button>
                                <button onClick={() => rejectOutbound(msg.id)} style={{
                                  padding: '8px 16px',
                                  background: 'rgba(239, 68, 68, 0.1)',
                                  border: '1px solid rgba(239, 68, 68, 0.3)',
                                  borderRadius: 6, color: '#f87171', cursor: 'pointer',
                                  fontSize: 13, display: 'flex', alignItems: 'center', gap: 6,
                                }}>
                                  <X size={14} /> Reject
                                </button>
                              </div>
                            )}

                            {/* Edit Mode */}
                            {editingOutbound === msg.id && (
                              <div style={{ marginTop: 8 }}>
                                <input value={editSubject} onChange={e => setEditSubject(e.target.value)} style={{
                                  width: '100%', padding: 8, marginBottom: 8,
                                  background: 'rgba(15, 23, 42, 0.6)',
                                  border: '1px solid rgba(34, 211, 238, 0.2)',
                                  borderRadius: 6, color: '#e2e8f0', fontSize: 13,
                                }} />
                                <textarea value={editBody} onChange={e => setEditBody(e.target.value)} rows={8} style={{
                                  width: '100%', padding: 8,
                                  background: 'rgba(15, 23, 42, 0.6)',
                                  border: '1px solid rgba(34, 211, 238, 0.2)',
                                  borderRadius: 6, color: '#e2e8f0', fontSize: 13,
                                  resize: 'vertical', fontFamily: 'inherit',
                                }} />
                                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                  <button onClick={() => editAndSend(msg.id)} style={{
                                    flex: 1, padding: '8px 16px',
                                    background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                                    border: 'none', borderRadius: 6, color: '#0f172a',
                                    fontWeight: 600, fontSize: 13, cursor: 'pointer',
                                  }}>
                                    Save & Send
                                  </button>
                                  <button onClick={() => setEditingOutbound(null)} style={{
                                    padding: '8px 16px', background: 'rgba(100, 116, 139, 0.15)',
                                    border: '1px solid rgba(100, 116, 139, 0.3)',
                                    borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 13,
                                  }}>
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            )}

                            {msg.sent_at && (
                              <p style={{ fontSize: 11, color: '#34d399', margin: '8px 0 0' }}>
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
                      <h4 style={{ fontSize: 13, color: '#64748b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Mail size={14} /> Original Email
                      </h4>
                      <div style={{
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(34, 211, 238, 0.05)',
                        borderRadius: 8, padding: 16,
                        fontSize: 13, color: '#cbd5e1', lineHeight: 1.6,
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

          {/* ── QUEUE TAB ──────────────────────────────────────────────── */}
          {tab === 'queue' && (
            <div>
              {queue.length === 0 ? (
                <div style={{
                  textAlign: 'center', padding: 60,
                  background: 'rgba(15, 23, 42, 0.4)',
                  border: '1px solid rgba(34, 211, 238, 0.1)',
                  borderRadius: 12,
                }}>
                  <CheckCircle size={48} color="#34d399" />
                  <p style={{ color: '#34d399', marginTop: 16, fontWeight: 600 }}>All caught up!</p>
                  <p style={{ color: '#64748b', fontSize: 13 }}>No messages waiting for approval.</p>
                </div>
              ) : (
                queue.map(msg => (
                  <div key={msg.id} style={{
                    background: 'rgba(15, 23, 42, 0.4)',
                    border: '1px solid rgba(251, 191, 36, 0.2)',
                    borderRadius: 10, padding: 20, marginBottom: 12,
                    borderLeft: '3px solid #fbbf24',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div>
                        <span style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{msg.subject}</span>
                        <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0' }}>
                          To: {msg.to_name || msg.to_email} • {timeAgo(msg.created_at)}
                        </p>
                      </div>
                      <span style={{
                        fontSize: 11, padding: '4px 10px', borderRadius: 4,
                        background: 'rgba(251, 191, 36, 0.15)', color: '#fbbf24', fontWeight: 600,
                      }}>
                        PENDING
                      </span>
                    </div>
                    {msg.ai_rationale && (
                      <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 12px', fontStyle: 'italic' }}>
                        💡 {msg.ai_rationale}
                      </p>
                    )}
                    <div style={{
                      background: 'rgba(255,255,255,0.02)', borderRadius: 8, padding: 16, marginBottom: 16,
                      fontSize: 13, color: '#cbd5e1', maxHeight: 200, overflowY: 'auto',
                    }} dangerouslySetInnerHTML={{ __html: msg.body_html }} />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button onClick={() => approveOutbound(msg.id)} style={{
                        flex: 1, padding: '10px 20px',
                        background: 'linear-gradient(135deg, #22d3ee, #0891b2)',
                        border: 'none', borderRadius: 8, color: '#0f172a',
                        fontWeight: 600, fontSize: 14, cursor: 'pointer',
                      }}>
                        ✓ Approve & Send
                      </button>
                      <button onClick={() => rejectOutbound(msg.id)} style={{
                        padding: '10px 20px',
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        borderRadius: 8, color: '#f87171', cursor: 'pointer', fontSize: 14,
                      }}>
                        ✕ Reject
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* ── STATS TAB ─────────────────────────────────────────────── */}
          {tab === 'stats' && stats && (
            <div>
              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                gap: 16, marginBottom: 24,
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
                  <div key={i} style={{
                    background: 'rgba(15, 23, 42, 0.5)',
                    border: '1px solid rgba(34, 211, 238, 0.1)',
                    borderRadius: 10, padding: 20,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                      <stat.icon size={16} color={stat.color} />
                      <span style={{ fontSize: 12, color: '#64748b' }}>{stat.label}</span>
                    </div>
                    <div style={{ fontSize: 28, fontWeight: 700, color: stat.color }}>
                      {stat.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Category Breakdown */}
              {Object.keys(stats.category_breakdown).length > 0 && (
                <div style={{
                  background: 'rgba(15, 23, 42, 0.5)',
                  border: '1px solid rgba(34, 211, 238, 0.1)',
                  borderRadius: 12, padding: 24,
                }}>
                  <h3 style={{ fontSize: 14, color: '#64748b', marginBottom: 16 }}>Category Breakdown (7 days)</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {Object.entries(stats.category_breakdown)
                      .sort((a, b) => b[1] - a[1])
                      .map(([cat, count]) => {
                        const maxCount = Math.max(...Object.values(stats.category_breakdown));
                        return (
                          <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <span style={{ width: 160, fontSize: 13, color: '#94a3b8' }}>{formatCategory(cat)}</span>
                            <div style={{ flex: 1, height: 8, background: 'rgba(15, 23, 42, 0.8)', borderRadius: 4 }}>
                              <div style={{
                                width: `${(count / maxCount) * 100}%`, height: '100%',
                                background: categoryColors[cat] || '#64748b', borderRadius: 4,
                                transition: 'width 0.3s',
                              }} />
                            </div>
                            <span style={{ width: 40, textAlign: 'right', fontSize: 13, fontWeight: 600, color: categoryColors[cat] || '#64748b' }}>
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
