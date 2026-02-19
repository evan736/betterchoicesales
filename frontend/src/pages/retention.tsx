import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { retentionAPI } from '../lib/api';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Cell
} from 'recharts';
import {
  Shield, AlertTriangle, Users, Building, Megaphone, ChevronDown
} from 'lucide-react';

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4'];

const RetentionPage = () => {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [overview, setOverview] = useState<any>(null);
  const [byAgent, setByAgent] = useState<any[]>([]);
  const [byCarrier, setByCarrier] = useState<any[]>([]);
  const [bySource, setBySource] = useState<any[]>([]);
  const [trend, setTrend] = useState<any[]>([]);
  const [earlyCancels, setEarlyCancels] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'agent' | 'carrier' | 'source' | 'list'>('overview');
  const [period, setPeriod] = useState<string>('');

  useEffect(() => {
    if (!authLoading && !user) { router.push('/'); return; }
    if (user) loadData();
  }, [user, authLoading, period]);

  const loadData = async () => {
    setLoading(true);
    try {
      const p = period || undefined;
      const [ovRes, agRes, caRes, srRes, trRes, ecRes] = await Promise.all([
        retentionAPI.overview(p),
        retentionAPI.byAgent(p),
        retentionAPI.byCarrier(p),
        retentionAPI.bySource(p),
        retentionAPI.trend(12),
        retentionAPI.earlyCancellations(120, p),
      ]);
      setOverview(ovRes.data);
      setByAgent(agRes.data);
      setByCarrier(caRes.data);
      setBySource(srRes.data);
      setTrend(trRes.data);
      setEarlyCancels(ecRes.data);
    } catch (err) {
      console.error('Failed to load retention data:', err);
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) return null;
  if (!user) return null;

  const tabs = [
    { key: 'overview', label: 'Overview', icon: Shield },
    { key: 'agent', label: 'By Agent', icon: Users },
    { key: 'carrier', label: 'By Carrier', icon: Building },
    { key: 'source', label: 'By Lead Source', icon: Megaphone },
    { key: 'list', label: 'Early Cancellations', icon: AlertTriangle },
  ];

  // Generate period options
  const periodOptions: { value: string; label: string }[] = [{ value: '', label: 'All Time' }];
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const label = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    periodOptions.push({ value: val, label });
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Retention Analytics</h1>
            <p className="text-sm text-slate-500">Track early terminations and retention rates</p>
          </div>
          <div className="relative">
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="appearance-none bg-white border border-slate-300 rounded-lg px-4 py-2 pr-8 text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500"
            >
              {periodOptions.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-2.5 top-3 text-slate-400 pointer-events-none" />
          </div>
        </div>

        {/* Tabs */}
        <div className="flex space-x-1 bg-white rounded-xl p-1 shadow-sm border border-slate-200 mb-6">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as any)}
              className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab.key
                  ? 'bg-green-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <tab.icon size={16} />
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center py-20 text-slate-500">Loading retention data...</div>
        ) : (
          <>
            {activeTab === 'overview' && overview && (
              <div className="space-y-6">
                {/* Summary Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <StatCard label="Total Policies" value={overview.total_sales} />
                  <StatCard label="Active" value={overview.total_active} color="text-green-700" />
                  <StatCard label="Cancelled" value={overview.total_cancelled} color="text-red-600" />
                  <StatCard label="Retention Rate" value={`${overview.retention_rate}%`}
                    color={overview.retention_rate >= 85 ? 'text-green-700' : overview.retention_rate >= 70 ? 'text-amber-600' : 'text-red-600'} />
                </div>

                {/* Charts Row */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Cancellation Buckets */}
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
                    <h3 className="font-semibold text-slate-800 mb-4">Cancellations by Time Period</h3>
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={overview.bucket_chart_data}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 12 }} />
                        <Tooltip />
                        <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                          {overview.bucket_chart_data.map((_: any, i: number) => (
                            <Cell key={i} fill={COLORS[i]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Retention Trend */}
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
                    <h3 className="font-semibold text-slate-800 mb-4">Monthly Retention Rate Trend</h3>
                    <ResponsiveContainer width="100%" height={280}>
                      <LineChart data={trend}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
                        <Tooltip formatter={(v: any) => [`${v}%`, 'Retention Rate']} />
                        <Line type="monotone" dataKey="retention_rate" stroke="#16a34a" strokeWidth={2.5} dot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'agent' && (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="p-5 border-b border-slate-200">
                  <h3 className="font-semibold text-slate-800">Retention by Agent</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left py-3 px-4 font-semibold text-slate-600">Agent</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Total</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Active</th>
                        <th className="text-right py-3 px-4 font-semibold text-red-600">Cancelled</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Retention</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">0-30d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">31-60d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">61-90d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">91-120d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byAgent.map((a: any, i: number) => (
                        <tr key={a.agent_id} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                          <td className="py-2.5 px-4 font-medium">{a.agent_name}</td>
                          <td className="py-2.5 px-4 text-right">{a.total_sales}</td>
                          <td className="py-2.5 px-4 text-right text-green-700">{a.active}</td>
                          <td className="py-2.5 px-4 text-right text-red-600">{a.cancelled}</td>
                          <td className="py-2.5 px-4 text-right">
                            <RetentionBadge rate={a.retention_rate} />
                          </td>
                          <td className="py-2.5 px-4 text-right">{a.cancel_30 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{a.cancel_60 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{a.cancel_90 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{a.cancel_120 || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {byAgent.length > 0 && (
                  <div className="p-5 border-t border-slate-200">
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={byAgent} layout="vertical">
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                        <YAxis type="category" dataKey="agent_name" width={120} tick={{ fontSize: 12 }} />
                        <Tooltip formatter={(v: any) => [`${v}%`, 'Retention Rate']} />
                        <Bar dataKey="retention_rate" radius={[0, 6, 6, 0]}>
                          {byAgent.map((a: any, i: number) => (
                            <Cell key={i} fill={a.retention_rate >= 85 ? '#22c55e' : a.retention_rate >= 70 ? '#eab308' : '#ef4444'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'carrier' && (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="p-5 border-b border-slate-200">
                  <h3 className="font-semibold text-slate-800">Retention by Carrier</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left py-3 px-4 font-semibold text-slate-600">Carrier</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Total</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Active</th>
                        <th className="text-right py-3 px-4 font-semibold text-red-600">Cancelled</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Retention</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">0-30d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">31-60d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">61-90d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">91-120d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byCarrier.map((c: any, i: number) => (
                        <tr key={c.carrier} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                          <td className="py-2.5 px-4 font-medium capitalize">{(c.carrier || '').replace('_', ' ')}</td>
                          <td className="py-2.5 px-4 text-right">{c.total_sales}</td>
                          <td className="py-2.5 px-4 text-right text-green-700">{c.active}</td>
                          <td className="py-2.5 px-4 text-right text-red-600">{c.cancelled}</td>
                          <td className="py-2.5 px-4 text-right"><RetentionBadge rate={c.retention_rate} /></td>
                          <td className="py-2.5 px-4 text-right">{c.cancel_30 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{c.cancel_60 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{c.cancel_90 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{c.cancel_120 || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {byCarrier.length > 0 && (
                  <div className="p-5 border-t border-slate-200">
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={byCarrier}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="carrier" tick={{ fontSize: 12 }} />
                        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                        <Tooltip formatter={(v: any) => [`${v}%`, 'Retention Rate']} />
                        <Bar dataKey="retention_rate" radius={[6, 6, 0, 0]}>
                          {byCarrier.map((c: any, i: number) => (
                            <Cell key={i} fill={c.retention_rate >= 85 ? '#22c55e' : c.retention_rate >= 70 ? '#eab308' : '#ef4444'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'source' && (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="p-5 border-b border-slate-200">
                  <h3 className="font-semibold text-slate-800">Retention by Lead Source</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left py-3 px-4 font-semibold text-slate-600">Lead Source</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Total</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Active</th>
                        <th className="text-right py-3 px-4 font-semibold text-red-600">Cancelled</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">Retention</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">0-30d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">31-60d</th>
                        <th className="text-right py-3 px-4 font-semibold text-slate-600">61-90d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bySource.map((s: any, i: number) => (
                        <tr key={s.lead_source} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                          <td className="py-2.5 px-4 font-medium capitalize">{(s.lead_source || '').replace('_', ' ')}</td>
                          <td className="py-2.5 px-4 text-right">{s.total_sales}</td>
                          <td className="py-2.5 px-4 text-right text-green-700">{s.active}</td>
                          <td className="py-2.5 px-4 text-right text-red-600">{s.cancelled}</td>
                          <td className="py-2.5 px-4 text-right"><RetentionBadge rate={s.retention_rate} /></td>
                          <td className="py-2.5 px-4 text-right">{s.cancel_30 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{s.cancel_60 || '—'}</td>
                          <td className="py-2.5 px-4 text-right">{s.cancel_90 || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'list' && (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="p-5 border-b border-slate-200">
                  <h3 className="font-semibold text-slate-800">Early Cancellations (within 120 days)</h3>
                  <p className="text-xs text-slate-500 mt-1">{earlyCancels.length} policies</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left py-2.5 px-3 font-semibold text-slate-600">Policy #</th>
                        <th className="text-left py-2.5 px-3 font-semibold text-slate-600">Client</th>
                        <th className="text-left py-2.5 px-3 font-semibold text-slate-600">Carrier</th>
                        <th className="text-left py-2.5 px-3 font-semibold text-slate-600">Producer</th>
                        <th className="text-left py-2.5 px-3 font-semibold text-slate-600">Source</th>
                        <th className="text-right py-2.5 px-3 font-semibold text-slate-600">Premium</th>
                        <th className="text-center py-2.5 px-3 font-semibold text-slate-600">Effective</th>
                        <th className="text-center py-2.5 px-3 font-semibold text-slate-600">Cancelled</th>
                        <th className="text-center py-2.5 px-3 font-semibold text-red-600">Days</th>
                        <th className="text-center py-2.5 px-3 font-semibold text-slate-600">Comm Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {earlyCancels.map((s: any, i: number) => (
                        <tr key={s.id} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                          <td className="py-2 px-3 font-mono">{s.policy_number}</td>
                          <td className="py-2 px-3">{s.client_name}</td>
                          <td className="py-2 px-3 capitalize">{(s.carrier || '').replace('_', ' ')}</td>
                          <td className="py-2 px-3">{s.producer}</td>
                          <td className="py-2 px-3 capitalize">{(s.lead_source || '').replace('_', ' ')}</td>
                          <td className="py-2 px-3 text-right">${(s.written_premium || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                          <td className="py-2 px-3 text-center">{s.effective_date || '—'}</td>
                          <td className="py-2 px-3 text-center">{s.cancelled_date || '—'}</td>
                          <td className="py-2 px-3 text-center">
                            <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-bold ${
                              s.days_to_cancel <= 30 ? 'bg-red-100 text-red-700' :
                              s.days_to_cancel <= 60 ? 'bg-orange-100 text-orange-700' :
                              s.days_to_cancel <= 90 ? 'bg-yellow-100 text-yellow-700' :
                              'bg-blue-100 text-blue-700'
                            }`}>
                              {s.days_to_cancel}d
                            </span>
                          </td>
                          <td className="py-2 px-3 text-center">
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                              s.commission_status === 'paid' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
                            }`}>
                              {s.commission_status === 'paid' ? 'Paid' : 'Pending'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
};

const StatCard: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color }) => (
  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 text-center">
    <div className={`text-2xl font-bold ${color || 'text-slate-900'}`}>{value}</div>
    <div className="text-xs text-slate-500 mt-1">{label}</div>
  </div>
);

const RetentionBadge: React.FC<{ rate: number }> = ({ rate }) => {
  const color = rate >= 85 ? 'bg-green-100 text-green-700' : rate >= 70 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700';
  return <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-bold ${color}`}>{rate}%</span>;
};

export default RetentionPage;
