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
  Sliders,
  Power,
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

  // Tab state — winback (default) vs cold prospects (Allstate X-date list)
  const [tab, setTab] = useState<'winback' | 'cold'>('winback');

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
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <TrendingDown size={24} className="text-amber-400" />
              Outreach
            </h1>
            <p className="text-slate-400 text-sm mt-1">
              Win-Back analysis for former customers + Cold Prospects from the Allstate X-date list.
            </p>
          </div>
        </div>

        {/* Outreach scheduler control — visible to admins, persistent across tabs */}
        <SchedulerControlCard />

        {/* Tab strip */}
        <div className="flex items-center gap-2 border-b border-slate-800 mb-6">
          <button
            onClick={() => setTab('winback')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === 'winback'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Win-Back
          </button>
          <button
            onClick={() => setTab('cold')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === 'cold'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Cold Prospects
          </button>
        </div>

        {tab === 'winback' && (
          <>
        {/* Win-Back tab controls */}
        <div className="flex items-center justify-end mb-4 flex-wrap gap-3">
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
        </>
        )}

        {tab === 'cold' && <ColdProspectsPanel />}
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

// ─── Cold Prospects Panel ───────────────────────────────────────────
//
// Tab content for the Cold Prospects view. Self-contained: manages its
// own data load, filters, and pagination state. Hits these endpoints:
//   GET  /api/cold-prospects/stats         — KPI aggregates
//   GET  /api/cold-prospects/              — paginated list

interface ColdStats {
  total: number;
  by_status: Record<string, number>;
  by_phase: Record<string, number>;
  by_email_validation: Record<string, number>;
  by_customer_status: Record<string, number>;
  sendable_now: number;
  ever_emailed: number;
  converted: number;
}

interface ColdProspect {
  id: number;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  policy_type: string | null;
  company: string | null;
  premium: number | null;
  customer_status: string | null;
  next_x_date: string | null;
  phase: string | null;
  status: string | null;
  touchpoint_count: number;
  last_touchpoint_at: string | null;
  last_email_variant: string | null;
  assigned_producer: string | null;
  email_valid: boolean;
  do_not_email: boolean;
  bounce_count: number;
  excluded: boolean;
  excluded_reason: string | null;
  converted_at: string | null;
}

function ColdProspectsPanel() {
  const [stats, setStats] = useState<ColdStats | null>(null);
  const [items, setItems] = useState<ColdProspect[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);

  // Filters / pagination
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [customerStatusFilter, setCustomerStatusFilter] = useState<string>('all');
  const [contactedFilter, setContactedFilter] = useState<string>('all'); // all | yes | no
  const [producerFilter, setProducerFilter] = useState<string>('all');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  // Debounced search — don't fire a request on every keystroke
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const token = localStorage.getItem('token');
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      const res = await fetch(`${apiBase}/api/cold-prospects/stats`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStats(data);
    } catch (e) {
      console.error('Failed to load cold prospect stats:', e);
    } finally {
      setStatsLoading(false);
    }
  };

  const loadList = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      const params = new URLSearchParams({
        skip: String(page * PAGE_SIZE),
        limit: String(PAGE_SIZE),
        sort_by: 'id',
        sort_dir: 'desc',
      });
      if (debouncedSearch) params.set('search', debouncedSearch);
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (customerStatusFilter !== 'all') params.set('customer_status', customerStatusFilter);
      if (contactedFilter !== 'all') params.set('contacted', contactedFilter === 'yes' ? 'true' : 'false');
      if (producerFilter !== 'all') params.set('assigned_producer', producerFilter);

      const res = await fetch(`${apiBase}/api/cold-prospects/?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error('Failed to load cold prospects:', e);
    } finally {
      setLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    loadStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload list whenever filters change
  useEffect(() => {
    loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, debouncedSearch, statusFilter, customerStatusFilter, contactedFilter, producerFilter]);

  // Reset to page 0 when filters change
  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, statusFilter, customerStatusFilter, contactedFilter, producerFilter]);

  const fmtMoneyOrDash = (v: number | null) => v == null ? '—' : `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const fmtDateOrDash = (v: string | null) => v ? new Date(v).toLocaleDateString() : '—';

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <Users size={12} /> Total Prospects
          </div>
          <div className="text-2xl font-bold">{statsLoading ? '…' : (stats?.total || 0).toLocaleString()}</div>
          <div className="text-xs text-slate-500 mt-1">
            {stats && `${stats.sendable_now.toLocaleString()} sendable`}
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <Send size={12} /> Ever Contacted
          </div>
          <div className="text-2xl font-bold text-cyan-400">{statsLoading ? '…' : (stats?.ever_emailed || 0).toLocaleString()}</div>
          <div className="text-xs text-slate-500 mt-1">
            {stats && stats.total > 0 && `${((stats.ever_emailed / stats.total) * 100).toFixed(1)}% of list`}
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <CheckCircle2 size={12} /> Converted
          </div>
          <div className="text-2xl font-bold text-emerald-400">{statsLoading ? '…' : (stats?.converted || 0).toLocaleString()}</div>
          <div className="text-xs text-slate-500 mt-1">Sales matched to prospects</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <AlertCircle size={12} /> Suppressed / Replied
          </div>
          <div className="text-2xl font-bold text-amber-400">
            {statsLoading ? '…' : (
              (stats?.by_status?.paused_bounced || 0) +
              (stats?.by_status?.paused_replied || 0) +
              (stats?.by_status?.paused_unsubscribed || 0) +
              (stats?.by_status?.paused_complained || 0)
            ).toLocaleString()}
          </div>
          <div className="text-xs text-slate-500 mt-1">Bounced / unsub / spam / replied</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div className="md:col-span-2 relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name or email..."
              className="w-full bg-slate-800 border border-slate-700 rounded pl-9 pr-3 py-2 text-sm"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="converted">Converted</option>
            <option value="paused_replied">Replied</option>
            <option value="paused_bounced">Bounced</option>
            <option value="paused_unsubscribed">Unsubscribed</option>
            <option value="paused_complained">Complained</option>
            <option value="excluded">Excluded</option>
          </select>
          <select
            value={customerStatusFilter}
            onChange={(e) => setCustomerStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
          >
            <option value="all">All Source Types</option>
            <option value="Prospect">Prospect</option>
            <option value="Former Customer">Former Customer</option>
            <option value="null">No Customer Status</option>
          </select>
          <select
            value={contactedFilter}
            onChange={(e) => setContactedFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
          >
            <option value="all">All</option>
            <option value="yes">Contacted</option>
            <option value="no">Never Contacted</option>
          </select>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mt-3">
          <select
            value={producerFilter}
            onChange={(e) => setProducerFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm md:col-span-2"
          >
            <option value="all">All Producers</option>
            <option value="evan.larson">Evan</option>
            <option value="joseph.rivera">Joseph</option>
            <option value="giulian.baez">Giulian</option>
            <option value="unassigned">Unassigned</option>
          </select>
          <div className="md:col-span-3 flex items-center justify-end gap-3 text-sm text-slate-400">
            <span>{loading ? 'Loading...' : `${total.toLocaleString()} matching`}</span>
            <button
              onClick={() => { loadStats(); loadList(); }}
              disabled={loading}
              className="bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded px-3 py-2 text-sm flex items-center gap-2"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        {loading && items.length === 0 ? (
          <div className="p-8 text-slate-400 flex items-center gap-2 justify-center">
            <Loader2 size={16} className="animate-spin" />
            Loading prospects...
          </div>
        ) : items.length === 0 ? (
          <div className="p-8 text-slate-400 text-center">
            No prospects match these filters.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-950 text-slate-400 text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Email</th>
                  <th className="px-3 py-2 text-left">Location</th>
                  <th className="px-3 py-2 text-left">Source / Type</th>
                  <th className="px-3 py-2 text-right">Premium</th>
                  <th className="px-3 py-2 text-left">Producer</th>
                  <th className="px-3 py-2 text-right">Touches</th>
                  <th className="px-3 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id} className="border-t border-slate-800 hover:bg-slate-800/50">
                    <td className="px-3 py-2">
                      <div className="font-medium">{p.full_name || `${p.first_name || ''} ${p.last_name || ''}`.trim() || '—'}</div>
                      {p.phone && <div className="text-xs text-slate-500">{p.phone}</div>}
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      {p.email || <span className="text-slate-600">—</span>}
                      {p.email_valid === false && p.email && (
                        <span className="ml-1 text-xs text-rose-400">invalid</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400 text-xs">
                      {p.city ? `${p.city}, ${p.state || ''}` : (p.state || '—')}
                      {p.zip_code && <div>{p.zip_code}</div>}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <div className="text-slate-300">{p.customer_status || '—'}</div>
                      <div className="text-slate-500">{p.policy_type ? `${p.policy_type}${p.company ? ' / ' + p.company : ''}` : (p.company || '—')}</div>
                    </td>
                    <td className="px-3 py-2 text-right text-slate-300">{fmtMoneyOrDash(p.premium)}</td>
                    <td className="px-3 py-2 text-xs text-slate-400">
                      {p.assigned_producer || <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="text-slate-300">{p.touchpoint_count}</div>
                      {p.last_touchpoint_at && (
                        <div className="text-xs text-slate-500">{fmtDateOrDash(p.last_touchpoint_at)}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <ColdStatusBadge status={p.status} bounceCount={p.bounce_count} converted={!!p.converted_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {total > 0 && (
          <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3 text-sm text-slate-400">
            <div>
              Page {page + 1} of {totalPages.toLocaleString()} · Showing {items.length} of {total.toLocaleString()}
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page === 0 || loading}
                onClick={() => setPage(0)}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                First
              </button>
              <button
                disabled={page === 0 || loading}
                onClick={() => setPage(p => Math.max(0, p - 1))}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Prev
              </button>
              <button
                disabled={page >= totalPages - 1 || loading}
                onClick={() => setPage(p => p + 1)}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Next
              </button>
              <button
                disabled={page >= totalPages - 1 || loading}
                onClick={() => setPage(totalPages - 1)}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Last
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Help text */}
      <div className="mt-4 text-xs text-slate-500">
        <p>
          28K Allstate X-date prospects. Imported from territorial export.
          Phase 1 cold-wakeup is paced over 90 days; Phase 2 fires -30/-21/-14/-7 days
          before each prospect's renewal X-date.
          Schedulers are gated by env vars on Render — flip{' '}
          <code className="bg-slate-800 px-1.5 py-0.5 rounded">COLD_PROSPECT_SCHEDULER_ENABLED=true</code>{' '}
          to start sending.
        </p>
      </div>
    </>
  );
}

function ColdStatusBadge({ status, bounceCount, converted }: { status: string | null; bounceCount: number; converted: boolean }) {
  if (converted) {
    return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">Converted</span>;
  }
  switch (status) {
    case 'active':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">Active</span>;
    case 'paused_replied':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30">Replied</span>;
    case 'paused_bounced':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-400 border border-rose-500/30" title={`${bounceCount} bounce(s)`}>Bounced</span>;
    case 'paused_unsubscribed':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-slate-500/20 text-slate-400 border border-slate-500/30">Unsubscribed</span>;
    case 'paused_complained':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-400 border border-rose-500/30">Spam Complaint</span>;
    case 'excluded':
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-slate-700/50 text-slate-500 border border-slate-700">Excluded</span>;
    default:
      return <span className="text-xs text-slate-500">{status || '—'}</span>;
  }
}

// ─── Scheduler control card ─────────────────────────────────────────
//
// Admin-only card for tuning the outreach schedulers (winback + cold)
// without touching Render env vars.
//
// Backend: GET /api/admin/outreach-scheduler-config returns current
// values + computed daily volumes. POST same path with the fields
// to change. Scheduler picks up new values on its next 30-min tick.

interface SchedulerConfigField {
  value: number | boolean;
  source: 'db' | 'env' | 'default';
  updated_at: string | null;
  updated_by: string | null;
}

interface SchedulerConfig {
  winback_scheduler_enabled: SchedulerConfigField;
  winback_max_per_tick: SchedulerConfigField;
  cold_prospect_scheduler_enabled: SchedulerConfigField;
  cold_max_per_tick: SchedulerConfigField;
  winback_max_per_day: number;
  cold_max_per_day: number;
  combined_max_per_day: number;
  ticks_per_day: number;
  business_hours_ct: string;
  tick_interval_minutes: number;
}

function SchedulerControlCard() {
  const { user } = useAuth();
  const [config, setConfig] = useState<SchedulerConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Local edit state — initialized from config, only saved on Save click
  const [winbackEnabled, setWinbackEnabled] = useState(false);
  const [winbackPerTick, setWinbackPerTick] = useState(2);
  const [coldEnabled, setColdEnabled] = useState(false);
  const [coldPerTick, setColdPerTick] = useState(4);

  const isAdmin = (user?.role || '').toLowerCase() === 'admin';

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

  const load = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${apiBase}/api/admin/outreach-scheduler-config`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SchedulerConfig = await res.json();
      setConfig(data);
      setWinbackEnabled(Boolean(data.winback_scheduler_enabled.value));
      setWinbackPerTick(Number(data.winback_max_per_tick.value));
      setColdEnabled(Boolean(data.cold_prospect_scheduler_enabled.value));
      setColdPerTick(Number(data.cold_max_per_tick.value));
    } catch (e) {
      console.error('Failed to load scheduler config:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const save = async () => {
    setSaving(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${apiBase}/api/admin/outreach-scheduler-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          winback_scheduler_enabled: winbackEnabled,
          winback_max_per_tick: winbackPerTick,
          cold_prospect_scheduler_enabled: coldEnabled,
          cold_max_per_tick: coldPerTick,
        }),
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }
      toast.success('Scheduler config updated. Applies within 30 min.');
      load();
    } catch (e: any) {
      toast.error(`Save failed: ${e?.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) return null;
  if (loading || !config) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 mb-6">
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Loader2 size={14} className="animate-spin" />
          Loading scheduler config...
        </div>
      </div>
    );
  }

  // Has the user changed anything from server state?
  const dirty =
    winbackEnabled !== Boolean(config.winback_scheduler_enabled.value) ||
    winbackPerTick !== Number(config.winback_max_per_tick.value) ||
    coldEnabled !== Boolean(config.cold_prospect_scheduler_enabled.value) ||
    coldPerTick !== Number(config.cold_max_per_tick.value);

  // Computed projections based on EDITED values
  const winbackPerDay = winbackPerTick * config.ticks_per_day;
  const coldPerDay = coldPerTick * config.ticks_per_day;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg mb-6 overflow-hidden">
      {/* Collapsed header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Sliders size={16} className="text-cyan-400" />
          <span className="text-sm font-medium">Outreach Scheduler</span>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded ${winbackEnabled ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-800 text-slate-500'}`}>
              <Power size={10} />
              Winback {winbackEnabled ? 'ON' : 'OFF'}
            </span>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded ${coldEnabled ? 'bg-cyan-500/20 text-cyan-400' : 'bg-slate-800 text-slate-500'}`}>
              <Power size={10} />
              Cold {coldEnabled ? 'ON' : 'OFF'}
            </span>
            <span className="text-slate-500">
              · max {(winbackEnabled ? winbackPerDay : 0) + (coldEnabled ? coldPerDay : 0)}/day
            </span>
          </div>
        </div>
        <ChevronDown size={14} className={`text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="border-t border-slate-800 p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Winback controls */}
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TrendingDown size={14} className="text-amber-400" />
                  <span className="font-medium text-sm">Win-Back Scheduler</span>
                </div>
                <ToggleSwitch checked={winbackEnabled} onChange={setWinbackEnabled} accent="amber" />
              </div>
              <div className={winbackEnabled ? '' : 'opacity-50 pointer-events-none'}>
                <label className="block text-xs text-slate-400 mb-1">Emails per tick (every 30 min)</label>
                <input
                  type="number"
                  min={0}
                  max={500}
                  value={winbackPerTick}
                  onChange={(e) => setWinbackPerTick(Math.max(0, Math.min(500, parseInt(e.target.value) || 0)))}
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm font-mono"
                />
                <div className="text-xs text-slate-500 mt-2">
                  = <span className="text-slate-300 font-mono">{winbackPerDay}</span> emails/day max
                </div>
              </div>
              {config.winback_max_per_tick.source !== 'db' && (
                <div className="text-xs text-slate-500 italic">
                  Currently from {config.winback_max_per_tick.source === 'env' ? 'Render env var' : 'default'}. Saving will switch to DB control.
                </div>
              )}
            </div>

            {/* Cold prospect controls */}
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Users size={14} className="text-cyan-400" />
                  <span className="font-medium text-sm">Cold Prospect Scheduler</span>
                </div>
                <ToggleSwitch checked={coldEnabled} onChange={setColdEnabled} accent="cyan" />
              </div>
              <div className={coldEnabled ? '' : 'opacity-50 pointer-events-none'}>
                <label className="block text-xs text-slate-400 mb-1">Emails per tick (every 30 min)</label>
                <input
                  type="number"
                  min={0}
                  max={2000}
                  value={coldPerTick}
                  onChange={(e) => setColdPerTick(Math.max(0, Math.min(2000, parseInt(e.target.value) || 0)))}
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm font-mono"
                />
                <div className="text-xs text-slate-500 mt-2">
                  = <span className="text-slate-300 font-mono">{coldPerDay.toLocaleString()}</span> emails/day max
                </div>
              </div>
              {config.cold_max_per_tick.source !== 'db' && (
                <div className="text-xs text-slate-500 italic">
                  Currently from {config.cold_max_per_tick.source === 'env' ? 'Render env var' : 'default'}. Saving will switch to DB control.
                </div>
              )}
            </div>
          </div>

          {/* Quick presets for cold ramp */}
          <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
            <div className="text-xs text-slate-400 mb-2">Cold prospect quick presets:</div>
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'Conservative (48/day)', value: 4 },
                { label: 'Day 3 ramp (240/day)', value: 20 },
                { label: 'Week 2 (600/day)', value: 50 },
                { label: 'Full speed (1,200/day)', value: 100 },
                { label: 'Aggressive (2,400/day)', value: 200 },
              ].map((p) => (
                <button
                  key={p.value}
                  onClick={() => setColdPerTick(p.value)}
                  className={`px-2 py-1 text-xs rounded border ${
                    coldPerTick === p.value
                      ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                      : 'bg-slate-800 border-slate-700 text-slate-400 hover:bg-slate-700'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Summary + save */}
          <div className="flex items-center justify-between pt-2 border-t border-slate-800">
            <div className="text-xs text-slate-400">
              Active hours: {config.business_hours_ct} · Tick every {config.tick_interval_minutes} min · {config.ticks_per_day} ticks/day
              <br />
              Changes apply within 30 minutes (next scheduler tick).
            </div>
            <button
              onClick={save}
              disabled={!dirty || saving}
              className={`px-4 py-2 rounded text-sm font-medium ${
                !dirty || saving
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'
              }`}
            >
              {saving ? 'Saving...' : dirty ? 'Save changes' : 'No changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ToggleSwitch({ checked, onChange, accent }: { checked: boolean; onChange: (v: boolean) => void; accent: 'amber' | 'cyan' }) {
  const accentClass = accent === 'amber' ? 'bg-amber-500' : 'bg-cyan-500';
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked ? accentClass : 'bg-slate-700'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-1'
        }`}
      />
    </button>
  );
}
