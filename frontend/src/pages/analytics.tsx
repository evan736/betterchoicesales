import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import TrendingGoals from '../components/TrendingGoals';
import { analyticsAPI } from '../lib/api';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import {
  DollarSign, TrendingUp, FileText, Users, Filter, ChevronDown
} from 'lucide-react';

const COLORS = ['#0ea5e9', '#0284c7', '#0369a1', '#075985', '#0c4a6e', '#38bdf8', '#7dd3fc', '#bae6fd', '#d97706', '#f59e0b', '#10b981', '#ef4444'];

const GROUP_OPTIONS = [
  { value: 'lead_source', label: 'Lead Source' },
  { value: 'producer', label: 'Producer' },
  { value: 'policy_type', label: 'Policy Type' },
  { value: 'carrier', label: 'Carrier' },
  { value: 'state', label: 'State' },
];

const PERIOD_OPTIONS = [
  { value: 'monthly', label: 'This Month' },
  { value: 'last_month', label: 'Last Month' },
  { value: 'annual', label: 'This Year' },
  { value: 'last_year', label: 'Last Year' },
  { value: 'all-time', label: 'All Time' },
];

export default function Analytics() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [period, setPeriod] = useState('monthly');
  const [groupBy, setGroupBy] = useState('lead_source');
  const [summary, setSummary] = useState<any>(null);
  const [chartData, setChartData] = useState<any[]>([]);
  const [salesData, setSalesData] = useState<any[]>([]);
  const [salesTotal, setSalesTotal] = useState(0);
  const [filterOptions, setFilterOptions] = useState<any>(null);
  const [loadingData, setLoadingData] = useState(true);

  const [trendingData, setTrendingData] = useState<any>(null);

  // Table filters
  const [tableFilters, setTableFilters] = useState<any>({});
  const [sortBy, setSortBy] = useState('sale_date');
  const [sortOrder, setSortOrder] = useState('desc');

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) {
      loadFilterOptions();
      loadData();
    }
  }, [user, loading]);

  useEffect(() => {
    if (user) loadData();
  }, [period, groupBy, tableFilters, sortBy, sortOrder]);

  const loadFilterOptions = async () => {
    try {
      const res = await analyticsAPI.filterOptions();
      setFilterOptions(res.data);
    } catch (e) { console.error(e); }
  };

  const loadData = async () => {
    setLoadingData(true);
    try {
      const periodParam = period === 'all-time' ? undefined : period;
      const now = new Date();
      const extraParams: any = {};
      if (period === 'last_year') {
        extraParams.year = now.getFullYear() - 1;
      }
      const apiPeriod = period === 'last_year' ? 'annual' : periodParam;
      const [summaryRes, groupRes, tableRes, trendRes] = await Promise.all([
        analyticsAPI.summary({ period: apiPeriod, ...extraParams }),
        analyticsAPI.byGroup({ group_by: groupBy, period: apiPeriod, ...extraParams }),
        analyticsAPI.salesTable({
          period: apiPeriod,
          sort_by: sortBy,
          sort_order: sortOrder,
          ...extraParams,
          ...tableFilters,
          limit: 50,
        }),
        analyticsAPI.trending({ period: period === 'all-time' ? 'annual' : (period === 'last_month' ? 'monthly' : period) }),
      ]);
      setSummary(summaryRes.data);
      setChartData(groupRes.data.results || []);
      setSalesData(tableRes.data.sales || []);
      setSalesTotal(tableRes.data.total || 0);
      setTrendingData(trendRes.data);
    } catch (e) { console.error(e); }
    finally { setLoadingData(false); }
  };

  if (loading || !user) return null;

  const formatCurrency = (val: number) => `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
          <div>
            <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">Sales Analytics</h1>
            <p className="text-slate-600">Agency performance, filtered by any dimension</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {PERIOD_OPTIONS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                className={`px-4 py-2 rounded-lg font-semibold text-sm transition-all ${
                  period === p.value
                    ? 'bg-brand-600 text-white shadow-md'
                    : 'bg-white text-slate-600 border border-slate-200 hover:border-brand-300'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Summary Cards — dynamic trending numbers */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <SummaryCard icon={<DollarSign />} label="Total Premium" value={formatCurrency(summary?.total_premium || 0)} color="text-green-600" bg="bg-green-100" />
          <SummaryCard
            icon={<TrendingUp />}
            label={period === 'last_year' ? 'Last Year Total' : 'Projected'}
            value={trendingData ? formatCurrency(trendingData.projected_premium) : '—'}
            color="text-brand-600"
            bg="bg-brand-100"
          />
          <SummaryCard
            icon={<FileText />}
            label="Daily Pace"
            value={trendingData && trendingData.daily_pace > 0 ? formatCurrency(trendingData.daily_pace) : '—'}
            color="text-blue-600"
            bg="bg-blue-100"
          />
          <SummaryCard icon={<Users />} label="Policies / Items" value={`${summary?.total_policies || 0} / ${summary?.total_items || 0}`} color="text-purple-600" bg="bg-purple-100" />
        </div>

        {/* Trending Data (left) + Goals & Milestones (right) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          <TrendingGoals period={period} showGoals={false} />
          <TrendingGoals period={period} showTrending={false} />
        </div>

        {/* Chart Section */}
        <div className="card mb-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between mb-6 gap-4">
            <h2 className="font-display text-2xl font-bold text-slate-900">Premium Breakdown</h2>
            <div className="flex items-center gap-2 flex-wrap">
              {GROUP_OPTIONS.map((g) => (
                <button
                  key={g.value}
                  onClick={() => setGroupBy(g.value)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                    groupBy === g.value
                      ? 'bg-brand-600 text-white'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>

          {chartData.length === 0 ? (
            <div className="text-center py-16 text-slate-400">No data for this period</div>
          ) : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 60 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="group"
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  angle={-35}
                  textAnchor="end"
                  interval={0}
                  height={80}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  formatter={(value: any) => [formatCurrency(value), 'Premium']}
                  contentStyle={{ borderRadius: '12px', border: '1px solid #e2e8f0' }}
                />
                <Bar dataKey="total_premium" radius={[6, 6, 0, 0]}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Sales Table */}
        <div className="card">
          <div className="flex flex-col md:flex-row md:items-center justify-between mb-6 gap-4">
            <h2 className="font-display text-2xl font-bold text-slate-900">
              Sales ({salesTotal})
            </h2>
            {/* Inline filters */}
            <div className="flex items-center gap-2 flex-wrap">
              {filterOptions && (
                <>
                  <FilterSelect
                    label="Source"
                    value={tableFilters.lead_source || ''}
                    onChange={(v) => setTableFilters({ ...tableFilters, lead_source: v || undefined })}
                    options={filterOptions.lead_sources.map((s: string) => ({ value: s, label: s.replace(/_/g, ' ') }))}
                  />
                  <FilterSelect
                    label="Type"
                    value={tableFilters.policy_type || ''}
                    onChange={(v) => setTableFilters({ ...tableFilters, policy_type: v || undefined })}
                    options={filterOptions.policy_types.map((s: string) => ({ value: s, label: s.replace(/_/g, ' ') }))}
                  />
                  {filterOptions.carriers.length > 0 && (
                    <FilterSelect
                      label="Carrier"
                      value={tableFilters.carrier || ''}
                      onChange={(v) => setTableFilters({ ...tableFilters, carrier: v || undefined })}
                      options={filterOptions.carriers.map((s: string) => ({ value: s, label: s }))}
                    />
                  )}
                  {filterOptions.states.length > 0 && (
                    <FilterSelect
                      label="State"
                      value={tableFilters.state || ''}
                      onChange={(v) => setTableFilters({ ...tableFilters, state: v || undefined })}
                      options={filterOptions.states.map((s: string) => ({ value: s, label: s }))}
                    />
                  )}
                  {filterOptions.producers.length > 0 && (
                    <FilterSelect
                      label="Producer"
                      value={tableFilters.producer_id || ''}
                      onChange={(v) => setTableFilters({ ...tableFilters, producer_id: v ? parseInt(v) : undefined })}
                      options={filterOptions.producers.map((p: any) => ({ value: String(p.id), label: p.name }))}
                    />
                  )}
                </>
              )}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <SortHeader label="Sale Date" field="sale_date" sortBy={sortBy} sortOrder={sortOrder} onSort={(f, o) => { setSortBy(f); setSortOrder(o); }} />
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Policy #</th>
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Customer</th>
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Type</th>
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Carrier</th>
                  <SortHeader label="Premium" field="written_premium" sortBy={sortBy} sortOrder={sortOrder} onSort={(f, o) => { setSortBy(f); setSortOrder(o); }} />
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Items</th>
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Source</th>
                  <th className="text-left py-3 px-3 font-semibold text-slate-600">Producer</th>
                </tr>
              </thead>
              <tbody>
                {salesData.map((s: any) => (
                  <tr key={s.id} className="border-b border-slate-100 hover:bg-brand-50/30 transition-colors">
                    <td className="py-3 px-3 text-slate-700">{s.sale_date ? new Date(s.sale_date).toLocaleDateString() : '—'}</td>
                    <td className="py-3 px-3 font-medium text-slate-900">{s.policy_number}</td>
                    <td className="py-3 px-3 text-slate-700">{s.client_name}</td>
                    <td className="py-3 px-3"><TypeBadge type={s.policy_type} /></td>
                    <td className="py-3 px-3 text-slate-700">{s.carrier || '—'}</td>
                    <td className="py-3 px-3 font-bold text-brand-600">{formatCurrency(s.written_premium)}</td>
                    <td className="py-3 px-3 text-center text-slate-700">{s.item_count}</td>
                    <td className="py-3 px-3 text-slate-600 text-xs">{(s.lead_source || '').replace(/_/g, ' ')}</td>
                    <td className="py-3 px-3 text-slate-700">{s.producer_name}</td>
                  </tr>
                ))}
                {salesData.length === 0 && (
                  <tr><td colSpan={9} className="py-12 text-center text-slate-400">No sales match your filters</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}

/* ---------- Sub-components ---------- */

const SummaryCard: React.FC<{ icon: React.ReactNode; label: string; value: any; color: string; bg: string }> = ({ icon, label, value, color, bg }) => (
  <div className="stat-card">
    <div className={`p-3 rounded-lg ${bg} ${color} w-fit mb-3`}>{icon}</div>
    <div className="text-3xl font-bold text-slate-900">{value}</div>
    <div className="text-sm text-slate-600 font-medium">{label}</div>
  </div>
);

const FilterSelect: React.FC<{ label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }> = ({ label, value, onChange, options }) => (
  <select
    value={value}
    onChange={(e) => onChange(e.target.value)}
    className="px-3 py-1.5 rounded-lg text-sm border border-slate-200 bg-white text-slate-700 focus:border-brand-400 focus:ring-1 focus:ring-brand-200 outline-none capitalize"
  >
    <option value="">All {label}s</option>
    {options.map((o) => (
      <option key={o.value} value={o.value} className="capitalize">{o.label}</option>
    ))}
  </select>
);

const SortHeader: React.FC<{ label: string; field: string; sortBy: string; sortOrder: string; onSort: (f: string, o: string) => void }> = ({ label, field, sortBy, sortOrder, onSort }) => (
  <th
    className="text-left py-3 px-3 font-semibold text-slate-600 cursor-pointer hover:text-brand-600 select-none"
    onClick={() => onSort(field, sortBy === field && sortOrder === 'desc' ? 'asc' : 'desc')}
  >
    {label} {sortBy === field && (sortOrder === 'desc' ? '↓' : '↑')}
  </th>
);

const TypeBadge: React.FC<{ type: string | null }> = ({ type }) => {
  if (!type) return <span className="text-slate-400 text-xs">—</span>;
  const colors: Record<string, string> = {
    auto: 'bg-blue-100 text-blue-800',
    home: 'bg-green-100 text-green-800',
    renters: 'bg-purple-100 text-purple-800',
    condo: 'bg-teal-100 text-teal-800',
    landlord: 'bg-orange-100 text-orange-800',
    bundled: 'bg-yellow-100 text-yellow-800',
    life: 'bg-red-100 text-red-800',
    rv: 'bg-indigo-100 text-indigo-800',
    commercial: 'bg-gray-100 text-gray-800',
  };
  const cls = colors[type] || 'bg-slate-100 text-slate-700';
  return <span className={`badge ${cls} capitalize`}>{type.replace(/_/g, ' ')}</span>;
};
