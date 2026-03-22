import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend
} from 'recharts';
import {
  TrendingUp, TrendingDown, DollarSign, Calendar, ChevronDown, ChevronUp,
  Target, Activity, ArrowUpRight, ArrowDownRight, Eye
} from 'lucide-react';
import axios from 'axios';

const API = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
}

function fmtFull(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(n);
}

function pct(n: number) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;
}

interface MonthData {
  month: string;
  label: string;
  expiring_policy_count: number;
  expiring_premium: number;
  projected_renewal_premium: number;
  projected_commission: number;
  actual_commission: number;
  variance: number;
  variance_pct: number;
}

interface PolicyDetail {
  policy_number: string;
  client_name: string;
  carrier: string;
  policy_type: string;
  effective_date: string;
  expiration_date: string;
  current_premium: number;
  projected_renewal_premium: number;
  projected_commission: number;
  term_months: number;
}

export default function RevenueTracker() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<{ months: MonthData[]; summary: any } | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [expandedMonth, setExpandedMonth] = useState<string | null>(null);
  const [policies, setPolicies] = useState<PolicyDetail[]>([]);
  const [loadingPolicies, setLoadingPolicies] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) loadData();
  }, [user, loading]);

  const loadData = async () => {
    try {
      setLoadingData(true);
      const token = localStorage.getItem('token');
      const res = await axios.get(`${API}/api/revenue-tracker/projections?months_ahead=6`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setData(res.data);
    } catch (err) {
      console.error('Failed to load revenue projections:', err);
    } finally {
      setLoadingData(false);
    }
  };

  const loadPolicies = async (period: string) => {
    if (expandedMonth === period) {
      setExpandedMonth(null);
      return;
    }
    try {
      setLoadingPolicies(true);
      setExpandedMonth(period);
      const token = localStorage.getItem('token');
      const res = await axios.get(`${API}/api/revenue-tracker/projections/${period}/policies`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setPolicies(res.data.policies || []);
    } catch (err) {
      console.error('Failed to load policies:', err);
    } finally {
      setLoadingPolicies(false);
    }
  };

  if (loading || !user) return (
    <div className="min-h-screen">
      <div className="glass sticky top-0 z-50 border-b border-white/20 h-14" />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="h-8 w-56 rounded-lg bg-slate-200 animate-pulse mb-6" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          {[1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl bg-slate-200 animate-pulse" />)}
        </div>
        <div className="h-96 rounded-xl bg-slate-200 animate-pulse" />
      </main>
    </div>
  );

  const months = data?.months || [];
  const summary = data?.summary;

  const chartData = months.map(m => ({
    name: m.label.split(' ')[0].substring(0, 3),
    projected: Math.round(m.projected_commission),
    actual: Math.round(m.actual_commission),
  }));

  return (
    <div className="min-h-screen" style={{ background: '#0a0f1e' }}>
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Activity className="w-7 h-7" style={{ color: '#0ea5e9' }} />
              Revenue Tracker
            </h1>
            <p className="text-sm mt-1" style={{ color: '#64748b' }}>
              Projected vs actual renewal commission &mdash; next 6 months
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs" style={{ color: '#64748b' }}>
            <span className="px-2 py-1 rounded" style={{ background: 'rgba(14,165,233,0.15)', color: '#0ea5e9' }}>
              10% rate increase
            </span>
            <span className="px-2 py-1 rounded" style={{ background: 'rgba(14,165,233,0.15)', color: '#0ea5e9' }}>
              13% commission
            </span>
          </div>
        </div>

        {loadingData ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2" style={{ borderColor: '#0ea5e9' }} />
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            {summary && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                <div className="rounded-xl p-5" style={{ background: 'rgba(15,23,42,0.8)', border: '1px solid rgba(14,165,233,0.15)' }}>
                  <div className="flex items-center gap-2 mb-1">
                    <Target className="w-4 h-4" style={{ color: '#0ea5e9' }} />
                    <span className="text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Projected (6mo)</span>
                  </div>
                  <div className="text-2xl font-bold text-white">{fmt(summary.total_projected_commission)}</div>
                  <div className="text-xs mt-1" style={{ color: '#64748b' }}>Based on expiring policies</div>
                </div>

                <div className="rounded-xl p-5" style={{ background: 'rgba(15,23,42,0.8)', border: '1px solid rgba(14,165,233,0.15)' }}>
                  <div className="flex items-center gap-2 mb-1">
                    <DollarSign className="w-4 h-4" style={{ color: '#10b981' }} />
                    <span className="text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Actual Received</span>
                  </div>
                  <div className="text-2xl font-bold" style={{ color: '#10b981' }}>{fmt(summary.total_actual_commission)}</div>
                  <div className="text-xs mt-1" style={{ color: '#64748b' }}>From carrier renewal statements</div>
                </div>

                <div className="rounded-xl p-5" style={{ background: 'rgba(15,23,42,0.8)', border: `1px solid ${summary.total_variance >= 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}` }}>
                  <div className="flex items-center gap-2 mb-1">
                    {summary.total_variance >= 0
                      ? <ArrowUpRight className="w-4 h-4" style={{ color: '#10b981' }} />
                      : <ArrowDownRight className="w-4 h-4" style={{ color: '#ef4444' }} />
                    }
                    <span className="text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Variance</span>
                  </div>
                  <div className="text-2xl font-bold" style={{ color: summary.total_variance >= 0 ? '#10b981' : '#ef4444' }}>
                    {fmt(summary.total_variance)}
                  </div>
                  <div className="text-xs mt-1" style={{ color: '#64748b' }}>Actual vs projected</div>
                </div>
              </div>
            )}

            {/* Chart */}
            <div className="rounded-xl p-6 mb-8" style={{ background: 'rgba(15,23,42,0.8)', border: '1px solid rgba(14,165,233,0.1)' }}>
              <h2 className="text-sm font-medium text-white mb-4">Projected vs Actual Commission</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData} barGap={4}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,0.15)" />
                  <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 12 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 12 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid rgba(14,165,233,0.2)', borderRadius: 8, color: '#fff' }}
                    formatter={(value: number, name: string) => [fmt(value), name === 'projected' ? 'Projected' : 'Actual']}
                  />
                  <Legend formatter={(value) => value === 'projected' ? 'Projected' : 'Actual'} />
                  <Bar dataKey="projected" fill="#0c4a6e" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="actual" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Monthly Breakdown Table */}
            <div className="rounded-xl overflow-hidden" style={{ background: 'rgba(15,23,42,0.8)', border: '1px solid rgba(14,165,233,0.1)' }}>
              <div className="px-6 py-4" style={{ borderBottom: '1px solid rgba(14,165,233,0.1)' }}>
                <h2 className="text-sm font-medium text-white">Monthly Breakdown</h2>
              </div>

              <table className="w-full">
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(14,165,233,0.08)' }}>
                    <th className="text-left px-6 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Month</th>
                    <th className="text-right px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Policies</th>
                    <th className="text-right px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Expiring Premium</th>
                    <th className="text-right px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Projected Commission</th>
                    <th className="text-right px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Actual Commission</th>
                    <th className="text-right px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Variance</th>
                    <th className="text-center px-4 py-3 text-xs uppercase tracking-wider" style={{ color: '#64748b' }}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {months.map((m) => (
                    <React.Fragment key={m.month}>
                      <tr
                        className="transition-colors cursor-pointer"
                        style={{ borderBottom: '1px solid rgba(14,165,233,0.05)' }}
                        onMouseOver={e => (e.currentTarget.style.background = 'rgba(14,165,233,0.04)')}
                        onMouseOut={e => (e.currentTarget.style.background = 'transparent')}
                        onClick={() => loadPolicies(m.month)}
                      >
                        <td className="px-6 py-4">
                          <span className="text-sm font-medium text-white">{m.label}</span>
                        </td>
                        <td className="text-right px-4 py-4 text-sm" style={{ color: '#94a3b8' }}>
                          {m.expiring_policy_count}
                        </td>
                        <td className="text-right px-4 py-4 text-sm" style={{ color: '#94a3b8' }}>
                          {fmt(m.expiring_premium)}
                        </td>
                        <td className="text-right px-4 py-4 text-sm font-medium" style={{ color: '#0ea5e9' }}>
                          {fmtFull(m.projected_commission)}
                        </td>
                        <td className="text-right px-4 py-4 text-sm font-medium" style={{ color: m.actual_commission > 0 ? '#10b981' : '#475569' }}>
                          {m.actual_commission > 0 ? fmtFull(m.actual_commission) : '—'}
                        </td>
                        <td className="text-right px-4 py-4">
                          {m.actual_commission > 0 ? (
                            <span className="inline-flex items-center gap-1 text-sm font-medium" style={{ color: m.variance >= 0 ? '#10b981' : '#ef4444' }}>
                              {m.variance >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                              {pct(m.variance_pct)}
                            </span>
                          ) : (
                            <span className="text-sm" style={{ color: '#475569' }}>—</span>
                          )}
                        </td>
                        <td className="text-center px-4 py-4">
                          <button className="p-1 rounded" style={{ color: '#64748b' }}>
                            {expandedMonth === m.month ? <ChevronUp className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </td>
                      </tr>

                      {/* Expanded policy detail */}
                      {expandedMonth === m.month && (
                        <tr>
                          <td colSpan={7} className="px-6 py-4" style={{ background: 'rgba(2,6,23,0.5)' }}>
                            {loadingPolicies ? (
                              <div className="flex justify-center py-4">
                                <div className="animate-spin rounded-full h-5 w-5 border-t-2" style={{ borderColor: '#0ea5e9' }} />
                              </div>
                            ) : (
                              <div>
                                <div className="text-xs font-medium mb-3" style={{ color: '#64748b' }}>
                                  {policies.length} policies expiring in {m.label}
                                </div>
                                <div className="max-h-80 overflow-y-auto">
                                  <table className="w-full">
                                    <thead>
                                      <tr>
                                        <th className="text-left px-3 py-2 text-xs" style={{ color: '#475569' }}>Client</th>
                                        <th className="text-left px-3 py-2 text-xs" style={{ color: '#475569' }}>Policy</th>
                                        <th className="text-left px-3 py-2 text-xs" style={{ color: '#475569' }}>Carrier</th>
                                        <th className="text-left px-3 py-2 text-xs" style={{ color: '#475569' }}>Type</th>
                                        <th className="text-right px-3 py-2 text-xs" style={{ color: '#475569' }}>Current Prem</th>
                                        <th className="text-right px-3 py-2 text-xs" style={{ color: '#475569' }}>Projected Prem</th>
                                        <th className="text-right px-3 py-2 text-xs" style={{ color: '#475569' }}>Proj Commission</th>
                                        <th className="text-left px-3 py-2 text-xs" style={{ color: '#475569' }}>Expires</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {policies.map((p, i) => (
                                        <tr key={i} style={{ borderBottom: '1px solid rgba(14,165,233,0.04)' }}>
                                          <td className="px-3 py-2 text-xs text-white">{p.client_name}</td>
                                          <td className="px-3 py-2 text-xs" style={{ color: '#94a3b8' }}>{p.policy_number}</td>
                                          <td className="px-3 py-2 text-xs" style={{ color: '#94a3b8' }}>{p.carrier}</td>
                                          <td className="px-3 py-2 text-xs" style={{ color: '#94a3b8' }}>{p.policy_type}</td>
                                          <td className="text-right px-3 py-2 text-xs" style={{ color: '#94a3b8' }}>{fmtFull(p.current_premium)}</td>
                                          <td className="text-right px-3 py-2 text-xs" style={{ color: '#0ea5e9' }}>{fmtFull(p.projected_renewal_premium)}</td>
                                          <td className="text-right px-3 py-2 text-xs font-medium" style={{ color: '#10b981' }}>{fmtFull(p.projected_commission)}</td>
                                          <td className="px-3 py-2 text-xs" style={{ color: '#64748b' }}>{p.expiration_date}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Assumptions footnote */}
            <div className="mt-4 px-2 text-xs" style={{ color: '#475569' }}>
              Projections assume all active policies renew at expiration with a 10% average rate increase.
              Agency commission calculated at 13% of renewed premium. Actual commission pulled from carrier
              renewal lines in uploaded statements. Does not include new business written.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
