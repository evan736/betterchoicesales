import React, { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { retentionAPI, nonpayAPI, customersAPI } from '../lib/api';
import {
  Shield,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Users,
  FileText,
  RefreshCw,
  ChevronDown,
  ExternalLink,
  Mail,
  Phone,
  DollarSign,
  Clock,
  Activity,
  Filter,
  ArrowUpRight,
  ArrowDownRight,
  Zap,
  Target,
  BarChart2,
  Send,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
  PieChart,
  Pie,
} from 'recharts';
import { toast } from '../components/ui/Toast';

// ── Helper Components ──
interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
  icon?: React.ReactNode;
  trend?: 'up' | 'down' | null;
}

function StatCard({ label, value, sub, color = '#00e5c7', icon, trend }: StatCardProps) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
      <div
        className="absolute -top-5 -right-5 h-20 w-20 rounded-full"
        style={{ background: `radial-gradient(circle, ${color}15, transparent)` }}
      />
      {icon && (
        <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: `${color}15` }}>
          {icon}
        </div>
      )}
      <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 font-mono">{label}</div>
      <div className="mt-1 text-3xl font-bold font-display" style={{ color }}>
        {value}
        {trend && (
          <span className="ml-2 inline-flex items-center text-sm">
            {trend === 'up' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
          </span>
        )}
      </div>
      {sub && <div className="mt-1 text-[11px] text-slate-600 font-mono">{sub}</div>}
    </div>
  );
}

function Badge({ children, color = '#00e5c7' }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="inline-block rounded-full px-2.5 py-0.5 text-[10px] font-semibold font-mono tracking-wide"
      style={{
        background: `${color}18`,
        color,
        border: `1px solid ${color}30`,
      }}
    >
      {children}
    </span>
  );
}

function ProgressBar({ value, max = 100, color = '#00e5c7' }: { value: number; max?: number; color?: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
      <div
        className="h-full rounded-full transition-all duration-700"
        style={{
          width: `${pct}%`,
          background: `linear-gradient(90deg, ${color}, ${color}cc)`,
          boxShadow: `0 0 12px ${color}40`,
        }}
      />
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-[0.15em] text-slate-500 font-mono">{children}</h3>
  );
}

// ── Tab: Overview ──
function OverviewTab({
  overview,
  byCarrier,
  byAgent,
  trend,
  bySource,
}: {
  overview: any;
  byCarrier: any[];
  byAgent: any[];
  trend: any[];
  bySource: any[];
}) {
  const bucketData = overview?.cancellation_buckets
    ? Object.entries(overview.cancellation_buckets).map(([name, count]) => ({
        name: name + 'd',
        count: count as number,
      }))
    : [];

  const bucketColors = ['#ff4757', '#ff6b81', '#ffa502', '#00e5c7', '#2ed573'];

  const rateColor = (r: number) => (r >= 98 ? '#2ed573' : r >= 95 ? '#00e5c7' : r >= 90 ? '#ffa502' : '#ff4757');

  return (
    <div className="flex flex-col gap-5">
      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="Total Policies"
          value={overview?.total_sales?.toLocaleString() || '—'}
          sub="All time tracked"
          icon={<FileText size={16} color="#00e5c7" />}
        />
        <StatCard
          label="Active"
          value={overview?.total_active?.toLocaleString() || '—'}
          sub={overview ? `${((overview.total_active / overview.total_sales) * 100).toFixed(1)}% of total` : ''}
          color="#2ed573"
          icon={<Shield size={16} color="#2ed573" />}
        />
        <StatCard
          label="Cancelled"
          value={overview?.total_cancelled || '—'}
          sub="Across all carriers"
          color="#ff4757"
          icon={<AlertTriangle size={16} color="#ff4757" />}
        />
        <StatCard
          label="Retention Rate"
          value={overview ? `${overview.retention_rate}%` : '—'}
          sub="Agency-wide"
          color={overview ? rateColor(overview.retention_rate) : '#00e5c7'}
          icon={<Target size={16} color={overview ? rateColor(overview.retention_rate) : '#00e5c7'} />}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-5 gap-4">
        {/* Retention Trend — wider */}
        <div className="col-span-3 rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
          <SectionHeader>Retention Trend</SectionHeader>
          <div className="mt-3">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={trend}>
                <defs>
                  <linearGradient id="retGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00e5c7" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#00e5c7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#4a6280' }} axisLine={false} tickLine={false} />
                <YAxis
                  domain={[88, 101]}
                  tick={{ fontSize: 10, fill: '#4a6280' }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => `${v}%`}
                />
                <Tooltip
                  contentStyle={{
                    background: '#0a1224',
                    border: '1px solid rgba(0,229,199,0.2)',
                    borderRadius: 10,
                    fontSize: 12,
                    color: '#c5d4e8',
                  }}
                  formatter={(v: number) => [`${v}%`, 'Retention']}
                />
                <Area
                  type="monotone"
                  dataKey="retention_rate"
                  stroke="#00e5c7"
                  strokeWidth={2.5}
                  fill="url(#retGrad)"
                  dot={{ r: 4, fill: '#00e5c7', strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cancellation Timing */}
        <div className="col-span-2 rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
          <SectionHeader>Cancellation Timing</SectionHeader>
          <div className="mt-3">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={bucketData} barSize={28}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#4a6280' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: '#4a6280' }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    background: '#0a1224',
                    border: '1px solid rgba(0,229,199,0.2)',
                    borderRadius: 10,
                    fontSize: 12,
                    color: '#c5d4e8',
                  }}
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {bucketData?.map((_, i) => (
                    <Cell key={i} fill={bucketColors[i % bucketColors.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Carrier + Agent Tables */}
      <div className="grid grid-cols-2 gap-4">
        {/* By Carrier */}
        <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
          <SectionHeader>Retention by Carrier</SectionHeader>
          <div className="mt-4 flex flex-col gap-3">
            {byCarrier?.map((c: any) => (
              <div key={c.carrier} className="flex items-center gap-3">
                <div className="w-32 truncate text-xs text-slate-300 font-display">{c.carrier}</div>
                <div className="flex-1">
                  <ProgressBar value={c.retention_rate} color={rateColor(c.retention_rate)} />
                </div>
                <div className="w-12 text-right text-xs font-mono" style={{ color: rateColor(c.retention_rate) }}>
                  {c.retention_rate}%
                </div>
                <div className="w-8 text-right text-[11px] font-mono text-red-400">
                  {c.cancelled > 0 ? `-${c.cancelled}` : '—'}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* By Agent */}
        <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
          <SectionHeader>Retention by Producer</SectionHeader>
          <div className="mt-4 flex flex-col gap-3.5">
            {byAgent
              .filter((a: any) => a.agent_name !== 'System Administrator')
              .map((a: any) => (
                <div key={a.agent_name}>
                  <div className="mb-1.5 flex items-baseline justify-between">
                    <span className="text-xs text-slate-300 font-display">{a.agent_name}</span>
                    <span className="text-xs font-mono" style={{ color: rateColor(a.retention_rate) }}>
                      {a.retention_rate}%{' '}
                      <span className="text-[10px] text-slate-600">
                        ({a.total_sales} sold / {a.cancelled} lost)
                      </span>
                    </span>
                  </div>
                  <ProgressBar value={a.retention_rate} color={rateColor(a.retention_rate)} />
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* By Lead Source */}
      <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
        <SectionHeader>Retention by Lead Source</SectionHeader>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {bySource
            .filter((s: any) => s.total_sales >= 10)
            .sort((a: any, b: any) => a.retention_rate - b.retention_rate)
            .map((s: any) => (
              <div key={s.lead_source} className="flex items-center gap-3 rounded-lg border border-white/3 p-3">
                <div className="flex-1">
                  <div className="text-xs text-slate-300 font-display capitalize">
                    {s.lead_source.replace(/_/g, ' ')}
                  </div>
                  <div className="mt-1 text-[10px] text-slate-600 font-mono">
                    {s.total_sales} sold · {s.cancelled} lost
                  </div>
                </div>
                <div className="text-sm font-bold font-mono" style={{ color: rateColor(s.retention_rate) }}>
                  {s.retention_rate}%
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

// ── Tab: Cancellations ──
function CancellationsTab({ cancellations }: { cancellations: any[] }) {
  const [sortBy, setSortBy] = useState('days_to_cancel');
  const [filterCarrier, setFilterCarrier] = useState('All');

  const carriers = ['All', ...Array.from(new Set(cancellations.map((c: any) => c.carrier)))];

  const filtered = useMemo(() => {
    let data = [...cancellations];
    if (filterCarrier !== 'All') data = data.filter((c: any) => c.carrier === filterCarrier);
    data.sort((a: any, b: any) => {
      if (sortBy === 'days_to_cancel') return a.days_to_cancel - b.days_to_cancel;
      if (sortBy === 'written_premium') return b.written_premium - a.written_premium;
      return 0;
    });
    return data;
  }, [cancellations, sortBy, filterCarrier]);

  const totalLostPremium = filtered.reduce((s: number, c: any) => s + (c.written_premium || 0), 0);

  const carrierColor = (carrier: string) => {
    const colors: Record<string, string> = {
      'National General': '#ffa502',
      'Progressive Insurance': '#3742fa',
      'Progressive': '#3742fa',
      Grange: '#2ed573',
      Travelers: '#ff6348',
      Safeco: '#1a3054',
      'Bristol West': '#003B8E',
    };
    return colors[carrier] || '#00e5c7';
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Summary + Filters */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-5">
          <div>
            <span className="text-2xl font-bold text-red-400 font-display">
              ${totalLostPremium.toLocaleString()}
            </span>
            <span className="ml-2 text-xs text-slate-600 font-mono">
              lost premium ({filtered.length} policies)
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <select
            value={filterCarrier}
            onChange={(e) => setFilterCarrier(e.target.value)}
            className="rounded-lg border border-cyan-500/20 bg-[#0a1224] px-3 py-2 text-xs text-slate-300 font-mono focus:outline-none"
          >
            {carriers.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="rounded-lg border border-cyan-500/20 bg-[#0a1224] px-3 py-2 text-xs text-slate-300 font-mono focus:outline-none"
          >
            <option value="days_to_cancel">Sort: Days to Cancel</option>
            <option value="written_premium">Sort: Premium</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/5">
              {['Client', 'Policy #', 'Carrier', 'Producer', 'Premium', 'Effective', 'Cancelled', 'Days', 'Status'].map(
                (h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-600 font-mono"
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((c: any, i: number) => (
              <tr
                key={c.id || i}
                className="border-b border-white/[0.02] transition-colors hover:bg-cyan-500/[0.03]"
              >
                <td className="px-4 py-3 text-xs font-medium text-slate-200 font-display">{c.client_name}</td>
                <td className="px-4 py-3 text-[11px] text-slate-500 font-mono">{c.policy_number}</td>
                <td className="px-4 py-3">
                  <Badge color={carrierColor(c.carrier)}>{c.carrier}</Badge>
                </td>
                <td className="px-4 py-3 text-xs text-slate-300 font-display">{c.producer}</td>
                <td className="px-4 py-3 text-xs font-semibold text-red-400 font-mono">
                  ${(c.written_premium || 0).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-[11px] text-slate-500 font-mono">{c.effective_date}</td>
                <td className="px-4 py-3 text-[11px] text-slate-500 font-mono">{c.cancelled_date}</td>
                <td className="px-4 py-3">
                  <Badge
                    color={c.days_to_cancel <= 7 ? '#ff4757' : c.days_to_cancel <= 30 ? '#ffa502' : '#4a6280'}
                  >
                    {c.days_to_cancel}d
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  <Badge color={c.commission_status === 'paid' ? '#ffa502' : '#2ed573'}>
                    {c.commission_status === 'paid' ? 'COMM PAID' : 'CLAWED'}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="py-12 text-center text-sm text-slate-600 font-mono">No cancellations found</div>
        )}
      </div>
    </div>
  );
}

// ── Tab: Non-Pay ──
function NonPayTab({ nonpayEmails, nonpayHistory }: { nonpayEmails: any[]; nonpayHistory: any[] }) {
  const totalSent = nonpayEmails.length;
  const thisWeek = nonpayEmails.filter((e: any) => {
    const sent = new Date(e.sent_at);
    const now = new Date();
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    return sent >= weekAgo;
  }).length;

  const avgAmount =
    nonpayEmails.length > 0
      ? nonpayEmails.reduce((s: number, e: any) => s + (e.amount_due || 0), 0) / nonpayEmails.length
      : 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Non-Pay Notices Sent"
          value={totalSent}
          sub="All time (NatGen automated)"
          color="#ffa502"
          icon={<Mail size={16} color="#ffa502" />}
        />
        <StatCard
          label="This Week"
          value={thisWeek}
          sub="Last 7 days"
          color="#00e5c7"
          icon={<Send size={16} color="#00e5c7" />}
        />
        <StatCard
          label="Avg Amount Due"
          value={`$${Math.round(avgAmount).toLocaleString()}`}
          sub="Across all notices"
          color="#ff6348"
          icon={<DollarSign size={16} color="#ff6348" />}
        />
      </div>

      {/* Recent Notices */}
      <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
        <div className="flex items-center justify-between">
          <SectionHeader>Recent Non-Pay Notices</SectionHeader>
          <Badge color="#2ed573">LIVE — AUTO</Badge>
        </div>
        <div className="mt-4 flex flex-col">
          {nonpayEmails.slice(0, 8).map((n: any, i: number) => (
            <div
              key={n.id || i}
              className="grid grid-cols-5 items-center border-b border-white/[0.02] py-3"
              style={{ gridTemplateColumns: '1.5fr 1fr 0.8fr 0.8fr 0.5fr' }}
            >
              <div>
                <div className="text-xs font-medium text-slate-200 font-display">{n.customer_name}</div>
                <div className="text-[10px] text-slate-600 font-mono">{n.policy_number}</div>
              </div>
              <div className="text-[11px] text-slate-500 font-mono">{n.carrier || 'National General'}</div>
              <div className="text-xs font-semibold text-orange-400 font-mono">
                ${typeof n.amount_due === 'number' ? n.amount_due.toLocaleString() : n.amount_due}
              </div>
              <div className="text-[11px] text-slate-500 font-mono">Due {n.due_date}</div>
              <div>
                <Badge color={n.email_status === 'sent' ? '#2ed573' : '#ffa502'}>
                  {(n.email_status || 'sent').toUpperCase()}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Carrier Automation Status */}
      <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
        <SectionHeader>Carrier Automation Status</SectionHeader>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {[
            {
              carrier: 'National General',
              status: 'live',
              type: 'Non-Pay + UW + Non-Renewal',
              method: 'Email parsing → auto-send',
            },
            {
              carrier: 'Grange',
              status: 'building',
              type: 'Non-Renewal Notices',
              method: 'GrangeWire email parsing',
            },
            {
              carrier: 'Progressive',
              status: 'manual',
              type: 'Manual Upload',
              method: 'CSV upload → review → send',
            },
            {
              carrier: 'Travelers',
              status: 'manual',
              type: 'Manual Upload',
              method: 'CSV upload → review → send',
            },
            {
              carrier: 'Safeco',
              status: 'manual',
              type: 'Manual Upload',
              method: 'CSV upload → review → send',
            },
            {
              carrier: 'Bristol West',
              status: 'manual',
              type: 'Manual Upload',
              method: 'CSV upload → review → send',
            },
          ].map((c) => (
            <div
              key={c.carrier}
              className="rounded-lg border p-4"
              style={{
                borderColor:
                  c.status === 'live'
                    ? 'rgba(46,213,115,0.3)'
                    : c.status === 'building'
                    ? 'rgba(255,165,2,0.3)'
                    : 'rgba(255,255,255,0.06)',
                background: c.status === 'live' ? 'rgba(46,213,115,0.04)' : 'transparent',
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-200 font-display">{c.carrier}</span>
                <Badge
                  color={c.status === 'live' ? '#2ed573' : c.status === 'building' ? '#ffa502' : '#4a6280'}
                >
                  {c.status.toUpperCase()}
                </Badge>
              </div>
              <div className="mt-2 text-[10px] leading-relaxed text-slate-500 font-mono">
                {c.type}
                <br />
                {c.method}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Upload History */}
      {nonpayHistory.length > 0 && (
        <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
          <SectionHeader>Processing History</SectionHeader>
          <div className="mt-4 flex flex-col">
            {nonpayHistory.slice(0, 5).map((h: any, i: number) => (
              <div key={h.id || i} className="flex items-center justify-between border-b border-white/[0.02] py-3">
                <div>
                  <div className="text-xs text-slate-300 font-display">{h.filename}</div>
                  <div className="text-[10px] text-slate-600 font-mono">{h.uploaded_by}</div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-[11px] text-slate-500 font-mono">
                    {h.policies_found} found · {h.emails_sent} sent
                  </div>
                  <Badge color={h.status === 'complete' ? '#2ed573' : h.status === 'dry_run' ? '#ffa502' : '#4a6280'}>
                    {h.status?.toUpperCase()}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab: Re-Shop ──
function ReShopTab({ cancellations }: { cancellations: any[] }) {
  const candidates = cancellations.filter((c: any) => c.days_to_cancel <= 30);
  const totalRecovery = candidates.reduce((s: number, c: any) => s + (c.written_premium || 0), 0);

  return (
    <div className="flex flex-col gap-5">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Re-Shop Candidates"
          value={candidates.length}
          sub="Cancelled within 30 days"
          color="#3742fa"
          icon={<RefreshCw size={16} color="#3742fa" />}
        />
        <StatCard
          label="Potential Recovery"
          value={`$${totalRecovery.toLocaleString()}`}
          sub="Lost premium to win back"
          color="#2ed573"
          icon={<DollarSign size={16} color="#2ed573" />}
        />
        <StatCard
          label="Winback Campaigns"
          value="0"
          sub="Create your first campaign"
          color="#ffa502"
          icon={<Target size={16} color="#ffa502" />}
        />
      </div>

      {/* Candidates List */}
      <div className="rounded-xl border border-white/5 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-5">
        <div className="flex items-center justify-between">
          <SectionHeader>Re-Shop Candidates</SectionHeader>
          <button className="rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-xs font-bold text-[#0a1224] font-display shadow-lg shadow-cyan-500/20 transition hover:shadow-cyan-500/30">
            + Create Winback Campaign
          </button>
        </div>
        <div className="mt-4 flex flex-col gap-2">
          {candidates.map((c: any) => (
            <div
              key={c.id}
              className="grid items-center gap-3 rounded-lg border border-white/[0.04] bg-white/[0.01] p-3"
              style={{ gridTemplateColumns: '1.5fr 1fr 1fr 0.7fr 0.8fr 0.5fr' }}
            >
              <div>
                <div className="text-xs font-medium text-slate-200 font-display">{c.client_name}</div>
                <div className="text-[10px] text-slate-600 font-mono">{c.policy_number}</div>
              </div>
              <div className="text-xs text-slate-500">{c.carrier}</div>
              <div className="text-xs text-slate-500">{c.producer}</div>
              <div className="text-xs font-semibold text-red-400 font-mono">
                ${(c.written_premium || 0).toLocaleString()}
              </div>
              <Badge color="#ff4757">{c.days_to_cancel}d to cancel</Badge>
              <button className="rounded-md border border-indigo-500/30 bg-indigo-500/10 px-3 py-1.5 text-[10px] font-semibold text-indigo-400 font-mono transition hover:bg-indigo-500/20">
                Re-Shop
              </button>
            </div>
          ))}
          {candidates.length === 0 && (
            <div className="py-8 text-center text-sm text-slate-600 font-mono">No re-shop candidates</div>
          )}
        </div>
      </div>

      {/* Workflow */}
      <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-br from-[#0a1224]/95 to-[#0f1932]/90 p-6">
        <SectionHeader>Re-Shop Workflow</SectionHeader>
        <div className="mt-5 grid grid-cols-4 gap-6">
          {[
            { step: '1', title: 'Identify', desc: 'Auto-detect early cancellations & non-renewals' },
            { step: '2', title: 'Queue', desc: 'Producer assigned re-shop task with customer context' },
            { step: '3', title: 'Quote', desc: 'Agent re-quotes with alternate carriers' },
            { step: '4', title: 'Win Back', desc: 'Customer re-bound, retention preserved' },
          ].map((s) => (
            <div key={s.step} className="text-center">
              <div className="mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-indigo-600 text-base font-bold text-white shadow-lg shadow-indigo-500/30 font-display">
                {s.step}
              </div>
              <div className="text-sm font-semibold text-slate-200 font-display">{s.title}</div>
              <div className="mt-1 text-[10px] leading-relaxed text-slate-600 font-mono">{s.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Growth Tab ──
function GrowthTab({ data }: { data: any }) {
  const [capturing, setCapturing] = useState(false);

  const handleCapture = async () => {
    setCapturing(true);
    try {
      await customersAPI.captureSnapshot();
      window.location.reload();
    } catch (e) {
      toast.error('Failed to capture snapshot');
    } finally {
      setCapturing(false);
    }
  };

  const summary = data?.growth_summary || [];
  const snapshots = data?.snapshots || [];

  // Format for charts
  const chartData = summary.map((s: any) => ({
    ...s,
    label: s.period,
    premium_k: Math.round((s.active_premium || 0) / 1000),
  }));

  const latest = summary.length > 0 ? summary[summary.length - 1] : null;
  const prev = summary.length > 1 ? summary[summary.length - 2] : null;

  const fmtNum = (n: number) => n?.toLocaleString() ?? '—';
  const fmtMoney = (n: number) => n != null ? `$${Math.round(n).toLocaleString()}` : '—';
  const fmtPct = (n: number) => n != null ? `${n > 0 ? '+' : ''}${n}%` : '—';
  const changeColor = (n: number) => n > 0 ? 'text-emerald-400' : n < 0 ? 'text-red-400' : 'text-slate-400';

  return (
    <div className="space-y-6">
      {/* Header + Capture Button */}
      <div className="flex items-center justify-between">
        <SectionHeader>Agency Growth</SectionHeader>
        <button
          onClick={handleCapture}
          disabled={capturing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-cyan-600/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-600/30 transition-colors disabled:opacity-50"
        >
          {capturing ? <RefreshCw size={12} className="animate-spin" /> : <Activity size={12} />}
          Capture Snapshot
        </button>
      </div>

      {snapshots.length === 0 ? (
        <div className="text-center py-16">
          <Activity size={40} className="mx-auto text-slate-600 mb-4" />
          <p className="text-slate-400 text-sm">No growth data yet.</p>
          <p className="text-slate-500 text-xs mt-1">Click "Capture Snapshot" to start tracking, or wait for the daily auto-capture.</p>
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          {latest && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-mono mb-1">Active Customers</div>
                <div className="text-2xl font-bold text-slate-100">{fmtNum(latest.active_customers)}</div>
                {latest.customer_change != null && (
                  <div className={`text-xs mt-1 ${changeColor(latest.customer_change)}`}>
                    {latest.customer_change > 0 ? '↑' : latest.customer_change < 0 ? '↓' : '→'} {fmtNum(Math.abs(latest.customer_change))} MoM ({fmtPct(latest.customer_change_pct)})
                  </div>
                )}
                {latest.yoy_customer_change != null && (
                  <div className={`text-[10px] mt-0.5 ${changeColor(latest.yoy_customer_change)}`}>
                    YoY: {latest.yoy_customer_change > 0 ? '+' : ''}{fmtNum(latest.yoy_customer_change)} ({fmtPct(latest.yoy_customer_pct)})
                  </div>
                )}
              </div>
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-mono mb-1">Active Premium</div>
                <div className="text-2xl font-bold text-slate-100">{fmtMoney(latest.active_premium)}</div>
                {latest.premium_change != null && (
                  <div className={`text-xs mt-1 ${changeColor(latest.premium_change)}`}>
                    {latest.premium_change > 0 ? '↑' : '↓'} {fmtMoney(Math.abs(latest.premium_change))} MoM ({fmtPct(latest.premium_change_pct)})
                  </div>
                )}
                {latest.yoy_premium_change != null && (
                  <div className={`text-[10px] mt-0.5 ${changeColor(latest.yoy_premium_change)}`}>
                    YoY: {latest.yoy_premium_change > 0 ? '+' : ''}{fmtMoney(Math.abs(latest.yoy_premium_change))} ({fmtPct(latest.yoy_premium_pct)})
                  </div>
                )}
              </div>
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-mono mb-1">Active Policies</div>
                <div className="text-2xl font-bold text-slate-100">{fmtNum(latest.active_policies)}</div>
              </div>
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-mono mb-1">New Sales (Month)</div>
                <div className="text-2xl font-bold text-emerald-400">{fmtNum(latest.new_sales)}</div>
                <div className="text-xs text-slate-400 mt-1">{fmtMoney(latest.new_sales_premium)} premium</div>
              </div>
            </div>
          )}

          {/* Customer Growth Chart */}
          {chartData.length > 1 && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-5">
              <h4 className="text-sm font-semibold text-slate-300 mb-4">Active Customers Over Time</h4>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="custGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }}
                    labelStyle={{ color: '#94a3b8' }}
                    itemStyle={{ color: '#06b6d4' }}
                  />
                  <Area type="monotone" dataKey="active_customers" stroke="#06b6d4" fill="url(#custGrad)" strokeWidth={2} name="Active Customers" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Premium Growth Chart */}
          {chartData.length > 1 && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-5">
              <h4 className="text-sm font-semibold text-slate-300 mb-4">Annualized Premium Over Time</h4>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="premGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }}
                    labelStyle={{ color: '#94a3b8' }}
                    formatter={(v: number) => [`$${v.toLocaleString()}`, 'Premium']}
                  />
                  <Area type="monotone" dataKey="active_premium" stroke="#10b981" fill="url(#premGrad)" strokeWidth={2} name="Premium" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Growth Table */}
          {summary.length > 0 && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] overflow-hidden">
              <div className="px-4 py-3 border-b border-white/[0.06]">
                <h4 className="text-sm font-semibold text-slate-300">Month-Over-Month Summary</h4>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-slate-500 uppercase tracking-wider">
                      <th className="px-4 py-2 text-left font-mono">Period</th>
                      <th className="px-4 py-2 text-right font-mono">Customers</th>
                      <th className="px-4 py-2 text-right font-mono">MoM Δ</th>
                      <th className="px-4 py-2 text-right font-mono">Premium</th>
                      <th className="px-4 py-2 text-right font-mono">MoM Δ</th>
                      <th className="px-4 py-2 text-right font-mono">Policies</th>
                      <th className="px-4 py-2 text-right font-mono">New Sales</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...summary].reverse().map((s: any, i: number) => (
                      <tr key={s.period} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                        <td className="px-4 py-2 text-slate-300 font-mono">{s.period}</td>
                        <td className="px-4 py-2 text-right text-slate-200">{fmtNum(s.active_customers)}</td>
                        <td className={`px-4 py-2 text-right ${changeColor(s.customer_change)}`}>
                          {s.customer_change != null ? `${s.customer_change > 0 ? '+' : ''}${s.customer_change}` : '—'}
                        </td>
                        <td className="px-4 py-2 text-right text-slate-200">{fmtMoney(s.active_premium)}</td>
                        <td className={`px-4 py-2 text-right ${changeColor(s.premium_change)}`}>
                          {s.premium_change != null ? `${s.premium_change > 0 ? '+' : ''}${fmtMoney(Math.abs(s.premium_change))}` : '—'}
                        </td>
                        <td className="px-4 py-2 text-right text-slate-200">{fmtNum(s.active_policies)}</td>
                        <td className="px-4 py-2 text-right text-emerald-400">{s.new_sales || 0}</td>
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
}

// ── Main Page ──
const TABS = ['Overview', 'Growth', 'Cancellations', 'Non-Pay', 'Re-Shop'] as const;
type TabType = (typeof TABS)[number];

export default function RetentionPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabType>('Overview');
  const [loading, setLoading] = useState(true);

  // Data
  const [overview, setOverview] = useState<any>(null);
  const [byCarrier, setByCarrier] = useState<any[]>([]);
  const [byAgent, setByAgent] = useState<any[]>([]);
  const [bySource, setBySource] = useState<any[]>([]);
  const [trend, setTrend] = useState<any[]>([]);
  const [cancellations, setCancellations] = useState<any[]>([]);
  const [nonpayEmails, setNonpayEmails] = useState<any[]>([]);
  const [nonpayHistory, setNonpayHistory] = useState<any[]>([]);
  const [growthData, setGrowthData] = useState<any>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.push('/login');
      return;
    }
    fetchData();
  }, [user, authLoading]);

  // SSE live refresh
  useEffect(() => {
    if (!user) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${baseUrl}/api/events/stream`);
      es.addEventListener('customers:updated', () => fetchData());
      es.addEventListener('dashboard:refresh', () => fetchData());
      es.onerror = () => es?.close();
    } catch {}
    return () => es?.close();
  }, [user]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [ovRes, carrierRes, agentRes, sourceRes, trendRes, cancelRes, npEmailRes, npHistRes, growthRes] =
        await Promise.allSettled([
          retentionAPI.overview(),
          retentionAPI.byCarrier(),
          retentionAPI.byAgent(),
          retentionAPI.bySource(),
          retentionAPI.trend(12),
          retentionAPI.earlyCancellations(120),
          nonpayAPI.emails(),
          nonpayAPI.history(10),
          customersAPI.growthData(),
        ]);

      if (ovRes.status === 'fulfilled') setOverview(ovRes.value.data);
      if (carrierRes.status === 'fulfilled') setByCarrier(carrierRes.value.data);
      if (agentRes.status === 'fulfilled') setByAgent(agentRes.value.data);
      if (sourceRes.status === 'fulfilled') setBySource(sourceRes.value.data);
      if (trendRes.status === 'fulfilled') setTrend(trendRes.value.data);
      if (cancelRes.status === 'fulfilled') setCancellations(cancelRes.value.data);
      if (npEmailRes.status === 'fulfilled') {
        const emailData = npEmailRes.value.data;
        setNonpayEmails(Array.isArray(emailData) ? emailData : emailData.emails || []);
      }
      if (npHistRes.status === 'fulfilled') {
        const histData = npHistRes.value.data;
        setNonpayHistory(Array.isArray(histData) ? histData : histData.notices || []);
      }
      if (growthRes.status === 'fulfilled') setGrowthData(growthRes.value.data);
    } catch (err) {
      console.error('Failed to load retention data:', err);
    } finally {
      setLoading(false);
    }
  };

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-[#050b18]">
      <Navbar />
      <div className="mx-auto max-w-[1600px] px-6 py-6">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.25em] text-cyan-400 font-mono">
              ORBIT • Policy Lifecycle
            </div>
            <h1 className="mt-1 text-2xl font-bold text-slate-100 font-display">Retention Command Center</h1>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-400 shadow-lg shadow-emerald-400/50" />
              <span className="text-xs text-emerald-400 font-mono">Systems Active</span>
            </div>
            <button
              onClick={fetchData}
              className="flex items-center gap-1.5 rounded-lg border border-cyan-500/20 px-3 py-1.5 text-xs text-cyan-400 transition hover:bg-cyan-500/10 font-mono"
            >
              <RefreshCw size={12} />
              Refresh
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex w-fit gap-1 rounded-xl border border-white/[0.06] bg-[#0a1224]/60 p-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`rounded-lg px-5 py-2.5 text-xs font-semibold transition-all font-display tracking-wide ${
                activeTab === tab
                  ? 'bg-cyan-500/10 text-cyan-400 shadow-lg shadow-cyan-500/5'
                  : 'text-slate-600 hover:text-slate-400'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Loading */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex items-center gap-3 text-sm text-slate-500 font-mono">
              <Activity size={16} className="animate-spin" />
              Loading retention data...
            </div>
          </div>
        ) : (
          <>
            {activeTab === 'Overview' && (
              <OverviewTab
                overview={overview}
                byCarrier={byCarrier}
                byAgent={byAgent}
                trend={trend}
                bySource={bySource}
              />
            )}
            {activeTab === 'Growth' && <GrowthTab data={growthData} />}
            {activeTab === 'Cancellations' && <CancellationsTab cancellations={cancellations} />}
            {activeTab === 'Non-Pay' && <NonPayTab nonpayEmails={nonpayEmails} nonpayHistory={nonpayHistory} />}
            {activeTab === 'Re-Shop' && <ReShopTab cancellations={cancellations} />}
          </>
        )}
      </div>
    </div>
  );
}
