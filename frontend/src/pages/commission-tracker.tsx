import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { commissionTrackerAPI } from '../lib/api';
import { DollarSign, AlertTriangle, CheckCircle, Clock, Search, RefreshCw, Flag, XCircle, ChevronDown, Loader2 } from 'lucide-react';
import { toast } from '../components/ui/Toast';

const STATUS_COLORS: Record<string, { bg: string; text: string; icon: any }> = {
  pending: { bg: 'bg-yellow-900/30 border-yellow-700/50', text: 'text-yellow-400', icon: <Clock size={14} /> },
  paid: { bg: 'bg-green-900/30 border-green-700/50', text: 'text-green-400', icon: <CheckCircle size={14} /> },
  overdue: { bg: 'bg-red-900/30 border-red-700/50', text: 'text-red-400', icon: <AlertTriangle size={14} /> },
  flagged: { bg: 'bg-orange-900/30 border-orange-700/50', text: 'text-orange-400', icon: <Flag size={14} /> },
  resolved: { bg: 'bg-slate-800/50 border-slate-600/50', text: 'text-slate-400', icon: <CheckCircle size={14} /> },
};

export default function CommissionTracker() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [carrierFilter, setCarrierFilter] = useState<string>('');
  const [scanning, setScanning] = useState(false);
  const [matching, setMatching] = useState(false);
  const [resolveModal, setResolveModal] = useState<any>(null);
  const [flagModal, setFlagModal] = useState<any>(null);
  const [modalText, setModalText] = useState('');

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) {
      if (user.role !== 'admin' && user.role !== 'manager') {
        router.push('/sales');
        return;
      }
      loadData();
    }
  }, [user, loading]);

  const loadData = async () => {
    try {
      setLoadingData(true);
      const params: any = {};
      if (statusFilter) params.status = statusFilter;
      if (carrierFilter) params.carrier = carrierFilter;
      const res = await commissionTrackerAPI.dashboard(params);
      setData(res.data);
    } catch (e: any) {
      toast.error('Failed to load commission tracker');
    } finally {
      setLoadingData(false);
    }
  };

  useEffect(() => { if (user) loadData(); }, [statusFilter, carrierFilter]);

  const handleScan = async () => {
    setScanning(true);
    try {
      const salesRes = await commissionTrackerAPI.scanSales();
      const renewalRes = await commissionTrackerAPI.scanRenewals();
      const sc = salesRes.data.created || 0;
      const rc = renewalRes.data.created || 0;
      toast.info(`Scan complete: ${sc} new business + ${rc} renewals created`);
      await loadData();
    } catch (e: any) {
      toast.error('Scan failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setScanning(false);
    }
  };

  const handleAutoMatch = async () => {
    setMatching(true);
    try {
      const res = await commissionTrackerAPI.autoMatch();
      const d = res.data;
      toast.info(`Matched: ${d.matched} paid, ${d.newly_overdue} newly overdue`);
      await loadData();
    } catch (e: any) {
      toast.error('Auto-match failed');
    } finally {
      setMatching(false);
    }
  };

  const handleResolve = async () => {
    if (!resolveModal || !modalText.trim()) return;
    try {
      await commissionTrackerAPI.resolve(resolveModal.id, modalText);
      toast.info('Resolved');
      setResolveModal(null);
      setModalText('');
      await loadData();
    } catch { toast.error('Failed to resolve'); }
  };

  const handleFlag = async () => {
    if (!flagModal || !modalText.trim()) return;
    try {
      await commissionTrackerAPI.flag(flagModal.id, modalText);
      toast.info('Flagged');
      setFlagModal(null);
      setModalText('');
      await loadData();
    } catch { toast.error('Failed to flag'); }
  };

  if (loading || !user) return null;

  const summary = data?.summary || {};
  const items = data?.items || [];

  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Commission Tracker</h1>
            <p className="text-sm text-slate-400 mt-1">Expected vs actual commission payments across all carriers</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleScan}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-600 text-white hover:bg-cyan-700 transition-all text-sm font-semibold disabled:opacity-50"
            >
              {scanning ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {scanning ? 'Scanning...' : 'Scan Sales'}
            </button>
            <button
              onClick={handleAutoMatch}
              disabled={matching}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-all text-sm font-semibold disabled:opacity-50"
            >
              {matching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              {matching ? 'Matching...' : 'Auto-Match Statements'}
            </button>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <SummaryCard label="Pending" value={summary.pending || 0} color="text-yellow-400" bgColor="bg-yellow-900/20 border-yellow-800/40" icon={<Clock size={18} />} onClick={() => setStatusFilter(statusFilter === 'pending' ? '' : 'pending')} active={statusFilter === 'pending'} />
          <SummaryCard label="Paid" value={summary.paid || 0} color="text-green-400" bgColor="bg-green-900/20 border-green-800/40" icon={<CheckCircle size={18} />} onClick={() => setStatusFilter(statusFilter === 'paid' ? '' : 'paid')} active={statusFilter === 'paid'} />
          <SummaryCard label="Overdue" value={summary.overdue || 0} color="text-red-400" bgColor="bg-red-900/20 border-red-800/40" icon={<AlertTriangle size={18} />} onClick={() => setStatusFilter(statusFilter === 'overdue' ? '' : 'overdue')} active={statusFilter === 'overdue'} />
          <SummaryCard label="Flagged" value={summary.flagged || 0} color="text-orange-400" bgColor="bg-orange-900/20 border-orange-800/40" icon={<Flag size={18} />} onClick={() => setStatusFilter(statusFilter === 'flagged' ? '' : 'flagged')} active={statusFilter === 'flagged'} />
          <SummaryCard label="Resolved" value={summary.resolved || 0} color="text-slate-400" bgColor="bg-slate-800/40 border-slate-700/40" icon={<CheckCircle size={18} />} onClick={() => setStatusFilter(statusFilter === 'resolved' ? '' : 'resolved')} active={statusFilter === 'resolved'} />
        </div>

        {/* Financial Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
          <div className="bg-slate-900/60 border border-slate-700/50 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Expected Commission</p>
            <p className="text-2xl font-bold text-white mt-1">${(summary.total_expected_commission || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
          </div>
          <div className="bg-slate-900/60 border border-slate-700/50 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Confirmed Paid</p>
            <p className="text-2xl font-bold text-green-400 mt-1">${(summary.total_paid_commission || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
          </div>
          <div className="bg-slate-900/60 border border-slate-700/50 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Overdue Commission</p>
            <p className="text-2xl font-bold text-red-400 mt-1">${(summary.total_overdue_commission || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
          </div>
        </div>

        {/* Carrier Filter */}
        <div className="flex gap-2 mb-4 flex-wrap">
          {['', 'travelers', 'grange', 'national_general', 'liberty_mutual', 'progressive', 'geico'].map((c) => (
            <button
              key={c}
              onClick={() => setCarrierFilter(c)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                carrierFilter === c
                  ? 'bg-cyan-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-300 border border-slate-700'
              }`}
            >
              {c ? c.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'All Carriers'}
            </button>
          ))}
        </div>

        {/* Items Table */}
        {loadingData ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={32} className="animate-spin text-cyan-500" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-20">
            <DollarSign size={48} className="mx-auto text-slate-600 mb-3" />
            <p className="text-slate-400 text-lg">No commission expectations found</p>
            <p className="text-slate-500 text-sm mt-1">Click "Scan Sales" to create expectations from your recent sales</p>
          </div>
        ) : (
          <div className="bg-slate-900/40 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Status</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Customer</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Policy #</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Carrier</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Type</th>
                    <th className="text-right py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Premium</th>
                    <th className="text-right py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Est. Commission</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Effective</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Days</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-semibold text-xs uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item: any) => {
                    const sc = STATUS_COLORS[item.status] || STATUS_COLORS.pending;
                    return (
                      <tr key={item.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-4">
                          <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border ${sc.bg} ${sc.text}`}>
                            {sc.icon}
                            {item.status}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-white font-medium">{item.customer_name}</td>
                        <td className="py-3 px-4 text-slate-300 font-mono text-xs">{item.policy_number}</td>
                        <td className="py-3 px-4 text-slate-300 capitalize">{(item.carrier || '').replace(/_/g, ' ')}</td>
                        <td className="py-3 px-4 text-slate-400 capitalize text-xs">
                          <span className="px-1.5 py-0.5 bg-slate-800 rounded text-slate-300">{item.source_type === 'new_business' ? 'New Biz' : 'Renewal'}</span>
                        </td>
                        <td className="py-3 px-4 text-right text-slate-300">${item.expected_premium.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</td>
                        <td className="py-3 px-4 text-right font-semibold text-cyan-400">
                          ${item.expected_commission.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          {item.status === 'paid' && item.matched_amount > 0 && (
                            <span className="block text-green-400 text-xs">Paid: ${item.matched_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-400 text-xs">{item.effective_date ? new Date(item.effective_date).toLocaleDateString() : '—'}</td>
                        <td className="py-3 px-4">
                          {item.days_since_effective != null && (
                            <span className={`text-xs font-semibold ${item.days_since_effective > 45 ? 'text-red-400' : item.days_since_effective > 30 ? 'text-yellow-400' : 'text-slate-400'}`}>
                              {item.days_since_effective}d
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex gap-1">
                            {(item.status === 'overdue' || item.status === 'pending') && (
                              <button
                                onClick={() => { setFlagModal(item); setModalText(''); }}
                                className="p-1.5 rounded hover:bg-orange-900/30 text-orange-400 transition-colors"
                                title="Flag for follow-up"
                              >
                                <Flag size={14} />
                              </button>
                            )}
                            {(item.status === 'overdue' || item.status === 'flagged') && (
                              <button
                                onClick={() => { setResolveModal(item); setModalText(''); }}
                                className="p-1.5 rounded hover:bg-green-900/30 text-green-400 transition-colors"
                                title="Resolve"
                              >
                                <CheckCircle size={14} />
                              </button>
                            )}
                          </div>
                          {item.flag_reason && (
                            <p className="text-[10px] text-orange-400/70 mt-1 max-w-[200px] truncate" title={item.flag_reason}>{item.flag_reason}</p>
                          )}
                          {item.resolution_notes && (
                            <p className="text-[10px] text-green-400/70 mt-1 max-w-[200px] truncate" title={item.resolution_notes}>{item.resolution_notes}</p>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* Resolve Modal */}
      {resolveModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setResolveModal(null)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white mb-1">Resolve: {resolveModal.customer_name}</h3>
            <p className="text-sm text-slate-400 mb-4">{resolveModal.policy_number} · ${resolveModal.expected_commission?.toFixed(2)} expected</p>
            <textarea
              value={modalText}
              onChange={e => setModalText(e.target.value)}
              placeholder="Resolution notes (e.g., confirmed paid on April statement, policy cancelled, etc.)"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 outline-none"
              rows={3}
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setResolveModal(null)} className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">Cancel</button>
              <button onClick={handleResolve} disabled={!modalText.trim()} className="px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-semibold hover:bg-green-700 disabled:opacity-50 transition-all">Resolve</button>
            </div>
          </div>
        </div>
      )}

      {/* Flag Modal */}
      {flagModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setFlagModal(null)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white mb-1">Flag: {flagModal.customer_name}</h3>
            <p className="text-sm text-slate-400 mb-4">{flagModal.policy_number} · ${flagModal.expected_commission?.toFixed(2)} expected</p>
            <textarea
              value={modalText}
              onChange={e => setModalText(e.target.value)}
              placeholder="Flag reason (e.g., need to call carrier, customer hasn't paid yet, etc.)"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-orange-500 focus:border-orange-500 outline-none"
              rows={3}
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setFlagModal(null)} className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">Cancel</button>
              <button onClick={handleFlag} disabled={!modalText.trim()} className="px-4 py-2 rounded-lg bg-orange-600 text-white text-sm font-semibold hover:bg-orange-700 disabled:opacity-50 transition-all">Flag</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value, color, bgColor, icon, onClick, active }: any) {
  return (
    <button
      onClick={onClick}
      className={`${bgColor} border rounded-xl p-4 text-left transition-all hover:scale-[1.02] ${active ? 'ring-2 ring-cyan-500' : ''}`}
    >
      <div className="flex items-center justify-between">
        <span className={`${color}`}>{icon}</span>
        <span className={`text-2xl font-bold ${color}`}>{value}</span>
      </div>
      <p className="text-xs text-slate-400 mt-2 font-semibold uppercase tracking-wider">{label}</p>
    </button>
  );
}
