import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  UserPlus, Phone, Mail, MapPin, Search, Filter, ChevronDown, ChevronUp,
  CheckCircle, Clock, FileText, XCircle, AlertCircle, RefreshCw, Users,
  ArrowRight, Calendar, DollarSign, Home, Car, Shield, Eye,
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
function headers() { return { Authorization: `Bearer ${localStorage.getItem('token') || ''}` }; }

function timeAgo(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string; icon: any }> = {
  new: { label: 'New', color: '#22d3ee', bg: 'rgba(34,211,238,0.12)', icon: AlertCircle },
  contacted: { label: 'Contacted', color: '#facc15', bg: 'rgba(250,204,21,0.12)', icon: Phone },
  quoted: { label: 'Quoted', color: '#818cf8', bg: 'rgba(129,140,248,0.12)', icon: FileText },
  sold: { label: 'Sold', color: '#22c55e', bg: 'rgba(34,197,94,0.12)', icon: CheckCircle },
  lost: { label: 'Lost', color: '#f87171', bg: 'rgba(248,113,113,0.12)', icon: XCircle },
};

const STATUSES = ['new', 'contacted', 'quoted', 'sold', 'lost'];

export default function LeadPipeline() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [leads, setLeads] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [roster, setRoster] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [days, setDays] = useState(30);
  const [showRoster, setShowRoster] = useState(false);

  const isManager = user?.role === 'admin' || user?.role === 'manager';

  const fetchLeads = useCallback(async () => {
    try {
      const params: any = { days, limit: 100 };
      if (statusFilter) params.status = statusFilter;
      if (agentFilter) params.assigned_to = agentFilter;
      if (search) params.search = search;
      const { data } = await axios.get(`${API}/api/leads`, { headers: headers(), params });
      setLeads(data.leads || []);
    } catch (e) { console.error(e); }
  }, [days, statusFilter, agentFilter, search]);

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/leads/stats`, { headers: headers(), params: { days } });
      setStats(data);
    } catch (e) { console.error(e); }
  }, [days]);

  const fetchRoster = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/leads/roster`, { headers: headers() });
      setRoster(data.roster || []);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) { router.push('/login'); return; }
    Promise.all([fetchLeads(), fetchStats(), fetchRoster()]).finally(() => setLoading(false));
  }, [user, authLoading, fetchLeads, fetchStats, fetchRoster]);

  const updateStatus = async (leadId: number, newStatus: string) => {
    try {
      await axios.patch(`${API}/api/leads/${leadId}`, { status: newStatus }, { headers: headers() });
      fetchLeads();
      fetchStats();
    } catch (e) { console.error(e); }
  };

  const updateNotes = async (leadId: number, notes: string) => {
    try {
      await axios.patch(`${API}/api/leads/${leadId}`, { notes }, { headers: headers() });
    } catch (e) { console.error(e); }
  };

  if (authLoading || loading) {
    return (
      <div style={{ minHeight: '100vh', background: '#0a0e1a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <RefreshCw size={24} color="#22d3ee" style={{ animation: 'spin 1s linear infinite' }} />
      </div>
    );
  }

  const panel: React.CSSProperties = {
    background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '12px', padding: '20px',
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0a0e1a', color: '#e2e8f0' }}>
      <Navbar />
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px 20px' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 700, color: '#fff' }}>
              <UserPlus size={24} style={{ marginRight: '10px', verticalAlign: 'middle', color: '#22d3ee' }} />
              Lead Pipeline
            </h1>
            <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '14px' }}>
              Round-robin lead distribution &amp; tracking
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {[7, 30, 90].map(d => (
              <button key={d} onClick={() => setDays(d)}
                style={{
                  padding: '6px 14px', borderRadius: '6px', border: 'none', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
                  background: days === d ? '#2563eb' : 'rgba(255,255,255,0.06)', color: days === d ? '#fff' : '#94a3b8',
                }}>
                {d}d
              </button>
            ))}
          </div>
        </div>

        {/* Stats Cards */}
        {stats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', marginBottom: '24px' }}>
            {[
              { label: 'Total Leads', value: stats.total, color: '#22d3ee' },
              { label: 'New', value: stats.new, color: '#22d3ee' },
              { label: 'Contacted', value: stats.contacted, color: '#facc15' },
              { label: 'Quoted', value: stats.quoted, color: '#818cf8' },
              { label: 'Sold', value: stats.sold, color: '#22c55e' },
              { label: 'Lost', value: stats.lost, color: '#f87171' },
            ].map(s => (
              <div key={s.label} style={{ ...panel, textAlign: 'center', padding: '16px' }}>
                <div style={{ fontSize: '28px', fontWeight: 700, color: s.color }}>{s.value}</div>
                <div style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>{s.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* Round Robin Roster (manager only) */}
        {isManager && (
          <div style={{ ...panel, marginBottom: '20px' }}>
            <div
              onClick={() => setShowRoster(!showRoster)}
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Users size={16} color="#22d3ee" />
                <span style={{ fontWeight: 600, fontSize: '14px' }}>Round Robin Roster</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>({roster.length} producers)</span>
              </div>
              {showRoster ? <ChevronUp size={16} color="#64748b" /> : <ChevronDown size={16} color="#64748b" />}
            </div>
            {showRoster && (
              <div style={{ marginTop: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
                {roster.map(r => (
                  <div key={r.user_id} style={{
                    padding: '14px', borderRadius: '8px',
                    background: r.is_next ? 'rgba(34,211,238,0.08)' : 'rgba(255,255,255,0.02)',
                    border: r.is_next ? '1px solid rgba(34,211,238,0.3)' : '1px solid rgba(255,255,255,0.04)',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, fontSize: '14px' }}>{r.name}</span>
                      {r.is_next && (
                        <span style={{ fontSize: '10px', background: '#22d3ee', color: '#0a0e1a', padding: '2px 8px', borderRadius: '99px', fontWeight: 700 }}>
                          NEXT UP
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>{r.total_leads} leads assigned</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Per-Agent Breakdown (manager only) */}
        {isManager && stats?.by_agent?.length > 0 && (
          <div style={{ ...panel, marginBottom: '20px' }}>
            <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Users size={16} color="#818cf8" /> Agent Performance
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
              {stats.by_agent.map((a: any) => (
                <div key={a.user_id} style={{
                  padding: '14px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)',
                }}>
                  <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '8px' }}>{a.name}</div>
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                    {(['new', 'contacted', 'quoted', 'sold', 'lost'] as const).map(s => {
                      const cfg = STATUS_CONFIG[s];
                      return (
                        <div key={s} style={{ fontSize: '12px' }}>
                          <span style={{ color: cfg.color, fontWeight: 700 }}>{a[s]}</span>
                          <span style={{ color: '#64748b', marginLeft: '3px' }}>{cfg.label}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: '1 1 250px' }}>
            <Search size={16} color="#64748b" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
            <input
              placeholder="Search name, phone, email..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && fetchLeads()}
              style={{
                width: '100%', padding: '10px 12px 10px 38px', borderRadius: '8px', fontSize: '14px',
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0',
                outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            style={{
              padding: '10px 14px', borderRadius: '8px', fontSize: '14px', cursor: 'pointer',
              background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0',
            }}
          >
            <option value="">All Statuses</option>
            {STATUSES.map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
          </select>
          {isManager && (
            <select
              value={agentFilter}
              onChange={e => setAgentFilter(e.target.value)}
              style={{
                padding: '10px 14px', borderRadius: '8px', fontSize: '14px', cursor: 'pointer',
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0',
              }}
            >
              <option value="">All Agents</option>
              {roster.map(r => <option key={r.user_id} value={r.user_id}>{r.name}</option>)}
            </select>
          )}
          <button onClick={() => { fetchLeads(); fetchStats(); }} style={{
            padding: '10px 16px', borderRadius: '8px', border: 'none', cursor: 'pointer',
            background: '#2563eb', color: '#fff', fontWeight: 600, fontSize: '14px',
            display: 'flex', alignItems: 'center', gap: '6px',
          }}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>

        {/* Leads Table */}
        <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
          {leads.length === 0 ? (
            <div style={{ padding: '48px', textAlign: 'center', color: '#64748b' }}>
              <UserPlus size={48} style={{ marginBottom: '12px', opacity: 0.3 }} />
              <p style={{ fontSize: '16px', fontWeight: 600 }}>No leads found</p>
              <p style={{ fontSize: '13px' }}>Leads from the quote form will appear here automatically.</p>
            </div>
          ) : (
            <div>
              {/* Table header */}
              <div style={{
                display: 'grid', gridTemplateColumns: isManager ? '2fr 1.2fr 1.5fr 1fr 1fr 1fr' : '2fr 1.2fr 1.5fr 1fr 1fr',
                padding: '12px 20px', background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.06)',
                fontSize: '11px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px',
              }}>
                <div>Lead</div>
                <div>Contact</div>
                <div>Products</div>
                {isManager && <div>Assigned To</div>}
                <div>Status</div>
                <div>Received</div>
              </div>
              {/* Lead rows */}
              {leads.map(lead => {
                const expanded = expandedId === lead.id;
                const cfg = STATUS_CONFIG[lead.status] || STATUS_CONFIG.new;
                const Icon = cfg.icon;
                return (
                  <div key={lead.id}>
                    <div
                      onClick={() => setExpandedId(expanded ? null : lead.id)}
                      style={{
                        display: 'grid', gridTemplateColumns: isManager ? '2fr 1.2fr 1.5fr 1fr 1fr 1fr' : '2fr 1.2fr 1.5fr 1fr 1fr',
                        padding: '14px 20px', cursor: 'pointer', alignItems: 'center',
                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                        background: expanded ? 'rgba(255,255,255,0.02)' : 'transparent',
                        transition: 'background 0.15s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                      onMouseLeave={e => (e.currentTarget.style.background = expanded ? 'rgba(255,255,255,0.02)' : 'transparent')}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '14px' }}>{lead.name}</div>
                        {lead.source && <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>{lead.source}</div>}
                      </div>
                      <div style={{ fontSize: '13px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Phone size={12} color="#64748b" /> {lead.phone}
                        </div>
                        {lead.email && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#64748b', fontSize: '12px', marginTop: '2px' }}>
                            <Mail size={11} /> {lead.email}
                          </div>
                        )}
                      </div>
                      <div style={{ fontSize: '13px', color: '#94a3b8' }}>{lead.policy_types || '—'}</div>
                      {isManager && (
                        <div style={{ fontSize: '13px', color: '#94a3b8', fontWeight: 500 }}>{lead.assigned_to_name || 'Unassigned'}</div>
                      )}
                      <div>
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: '4px',
                          padding: '4px 10px', borderRadius: '99px', fontSize: '12px', fontWeight: 600,
                          background: cfg.bg, color: cfg.color,
                        }}>
                          <Icon size={12} /> {cfg.label}
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#64748b' }}>{timeAgo(lead.created_at)}</div>
                    </div>

                    {/* Expanded detail */}
                    {expanded && (
                      <LeadDetail lead={lead} isManager={isManager} roster={roster} onStatusChange={updateStatus} onNotesChange={updateNotes} onRefresh={fetchLeads} />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <style jsx global>{`
        @keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }
      `}</style>
    </div>
  );
}

function LeadDetail({ lead, isManager, roster, onStatusChange, onNotesChange, onRefresh }: {
  lead: any; isManager: boolean; roster: any[]; onStatusChange: (id: number, s: string) => void;
  onNotesChange: (id: number, n: string) => void; onRefresh: () => void;
}) {
  const [notes, setNotes] = useState(lead.notes || '');
  const [saving, setSaving] = useState(false);
  const phoneDigits = (lead.phone || '').replace(/\D/g, '');

  const saveNotes = async () => {
    setSaving(true);
    await onNotesChange(lead.id, notes);
    setSaving(false);
  };

  const reassign = async (userId: number) => {
    try {
      await axios.patch(`${API}/api/leads/${lead.id}`, { assigned_to_id: userId }, { headers: headers() });
      onRefresh();
    } catch (e) { console.error(e); }
  };

  const detail: React.CSSProperties = {
    padding: '20px', background: 'rgba(255,255,255,0.015)', borderBottom: '1px solid rgba(255,255,255,0.06)',
  };

  const infoRow = (label: string, value: string | undefined) => {
    if (!value) return null;
    return (
      <div style={{ display: 'flex', gap: '8px', fontSize: '13px', padding: '4px 0' }}>
        <span style={{ color: '#64748b', minWidth: '120px' }}>{label}</span>
        <span style={{ color: '#e2e8f0' }}>{value}</span>
      </div>
    );
  };

  return (
    <div style={detail}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        {/* Left: Lead Info */}
        <div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
            Lead Details
          </div>
          {infoRow('Name', lead.name)}
          {infoRow('Phone', lead.phone)}
          {infoRow('Email', lead.email)}
          {infoRow('Address', [lead.address, lead.city, lead.state, lead.zip_code].filter(Boolean).join(', '))}
          {infoRow('Products', lead.policy_types)}
          {infoRow('Current Carrier', lead.current_carrier)}
          {infoRow('Current Premium', lead.current_premium ? `$${lead.current_premium}` : undefined)}
          {infoRow('Source', lead.source)}

          {lead.message && (
            <div style={{ marginTop: '12px', padding: '12px', borderRadius: '8px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#64748b', marginBottom: '4px' }}>DETAILS</div>
              <div style={{ fontSize: '13px', color: '#94a3b8', whiteSpace: 'pre-line', lineHeight: 1.5 }}>{lead.message}</div>
            </div>
          )}

          {/* Quick actions */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
            <a href={`tel:${phoneDigits}`} style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '6px',
              background: '#2563eb', color: '#fff', textDecoration: 'none', fontWeight: 600, fontSize: '13px',
            }}>
              <Phone size={14} /> Call Now
            </a>
            {lead.email && (
              <a href={`mailto:${lead.email}`} style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '6px',
                background: 'rgba(255,255,255,0.06)', color: '#e2e8f0', textDecoration: 'none', fontWeight: 600, fontSize: '13px',
                border: '1px solid rgba(255,255,255,0.08)',
              }}>
                <Mail size={14} /> Email
              </a>
            )}
          </div>
        </div>

        {/* Right: Status + Notes */}
        <div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
            Update Status
          </div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '16px' }}>
            {STATUSES.map(s => {
              const cfg = STATUS_CONFIG[s];
              const active = lead.status === s;
              return (
                <button key={s} onClick={() => onStatusChange(lead.id, s)}
                  style={{
                    padding: '6px 14px', borderRadius: '6px', border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
                    background: active ? cfg.bg : 'rgba(255,255,255,0.04)',
                    color: active ? cfg.color : '#64748b',
                    outline: active ? `1px solid ${cfg.color}` : 'none',
                  }}>
                  {cfg.label}
                </button>
              );
            })}
          </div>

          {/* Reassign (manager only) */}
          {isManager && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
                Reassign
              </div>
              <select
                value={lead.assigned_to_id || ''}
                onChange={e => e.target.value && reassign(Number(e.target.value))}
                style={{
                  width: '100%', padding: '8px 12px', borderRadius: '8px', fontSize: '13px',
                  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0',
                }}
              >
                <option value="">Select agent...</option>
                {roster.map(r => <option key={r.user_id} value={r.user_id}>{r.name}</option>)}
              </select>
            </div>
          )}

          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
            Notes
          </div>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Add notes about this lead..."
            rows={4}
            style={{
              width: '100%', padding: '10px 12px', borderRadius: '8px', fontSize: '13px', resize: 'vertical',
              background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0',
              outline: 'none', boxSizing: 'border-box', fontFamily: 'inherit',
            }}
          />
          <button onClick={saveNotes} disabled={saving}
            style={{
              marginTop: '8px', padding: '6px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer',
              background: 'rgba(255,255,255,0.06)', color: '#94a3b8', fontWeight: 600, fontSize: '12px',
            }}>
            {saving ? 'Saving...' : 'Save Notes'}
          </button>
        </div>
      </div>
    </div>
  );
}
