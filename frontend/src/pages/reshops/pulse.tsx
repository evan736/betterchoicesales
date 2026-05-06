/**
 * Reshop Pulse — daily activity heartbeat for the reshop pipeline.
 *
 * Surfaces 4 categories of attention-needed reshops:
 *   1. Stale          — active reshops past per-stage activity threshold
 *   2. No-touch       — aged with zero attempts logged
 *   3. No-answer      — 3 unanswered attempts, customer never reached
 *   4. At-risk wins   — bound/renewed with zero answered attempts
 *
 * This page replaces the manual cross-system audits Evan was doing
 * by hand (NowCerts + Lightspeed + Missive + ORBIT). Each card shows
 * the customer, stage, assignee, and a "why" explanation.
 *
 * Filtering by assignee surfaces individual producer accountability —
 * useful for 1-on-1 conversations.
 */
import React, { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import Navbar from '../../components/Navbar';
import { reshopAPI } from '../../lib/api';
import { useRouter } from 'next/router';
import {
  AlertTriangle, AlertOctagon, Clock, PhoneOff, RefreshCw, Send,
  CheckCircle2, ExternalLink, Loader2, Filter, Mail,
} from 'lucide-react';
import { toast } from '../../components/ui/Toast';

interface PulseCard {
  id: number;
  customer_name: string;
  carrier: string | null;
  stage: string;
  assigned_to: number | null;
  assignee_name: string | null;
  created_at: string | null;
  expiration_date: string | null;
  days_since_activity: number | null;
  days_since_created: number | null;
  attempt_count: number;
  unanswered_attempts: number;
  has_answered: boolean;
  current_premium: number | null;
  premium_change_pct: number | null;
  why: string;
}

interface PulsePayload {
  as_of: string;
  thresholds: any;
  totals: { stale: number; no_touch: number; no_answer_cycle: number; at_risk_win: number };
  stale: PulseCard[];
  no_touch: PulseCard[];
  no_answer_cycle: PulseCard[];
  at_risk_win: PulseCard[];
}

// Card category metadata — defines color, icon, title, copy
const CATEGORIES = [
  {
    key: 'at_risk_win' as const,
    title: 'At-risk wins',
    subtitle: 'Marked bound/renewed but no answered attempts',
    color: 'red',
    bg: 'bg-red-50',
    border: 'border-red-200',
    text: 'text-red-700',
    badge: 'bg-red-100 text-red-800',
    icon: AlertOctagon,
    severity: 1, // highest
  },
  {
    key: 'no_touch' as const,
    title: 'Untouched',
    subtitle: 'Aged with zero attempts logged',
    color: 'red',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
    text: 'text-orange-700',
    badge: 'bg-orange-100 text-orange-800',
    icon: AlertTriangle,
    severity: 2,
  },
  {
    key: 'stale' as const,
    title: 'Stale',
    subtitle: 'No recent activity past the per-stage threshold',
    color: 'amber',
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    text: 'text-amber-700',
    badge: 'bg-amber-100 text-amber-800',
    icon: Clock,
    severity: 3,
  },
  {
    key: 'no_answer_cycle' as const,
    title: 'Ghosted',
    subtitle: '3 unanswered attempts — customer never reached',
    color: 'slate',
    bg: 'bg-slate-50',
    border: 'border-slate-200',
    text: 'text-slate-700',
    badge: 'bg-slate-100 text-slate-800',
    icon: PhoneOff,
    severity: 4,
  },
];

export default function ReshopPulsePage() {
  const router = useRouter();
  const { user } = useAuth();
  const [data, setData] = useState<PulsePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [assigneeFilter, setAssigneeFilter] = useState<number | ''>('');
  const [teamMembers, setTeamMembers] = useState<any[]>([]);
  const [sendingDigest, setSendingDigest] = useState(false);

  useEffect(() => {
    loadPulse();
    loadTeam();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadPulse();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigneeFilter]);

  const loadPulse = async () => {
    setRefreshing(true);
    try {
      const res = await reshopAPI.pulse({
        assignee_id: assigneeFilter === '' ? undefined : assigneeFilter,
      });
      setData(res.data);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to load Pulse');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadTeam = async () => {
    try {
      const res = await reshopAPI.teamMembers();
      setTeamMembers(res.data.members || res.data || []);
    } catch { /* non-fatal */ }
  };

  const sendTestDigest = async () => {
    if (!confirm('Send the Pulse digest email now? (sends to your account)')) return;
    setSendingDigest(true);
    try {
      const res = await reshopAPI.sendPulseDigest(user?.email);
      if (res.data.sent) {
        toast.success(`Digest sent to ${res.data.to}`);
      } else {
        toast.error(res.data.error || 'Send failed');
      }
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Send failed');
    } finally {
      setSendingDigest(false);
    }
  };

  const grandTotal = data
    ? data.totals.stale + data.totals.no_touch + data.totals.no_answer_cycle + data.totals.at_risk_win
    : 0;

  if (loading) {
    return (
      <>
        <Navbar />
        <div className="min-h-screen bg-slate-50 flex items-center justify-center">
          <Loader2 className="animate-spin text-slate-400" size={32} />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <div className="min-h-screen bg-slate-50 p-6">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-2xl font-bold text-slate-900">Reshop Pulse</h1>
                {grandTotal === 0 ? (
                  <span className="bg-emerald-100 text-emerald-800 text-xs font-bold px-2.5 py-1 rounded-full flex items-center gap-1">
                    <CheckCircle2 size={12} /> All clear
                  </span>
                ) : (
                  <span className="bg-red-100 text-red-800 text-xs font-bold px-2.5 py-1 rounded-full">
                    {grandTotal} need{grandTotal === 1 ? 's' : ''} attention
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-600">
                Daily activity heartbeat — stale, untouched, and at-risk-win reshops.
                Auto-emailed to {user?.role === 'admin' ? 'you' : 'admin'} at 8 AM CT M-F.
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {/* Assignee filter */}
              <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-lg px-3 py-2">
                <Filter size={14} className="text-slate-400" />
                <select
                  value={assigneeFilter}
                  onChange={(e) => setAssigneeFilter(e.target.value === '' ? '' : Number(e.target.value))}
                  className="text-sm bg-transparent focus:outline-none"
                >
                  <option value="">All assignees</option>
                  {teamMembers.map((m: any) => (
                    <option key={m.id} value={m.id}>
                      {m.full_name || m.username}
                    </option>
                  ))}
                </select>
              </div>
              {/* Refresh */}
              <button
                onClick={loadPulse}
                disabled={refreshing}
                className="bg-white hover:bg-slate-50 border border-slate-200 text-slate-700 text-sm font-semibold px-3 py-2 rounded-lg flex items-center gap-2 disabled:opacity-50"
              >
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                Refresh
              </button>
              {/* Test digest send (admin only) */}
              {user?.role === 'admin' && (
                <button
                  onClick={sendTestDigest}
                  disabled={sendingDigest}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-3 py-2 rounded-lg flex items-center gap-2 disabled:opacity-50"
                  title="Send the Pulse digest email to yourself now (test the formatting)"
                >
                  <Mail size={14} />
                  {sendingDigest ? 'Sending…' : 'Send digest now'}
                </button>
              )}
            </div>
          </div>

          {/* Summary tiles */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {CATEGORIES.map((cat) => {
              const count = data?.totals[cat.key] || 0;
              const Icon = cat.icon;
              return (
                <div
                  key={cat.key}
                  className={`${cat.bg} ${cat.border} border rounded-xl p-4`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <Icon size={18} className={cat.text} />
                    <span className={`text-xs font-bold uppercase tracking-wider ${cat.text}`}>
                      {cat.title}
                    </span>
                  </div>
                  <div className={`text-3xl font-bold ${count > 0 ? cat.text : 'text-slate-400'}`}>
                    {count}
                  </div>
                  <div className="text-xs text-slate-600 mt-1">{cat.subtitle}</div>
                </div>
              );
            })}
          </div>

          {/* All-clear banner */}
          {grandTotal === 0 && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-8 text-center">
              <CheckCircle2 size={48} className="text-emerald-600 mx-auto mb-3" />
              <h2 className="text-lg font-bold text-emerald-900 mb-1">Pipeline is healthy</h2>
              <p className="text-sm text-emerald-700">
                No stale, untouched, or at-risk reshops right now.
                {assigneeFilter && ' (Filtered to selected assignee.)'}
              </p>
            </div>
          )}

          {/* Category lists */}
          {CATEGORIES.filter((cat) => (data?.[cat.key]?.length || 0) > 0).map((cat) => {
            const cards = data![cat.key] as PulseCard[];
            const Icon = cat.icon;
            return (
              <div key={cat.key} className="mb-6">
                <div className="flex items-center gap-2 mb-3">
                  <Icon size={18} className={cat.text} />
                  <h2 className={`text-base font-bold ${cat.text}`}>
                    {cat.title}
                  </h2>
                  <span className={`text-xs font-bold ${cat.badge} px-2 py-0.5 rounded-full`}>
                    {cards.length}
                  </span>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                  {cards.map((card, idx) => (
                    <PulseRow
                      key={`${cat.key}-${card.id}`}
                      card={card}
                      isLast={idx === cards.length - 1}
                      onClick={() => router.push(`/reshop?id=${card.id}`)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ─── PulseRow ────────────────────────────────────────────────────
// Individual reshop card. Renders compact info + the "why" badge.
// Click navigates to the full reshop kanban with this card focused.
const PulseRow: React.FC<{ card: PulseCard; isLast: boolean; onClick: () => void }> = ({
  card, isLast, onClick,
}) => {
  return (
    <div
      onClick={onClick}
      className={`px-4 py-3 hover:bg-slate-50 cursor-pointer flex items-center gap-3 ${
        !isLast ? 'border-b border-slate-100' : ''
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-slate-900 text-sm">{card.customer_name}</span>
          {card.carrier && (
            <span className="text-xs text-slate-500">· {card.carrier}</span>
          )}
          <span className="text-xs bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-medium">
            {card.stage}
          </span>
          {card.assignee_name && (
            <span className="text-xs text-slate-500">→ {card.assignee_name}</span>
          )}
        </div>
        <div className="text-xs text-slate-600 mt-1">{card.why}</div>
      </div>
      {/* Compact stat column */}
      <div className="flex items-center gap-3 text-xs text-slate-500 shrink-0">
        {card.attempt_count > 0 && (
          <span title="Attempts logged">
            {card.attempt_count}/{3} tries
            {card.has_answered ? ' ✓' : ''}
          </span>
        )}
        {card.current_premium && (
          <span className="font-mono">${card.current_premium.toLocaleString()}</span>
        )}
      </div>
      <ExternalLink size={14} className="text-slate-300 shrink-0" />
    </div>
  );
};
