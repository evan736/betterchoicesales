/**
 * Win-Back Analysis & Campaign Builder.
 *
 * Page workflow:
 *   1. Load /api/winback/lost-account-analysis (read-only) and show:
 *      - Aggregate KPIs (total customers, total premium, contact reach)
 *      - Breakdown bars (by carrier, by year, by producer)
 *      - Filterable + sortable table of every lost customer
 *   2. User multi-selects rows (or "select all in current filter").
 *   3. Click "Add Selected to Winback" to enroll them as pending
 *      WinBackCampaign records (POST /api/winback/bulk-add-from-analysis).
 *   4. Navigate to existing winback list (GET /api/winback/) to review,
 *      exclude individuals, or activate the drip sequence.
 *
 * IMPORTANT: this page does NOT send any emails. It only reads
 * cancelled-account data and queues records for review. Activation
 * is a separate explicit step on the winback list view.
 */
import React, { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { winbackAPI } from '../lib/api';
import {
  Users,
  DollarSign,
  Mail,
  Phone,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  Search,
  Filter,
  AlertCircle,
  CheckCircle2,
  Send,
  Loader2,
  TrendingDown,
  Calendar,
  ExternalLink,
} from 'lucide-react';
import { toast } from '../components/ui/Toast';

// ─── Types ────────────────────────────────────────────────────────

interface LostCustomer {
  customer_id: number;
  nowcerts_insured_id: string | null;
  full_name: string;
  email: string | null;
  phone: string | null;
  city: string | null;
  state: string | null;
  agent_name: string | null;
  policy_count: number;
  lines_of_business: string[];
  carriers: string[];
  total_lost_premium: number;
  premium_was_estimated: boolean;
  latest_cancel_date: string | null;
  has_email: boolean;
  has_phone: boolean;
  duplicate_profile_count: number;
}

interface AnalysisResponse {
  filters: { months_back: number | null; cutoff_date: string | null };
  totals: {
    lost_customer_count: number;
    lost_premium_total: number;
    lost_customers_with_email: number;
    lost_customers_with_phone: number;
    lost_customers_no_contact: number;
    premium_estimated_from_prior_renewal_count: number;
  };
  exclusions: {
    excluded_due_to_active_duplicate: number;
    excluded_due_to_no_premium_data: number;
    excluded_due_to_old_cancellation: number;
  };
  by_carrier: Array<{ carrier: string; customer_count: number; premium: number }>;
  by_producer: Array<{ producer: string; customer_count: number; premium: number }>;
  by_year: Array<{ year: string; customer_count: number; premium: number }>;
  top_50_customers: LostCustomer[];
  all_customer_count: number;
}

// ─── Helpers ──────────────────────────────────────────────────────

const fmtMoney = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const fmtMoney2 = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const fmtNum = (n: number) => n.toLocaleString('en-US');
const fmtDate = (iso: string | null) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
};

// ─── Page ─────────────────────────────────────────────────────────

export default function WinbackAnalysisPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  // Auth gate
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace(`/?returnTo=${encodeURIComponent('/winback')}`);
    }
  }, [authLoading, user, router]);

  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [monthsBack, setMonthsBack] = useState<number | null>(null); // null = all-time
  const [search, setSearch] = useState('');
  const [carrierFilter, setCarrierFilter] = useState<string>('all');
  const [contactFilter, setContactFilter] = useState<'all' | 'reachable' | 'email_only' | 'phone_only'>('all');
  const [sortField, setSortField] = useState<'premium' | 'name' | 'cancel_date' | 'carrier'>('premium');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [enrolling, setEnrolling] = useState(false);

  const loadAnalysis = async (mb: number | null) => {
    setLoading(true);
    setSelectedIds(new Set());
    try {
      const r = await winbackAPI.lostAccountAnalysis(mb ?? undefined);
      setAnalysis(r.data);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to load analysis');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user) loadAnalysis(monthsBack);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // ─── Filtered & sorted customer list ───────────────────────────
  const filteredCustomers = useMemo(() => {
    if (!analysis) return [] as LostCustomer[];
    let rows = [...analysis.top_50_customers];
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter((r) =>
        (r.full_name || '').toLowerCase().includes(q) ||
        (r.email || '').toLowerCase().includes(q) ||
        (r.phone || '').toLowerCase().includes(q) ||
        (r.carriers || []).some((c) => c.toLowerCase().includes(q)),
      );
    }
    if (carrierFilter !== 'all') {
      rows = rows.filter((r) => (r.carriers || []).includes(carrierFilter));
    }
    if (contactFilter === 'reachable') {
      rows = rows.filter((r) => r.has_email || r.has_phone);
    } else if (contactFilter === 'email_only') {
      rows = rows.filter((r) => r.has_email);
    } else if (contactFilter === 'phone_only') {
      rows = rows.filter((r) => r.has_phone);
    }
    rows.sort((a, b) => {
      let cmp = 0;
      if (sortField === 'premium') cmp = a.total_lost_premium - b.total_lost_premium;
      else if (sortField === 'name') cmp = (a.full_name || '').localeCompare(b.full_name || '');
      else if (sortField === 'cancel_date') {
        cmp = (a.latest_cancel_date || '').localeCompare(b.latest_cancel_date || '');
      } else if (sortField === 'carrier') {
        cmp = (a.carriers[0] || '').localeCompare(b.carriers[0] || '');
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return rows;
  }, [analysis, search, carrierFilter, contactFilter, sortField, sortDir]);

  const allCarriers = useMemo(() => {
    if (!analysis) return [] as string[];
    return analysis.by_carrier.map((c) => c.carrier).sort();
  }, [analysis]);

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir(field === 'name' ? 'asc' : 'desc');
    }
  };

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(filteredCustomers.map((r) => r.customer_id)));
  };

  const clearSelection = () => setSelectedIds(new Set());

  const enrollSelected = async () => {
    if (selectedIds.size === 0) {
      toast.error('Select at least one customer');
      return;
    }
    if (
      !confirm(
        `Enroll ${selectedIds.size} customers as pending winback records?\n\n` +
          `They will NOT be contacted yet — this just queues them. ` +
          `You'll need to activate the drip sequence on the Winback list page.`,
      )
    )
      return;
    setEnrolling(true);
    try {
      const r = await winbackAPI.bulkAddFromAnalysis(Array.from(selectedIds));
      const data = r.data;
      toast.success(
        `Enrolled ${data.created} customers.\n` +
          `Skipped: ${data.skipped_already_exists} already in winback, ` +
          `${data.skipped_no_contact} no contact info.`,
      );
      clearSelection();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to enroll');
    } finally {
      setEnrolling(false);
    }
  };

  // ─── Auth states ────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="p-8 text-slate-400 flex items-center gap-2">
        <Loader2 size={16} className="animate-spin" />
        <span>Loading…</span>
      </div>
    );
  }
  if (!user) return <div className="p-8 text-slate-400">Redirecting to login…</div>;
  if (!user.role || !['admin', 'manager'].includes(user.role.toLowerCase())) {
    return (
      <div>
        <Navbar />
        <div className="p-8 text-slate-400">
          <AlertCircle size={20} className="inline mr-2" /> Admin or manager access required.
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <TrendingDown size={24} className="text-amber-400" />
              Win-Back Analysis
            </h1>
            <p className="text-slate-400 text-sm mt-1">
              Fully-cancelled customers with deduplicated lost premium. Read-only — no outreach happens here.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={monthsBack ?? ''}
              onChange={(e) => {
                const v = e.target.value;
                const next = v === '' ? null : parseInt(v, 10);
                setMonthsBack(next);
                loadAnalysis(next);
              }}
              className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
            >
              <option value="">All-time</option>
              <option value="6">Last 6 months</option>
              <option value="12">Last 12 months</option>
              <option value="24">Last 24 months</option>
            </select>
            <button
              onClick={() => loadAnalysis(monthsBack)}
              disabled={loading}
              className="bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded px-3 py-2 text-sm flex items-center gap-2"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>

        {loading && !analysis ? (
          <div className="p-8 text-slate-400 flex items-center gap-2 justify-center">
            <Loader2 size={16} className="animate-spin" />
            <span>Crunching ~3,700 customers and ~11,000 policies…</span>
          </div>
        ) : !analysis ? (
          <div className="p-8 text-slate-400">No data.</div>
        ) : (
          <>
            {/* KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <KPI
                label="Lost Customers"
                value={fmtNum(analysis.totals.lost_customer_count)}
                icon={<Users size={16} />}
                tone="amber"
              />
              <KPI
                label="Lost Premium"
                value={fmtMoney(analysis.totals.lost_premium_total)}
                icon={<DollarSign size={16} />}
                tone="rose"
              />
              <KPI
                label="Reachable by Email"
                value={fmtNum(analysis.totals.lost_customers_with_email)}
                sublabel={`${Math.round(
                  (analysis.totals.lost_customers_with_email /
                    Math.max(analysis.totals.lost_customer_count, 1)) *
                    100,
                )}% of total`}
                icon={<Mail size={16} />}
                tone="cyan"
              />
              <KPI
                label="Reachable by Phone"
                value={fmtNum(analysis.totals.lost_customers_with_phone)}
                sublabel={`${Math.round(
                  (analysis.totals.lost_customers_with_phone /
                    Math.max(analysis.totals.lost_customer_count, 1)) *
                    100,
                )}% of total`}
                icon={<Phone size={16} />}
                tone="emerald"
              />
            </div>

            {/* Footnotes about data quality */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6 text-xs text-slate-400">
              <Footnote
                tone="cyan"
                text={`${analysis.exclusions.excluded_due_to_active_duplicate} excluded as duplicates of active customers.`}
              />
              <Footnote
                tone="amber"
                text={`${analysis.totals.premium_estimated_from_prior_renewal_count} customers have premium estimated from prior renewals (final policy had $0 in NowCerts).`}
              />
              <Footnote
                tone="slate"
                text={`${analysis.exclusions.excluded_due_to_no_premium_data} customers excluded because no premium history exists at all.`}
              />
            </div>

            {/* Breakdown by carrier and year */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
              <BreakdownCard title="By Carrier" rows={analysis.by_carrier.slice(0, 8)} keyField="carrier" />
              <BreakdownCard
                title="By Cancellation Year"
                rows={analysis.by_year.slice(0, 8).map((r) => ({
                  carrier: r.year,
                  customer_count: r.customer_count,
                  premium: r.premium,
                }))}
                keyField="carrier"
              />
            </div>

            {/* Filters + actions */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4 mb-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="relative flex-1 min-w-[200px]">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search name, email, phone, carrier…"
                    className="w-full bg-slate-800 border border-slate-700 rounded pl-9 pr-3 py-2 text-sm"
                  />
                </div>
                <select
                  value={carrierFilter}
                  onChange={(e) => setCarrierFilter(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                >
                  <option value="all">All carriers</option>
                  {allCarriers.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <select
                  value={contactFilter}
                  onChange={(e) => setContactFilter(e.target.value as any)}
                  className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                >
                  <option value="all">All contact states</option>
                  <option value="reachable">Has email or phone</option>
                  <option value="email_only">Has email</option>
                  <option value="phone_only">Has phone</option>
                </select>
              </div>
              <div className="flex items-center gap-2 mt-3 flex-wrap">
                <span className="text-xs text-slate-400">
                  Showing {filteredCustomers.length} of top {analysis.top_50_customers.length}
                  {analysis.all_customer_count > analysis.top_50_customers.length && (
                    <span className="text-slate-500">
                      {' '}
                      (full dataset has {analysis.all_customer_count} customers — top 50 by premium shown)
                    </span>
                  )}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <button
                    onClick={selectAllVisible}
                    className="text-xs px-3 py-1.5 rounded border border-slate-700 hover:bg-slate-800"
                  >
                    Select visible ({filteredCustomers.length})
                  </button>
                  <button
                    onClick={clearSelection}
                    disabled={selectedIds.size === 0}
                    className="text-xs px-3 py-1.5 rounded border border-slate-700 hover:bg-slate-800 disabled:opacity-50"
                  >
                    Clear ({selectedIds.size})
                  </button>
                  <button
                    onClick={enrollSelected}
                    disabled={selectedIds.size === 0 || enrolling}
                    className="text-xs px-3 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {enrolling ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                    Enroll {selectedIds.size > 0 ? `(${selectedIds.size})` : ''} as pending
                  </button>
                </div>
              </div>
            </div>

            {/* Table */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-900 border-b border-slate-800 text-slate-400 text-xs uppercase">
                    <tr>
                      <th className="px-3 py-2 w-8">
                        <input
                          type="checkbox"
                          checked={
                            selectedIds.size > 0 &&
                            filteredCustomers.every((r) => selectedIds.has(r.customer_id))
                          }
                          onChange={(e) => (e.target.checked ? selectAllVisible() : clearSelection())}
                        />
                      </th>
                      <Th sortable onClick={() => toggleSort('name')} dir={sortField === 'name' ? sortDir : null}>
                        Name
                      </Th>
                      <Th>Contact</Th>
                      <Th sortable onClick={() => toggleSort('carrier')} dir={sortField === 'carrier' ? sortDir : null}>
                        Carriers / LOB
                      </Th>
                      <Th
                        sortable
                        onClick={() => toggleSort('premium')}
                        dir={sortField === 'premium' ? sortDir : null}
                        align="right"
                      >
                        Lost Premium
                      </Th>
                      <Th
                        sortable
                        onClick={() => toggleSort('cancel_date')}
                        dir={sortField === 'cancel_date' ? sortDir : null}
                      >
                        Cancelled
                      </Th>
                      <Th>Dup?</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCustomers.map((r) => (
                      <tr
                        key={r.customer_id}
                        className={`border-b border-slate-800/50 hover:bg-slate-800/30 ${
                          selectedIds.has(r.customer_id) ? 'bg-cyan-950/20' : ''
                        }`}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(r.customer_id)}
                            onChange={() => toggleSelect(r.customer_id)}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <div className="font-medium text-slate-100">{r.full_name}</div>
                          {(r.city || r.state) && (
                            <div className="text-xs text-slate-500">
                              {[r.city, r.state].filter(Boolean).join(', ')}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2">
                            <span className={r.has_email ? 'text-cyan-400' : 'text-slate-700'} title={r.email || ''}>
                              <Mail size={12} />
                            </span>
                            <span className={r.has_phone ? 'text-emerald-400' : 'text-slate-700'} title={r.phone || ''}>
                              <Phone size={12} />
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-slate-300">
                          <div>{r.carriers.slice(0, 2).join(', ')}</div>
                          <div className="text-xs text-slate-500">{r.lines_of_business.join(' · ')}</div>
                        </td>
                        <td className="px-3 py-2 text-right">
                          <span className="font-mono text-slate-100">{fmtMoney2(r.total_lost_premium)}</span>
                          {r.premium_was_estimated && (
                            <div
                              className="text-[10px] text-amber-400/70"
                              title="Estimated from prior renewal — final policy had $0"
                            >
                              est.
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-300">{fmtDate(r.latest_cancel_date)}</td>
                        <td className="px-3 py-2">
                          {r.duplicate_profile_count > 0 ? (
                            <span className="text-xs text-amber-400" title="Has duplicate profile(s) (none active)">
                              ⚠ {r.duplicate_profile_count}
                            </span>
                          ) : (
                            <span className="text-slate-700">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredCustomers.length === 0 && (
                <div className="p-8 text-center text-slate-500 text-sm">
                  No customers match the current filters.
                </div>
              )}
            </div>

            {analysis.all_customer_count > analysis.top_50_customers.length && (
              <div className="mt-3 text-xs text-slate-500">
                Showing top 50 by premium. {analysis.all_customer_count - analysis.top_50_customers.length} more
                customers exist in the dataset.
              </div>
            )}

            <div className="mt-6 flex items-center gap-3 text-sm">
              <a
                href="/winback-list"
                className="text-cyan-400 hover:text-cyan-300 flex items-center gap-1.5"
              >
                <ExternalLink size={14} />
                Go to enrolled winback campaigns
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Mini components ──────────────────────────────────────────────

function KPI({
  label,
  value,
  sublabel,
  icon,
  tone,
}: {
  label: string;
  value: string;
  sublabel?: string;
  icon: React.ReactNode;
  tone: 'amber' | 'rose' | 'cyan' | 'emerald';
}) {
  const toneClasses: Record<string, string> = {
    amber: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    rose: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
    cyan: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
    emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  };
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider text-slate-400">{label}</span>
        <span className={`p-1.5 rounded border ${toneClasses[tone]}`}>{icon}</span>
      </div>
      <div className="text-2xl font-bold text-slate-100">{value}</div>
      {sublabel && <div className="text-xs text-slate-500 mt-1">{sublabel}</div>}
    </div>
  );
}

function BreakdownCard({
  title,
  rows,
  keyField,
}: {
  title: string;
  rows: Array<{ carrier: string; customer_count: number; premium: number }>;
  keyField: string;
}) {
  const max = Math.max(...rows.map((r) => r.premium), 1);
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-3">{title}</h3>
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.carrier}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-slate-300">{r.carrier}</span>
              <span className="text-slate-400 font-mono">
                {r.customer_count} · {fmtMoney(r.premium)}
              </span>
            </div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-cyan-500 to-cyan-400"
                style={{ width: `${(r.premium / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Footnote({ tone, text }: { tone: 'cyan' | 'amber' | 'slate'; text: string }) {
  const toneCls =
    tone === 'cyan'
      ? 'border-cyan-500/20 text-cyan-300/80'
      : tone === 'amber'
      ? 'border-amber-500/20 text-amber-300/80'
      : 'border-slate-700 text-slate-400';
  return <div className={`px-3 py-2 rounded border ${toneCls} bg-slate-900/30`}>{text}</div>;
}

function Th({
  children,
  sortable,
  onClick,
  dir,
  align,
}: {
  children: React.ReactNode;
  sortable?: boolean;
  onClick?: () => void;
  dir?: 'asc' | 'desc' | null;
  align?: 'left' | 'right';
}) {
  return (
    <th
      onClick={sortable ? onClick : undefined}
      className={`px-3 py-2 ${align === 'right' ? 'text-right' : 'text-left'} ${
        sortable ? 'cursor-pointer select-none hover:text-slate-200' : ''
      }`}
    >
      <div className={`flex items-center gap-1 ${align === 'right' ? 'justify-end' : ''}`}>
        {children}
        {sortable && dir && (dir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
      </div>
    </th>
  );
}
