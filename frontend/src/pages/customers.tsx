import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { customersAPI, nonpayAPI } from '../lib/api';
import {
  Search, RefreshCw, ChevronDown, ChevronUp, User, Users, Phone, Mail, MapPin,
  Calendar, DollarSign, Loader2, AlertCircle, CheckCircle2,
  FileText, AlertTriangle, Merge, X, Upload, Clock, Send, Ban
} from 'lucide-react';

export default function CustomersPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [customers, setCustomers] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [stats, setStats] = useState<any>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [ncStatus, setNcStatus] = useState<any>(null);
  const [syncing, setSyncing] = useState(false);
  const [expandedId, setExpandedId] = useState<number | string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [duplicates, setDuplicates] = useState<any[]>([]);
  const [dupsLoading, setDupsLoading] = useState(false);
  const [merging, setMerging] = useState(false);

  // Non-pay automation
  const [showNonPay, setShowNonPay] = useState(false);
  const [nonpayUploading, setNonpayUploading] = useState(false);
  const [nonpayResult, setNonpayResult] = useState<any>(null);
  const [nonpayDryRun, setNonpayDryRun] = useState(true);
  const [nonpayHistory, setNonpayHistory] = useState<any[]>([]);
  const [nonpayHistLoading, setNonpayHistLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
    else if (user) { loadStatus(); loadStats(); }
  }, [user, authLoading]);

  const loadStatus = async () => { try { const r = await customersAPI.nowcertsStatus(); setNcStatus(r.data); } catch {} };
  const loadStats = async () => { setStatsLoading(true); try { const r = await customersAPI.agencyStats(); setStats(r.data); } catch {} setStatsLoading(false); };

  const doSearch = useCallback(async (q?: string, p?: number) => {
    const query = q ?? searchQuery;
    if (!query.trim()) return;
    setLoading(true); setHasSearched(true);
    try {
      const res = await customersAPI.search({ q: query, source: 'local', page: p ?? page, page_size: 50 });
      setCustomers(res.data.customers || []); setTotal(res.data.total || 0);
    } catch {} setLoading(false);
  }, [searchQuery, page]);

  const handleSearch = (e: React.FormEvent) => { e.preventDefault(); setPage(1); doSearch(searchQuery, 1); };

  const handleExpand = async (customer: any) => {
    const key = customer.id || customer.nowcerts_insured_id;
    if (expandedId === key) { setExpandedId(null); setDetail(null); return; }
    setExpandedId(key);
    if (customer.id) {
      setDetailLoading(true);
      try { const r = await customersAPI.get(customer.id); setDetail(r.data); } catch {}
      setDetailLoading(false);
    }
  };

  const handleSync = async (id: number) => {
    setDetailLoading(true);
    try { const r = await customersAPI.sync(id); setDetail(r.data); } catch (e: any) { alert(e.response?.data?.detail || 'Sync failed'); }
    setDetailLoading(false);
  };

  const handleSyncAll = async () => {
    if (!confirm('Pull all customers from NowCerts? This may take a few minutes.')) return;
    setSyncing(true);
    try {
      const r = await customersAPI.syncAll();
      alert(`Sync complete!\n${r.data.imported} imported, ${r.data.updated} updated\n${r.data.policies_imported} policies imported, ${r.data.policies_updated} policies updated`);
      loadStats();
    } catch (e: any) { alert(e.response?.data?.detail || 'Sync failed'); }
    setSyncing(false);
  };

  const loadDuplicates = async () => {
    setShowDuplicates(true); setDupsLoading(true);
    try { const r = await customersAPI.duplicates(); setDuplicates(r.data.duplicate_sets || []); } catch {}
    setDupsLoading(false);
  };

  const handleMerge = async (keepId: number, mergeIds: number[]) => {
    if (!confirm(`Merge ${mergeIds.length} duplicate(s) into the selected customer? This cannot be undone.`)) return;
    setMerging(true);
    try {
      const r = await customersAPI.merge(keepId, mergeIds);
      alert(`Merged! ${r.data.policies_moved} policies moved, ${r.data.customers_deleted} duplicates removed.`);
      loadDuplicates(); loadStats();
    } catch (e: any) { alert(e.response?.data?.detail || 'Merge failed'); }
    setMerging(false);
  };

  const openNonPay = async () => {
    setShowNonPay(true);
    setNonpayResult(null);
    loadNonpayHistory();
  };

  const loadNonpayHistory = async () => {
    setNonpayHistLoading(true);
    try { const r = await nonpayAPI.history(10); setNonpayHistory(r.data.notices || []); } catch {}
    setNonpayHistLoading(false);
  };

  const handleNonpayUpload = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'csv', 'tsv', 'txt', 'xlsx', 'xls'].includes(ext || '')) {
      alert('Please upload a PDF, CSV, or Excel file.'); return;
    }
    setNonpayUploading(true); setNonpayResult(null);
    try {
      const r = await nonpayAPI.upload(file, nonpayDryRun);
      setNonpayResult(r.data);
      loadNonpayHistory();
    } catch (e: any) { alert(e.response?.data?.detail || e.response?.data?.message || e.message || 'Upload failed. Check Render logs for details.'); }
    setNonpayUploading(false);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleNonpayUpload(file);
  };

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleNonpayUpload(file);
    e.target.value = '';
  };

  if (authLoading || !user) return null;
  const isAdmin = user.role?.toLowerCase() === 'admin';
  const fmt = (n: number) => n?.toLocaleString('en-US') ?? '0';
  const fmtMoney = (n: number) => '$' + (n || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="font-display text-4xl font-bold text-slate-900 mb-1">Customers</h1>
            <p className="text-slate-600">Agency customer directory</p>
          </div>
          <div className="flex items-center gap-3">
            {ncStatus && (
              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold ${ncStatus.connected ? 'bg-green-100 text-green-800' : ncStatus.configured ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-500'}`}>
                {ncStatus.connected ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                NowCerts {ncStatus.connected ? 'Connected' : ncStatus.configured ? 'Auth Error' : 'Not Configured'}
              </div>
            )}
            {isAdmin && (
              <>
                <button onClick={openNonPay} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-50 text-red-700 hover:bg-red-100 border border-red-200">
                  <Ban size={14} /> Non-Pay
                </button>
                <button onClick={loadDuplicates} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-50 text-amber-700 hover:bg-amber-100 border border-amber-200">
                  <AlertTriangle size={14} /> Duplicates
                </button>
                <button onClick={handleSyncAll} disabled={syncing} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
                  {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  {syncing ? 'Syncing...' : 'Sync All from NowCerts'}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Agency Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          <StatCard icon={<Users size={20} />} label="Total Customers" value={statsLoading ? '...' : fmt(stats?.total_customers)} color="blue" />
          <StatCard icon={<CheckCircle2 size={20} />} label="Active Customers" value={statsLoading ? '...' : fmt(stats?.active_customers)} color="green" />
          <StatCard icon={<FileText size={20} />} label="Active Policies" value={statsLoading ? '...' : fmt(stats?.active_policies)} color="indigo" />
          <StatCard icon={<DollarSign size={20} />} label="Annual Premium" value={statsLoading ? '...' : fmtMoney(stats?.total_active_premium_annualized)} color="emerald" />
          <StatCard icon={<Calendar size={20} />} label="Last Sync" value={statsLoading ? '...' : (stats?.last_sync ? new Date(stats.last_sync).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Never')} color="slate" />
        </div>

        {/* Search Bar */}
        <form onSubmit={handleSearch} className="card p-4 mb-6">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name, email, phone, or address..."
                className="w-full pl-10 pr-4 py-3 rounded-lg border border-slate-200 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500" />
            </div>
            <button type="submit" disabled={!searchQuery.trim()} className="btn-primary px-6 py-3 flex items-center gap-2 disabled:opacity-40">
              <Search size={16} /> Search
            </button>
          </div>
        </form>

        {/* Results */}
        {loading ? (
          <div className="text-center py-16 text-slate-500"><Loader2 size={24} className="animate-spin mx-auto mb-3" />Searching...</div>
        ) : hasSearched && customers.length === 0 ? (
          <div className="text-center py-16 text-slate-500"><User size={32} className="mx-auto mb-3 opacity-40" /><p className="font-semibold">No customers found</p><p className="text-sm mt-1">Try a different search term</p></div>
        ) : hasSearched ? (
          <>
            <p className="text-sm text-slate-500 mb-3">{fmt(total)} result{total !== 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;</p>
            <div className="space-y-2">
              {customers.map((c, idx) => {
                const key = c.id || c.nowcerts_insured_id || idx;
                const isExpanded = expandedId === key;
                return (
                  <div key={key} className="card overflow-hidden">
                    <button onClick={() => handleExpand(c)} className="w-full text-left p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                      <div className="flex items-center gap-4 flex-1 min-w-0">
                        <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0 ${c.has_active_policy ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
                          {(c.full_name || '?')[0]?.toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="font-bold text-slate-900 truncate">{c.full_name}</p>
                            {c.has_active_policy ? (
                              <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-semibold">Active</span>
                            ) : (
                              <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-semibold">Inactive</span>
                            )}
                            {c.is_prospect && <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-semibold">Prospect</span>}
                          </div>
                          <div className="flex items-center gap-4 text-xs text-slate-500 mt-0.5">
                            {c.email && <span className="flex items-center gap-1"><Mail size={11} />{c.email}</span>}
                            {c.phone && <span className="flex items-center gap-1"><Phone size={11} />{c.phone}</span>}
                            {c.city && c.state && <span className="flex items-center gap-1"><MapPin size={11} />{c.city}, {c.state}</span>}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {c.policy_count > 0 && <span className="text-xs text-slate-400">{c.policy_count} {c.policy_count === 1 ? 'policy' : 'policies'}</span>}
                        {c.agent_name && <span className="text-xs text-slate-400">{c.agent_name}</span>}
                        {isExpanded ? <ChevronUp size={18} className="text-slate-400" /> : <ChevronDown size={18} className="text-slate-400" />}
                      </div>
                    </button>
                    {isExpanded && (
                      <div className="border-t border-slate-200 bg-slate-50 p-5">
                        {detailLoading ? (
                          <div className="text-center py-8 text-slate-500"><Loader2 size={20} className="animate-spin mx-auto mb-2" />Loading...</div>
                        ) : detail ? (
                          <>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                              <InfoItem icon={<User size={14} />} label="Name" value={detail.customer?.full_name} />
                              <InfoItem icon={<Mail size={14} />} label="Email" value={detail.customer?.email} />
                              <InfoItem icon={<Phone size={14} />} label="Phone" value={detail.customer?.phone} />
                              <InfoItem icon={<Phone size={14} />} label="Mobile" value={detail.customer?.mobile_phone} />
                              <InfoItem icon={<MapPin size={14} />} label="Address" value={detail.customer?.address} />
                              <InfoItem icon={<MapPin size={14} />} label="City" value={detail.customer?.city ? `${detail.customer.city}, ${detail.customer.state} ${detail.customer.zip_code}` : null} />
                              <InfoItem icon={<User size={14} />} label="Agent" value={detail.customer?.agent_name} />
                              <InfoItem icon={<Calendar size={14} />} label="Last Synced" value={detail.customer?.last_synced_at ? new Date(detail.customer.last_synced_at).toLocaleDateString() : 'Never'} />
                            </div>
                            <div className="flex items-center justify-between mb-3">
                              <h3 className="font-bold text-slate-900">Policies ({detail.policies?.length || 0})</h3>
                              {detail.customer?.id && (
                                <button onClick={() => handleSync(detail.customer.id)} className="flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 font-semibold"><RefreshCw size={13} />Refresh from NowCerts</button>
                              )}
                            </div>
                            {detail.policies?.length > 0 ? (
                              <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                  <thead><tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                                    <th className="pb-2 font-semibold">Policy #</th><th className="pb-2 font-semibold">Carrier</th><th className="pb-2 font-semibold">Type</th><th className="pb-2 font-semibold">Status</th><th className="pb-2 font-semibold">Effective</th><th className="pb-2 font-semibold">Expires</th><th className="pb-2 font-semibold text-right">Premium</th>
                                  </tr></thead>
                                  <tbody>
                                    {detail.policies.map((p: any, i: number) => (
                                      <tr key={p.id || i} className="border-b border-slate-100">
                                        <td className="py-2.5 font-semibold text-slate-900">{p.policy_number || '—'}</td>
                                        <td className="py-2.5">{p.carrier || '—'}</td>
                                        <td className="py-2.5 capitalize">{p.line_of_business || p.policy_type || '—'}</td>
                                        <td className="py-2.5"><span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${p.status?.toLowerCase() === 'active' ? 'bg-green-100 text-green-700' : p.status?.toLowerCase() === 'cancelled' ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'}`}>{p.status || 'Unknown'}</span></td>
                                        <td className="py-2.5">{p.effective_date ? new Date(p.effective_date).toLocaleDateString() : '—'}</td>
                                        <td className="py-2.5">{p.expiration_date ? new Date(p.expiration_date).toLocaleDateString() : '—'}</td>
                                        <td className="py-2.5 text-right font-semibold">{p.premium ? `$${parseFloat(p.premium).toLocaleString()}` : '—'}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : <p className="text-sm text-slate-500 py-4 text-center">No policies found. Try refreshing from NowCerts.</p>}
                          </>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {total > 50 && (
              <div className="flex justify-center gap-2 mt-6">
                <button onClick={() => { setPage(p => Math.max(1, p - 1)); doSearch(searchQuery, Math.max(1, page - 1)); }} disabled={page <= 1} className="px-3 py-1.5 text-sm rounded border border-slate-200 disabled:opacity-30">Prev</button>
                <span className="px-3 py-1.5 text-sm text-slate-500">Page {page} of {Math.ceil(total / 50)}</span>
                <button onClick={() => { setPage(p => p + 1); doSearch(searchQuery, page + 1); }} disabled={page * 50 >= total} className="px-3 py-1.5 text-sm rounded border border-slate-200 disabled:opacity-30">Next</button>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-20 text-slate-400">
            <Search size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg font-semibold text-slate-500">Search for a customer</p>
            <p className="text-sm mt-1">Enter a name, email, phone number, or address</p>
          </div>
        )}

        {/* Duplicates Modal */}
        {showDuplicates && (
          <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[80vh] overflow-hidden flex flex-col">
              <div className="flex items-center justify-between p-5 border-b border-slate-200">
                <div><h2 className="text-xl font-bold text-slate-900">Potential Duplicates</h2><p className="text-sm text-slate-500 mt-0.5">{duplicates.length} group{duplicates.length !== 1 ? 's' : ''} found</p></div>
                <button onClick={() => setShowDuplicates(false)} className="p-2 hover:bg-slate-100 rounded-lg"><X size={20} /></button>
              </div>
              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {dupsLoading ? (
                  <div className="text-center py-12"><Loader2 size={24} className="animate-spin mx-auto mb-3" />Scanning...</div>
                ) : duplicates.length === 0 ? (
                  <div className="text-center py-12 text-slate-500"><CheckCircle2 size={32} className="mx-auto mb-3 text-green-500" /><p className="font-semibold">No duplicates found!</p></div>
                ) : duplicates.map((dup, di) => <DupGroup key={di} group={dup} onMerge={handleMerge} merging={merging} />)}
              </div>
            </div>
          </div>
        )}

        {/* Non-Pay Automation Modal */}
        {showNonPay && (
          <NonPayModal
            onClose={() => setShowNonPay(false)}
            uploading={nonpayUploading}
            result={nonpayResult}
            history={nonpayHistory}
            histLoading={nonpayHistLoading}
            dragOver={dragOver}
            setDragOver={setDragOver}
            onDrop={onDrop}
            onFileSelect={onFileSelect}
            fileInputRef={fileInputRef}
            dryRun={nonpayDryRun}
            setDryRun={setNonpayDryRun}
          />
        )}
      </main>
    </div>
  );
}

const StatCard: React.FC<{ icon: React.ReactNode; label: string; value: string; color: string }> = ({ icon, label, value, color }) => {
  const cls: Record<string, string> = { blue: 'text-blue-600 bg-blue-50', green: 'text-green-600 bg-green-50', indigo: 'text-indigo-600 bg-indigo-50', emerald: 'text-emerald-600 bg-emerald-50', slate: 'text-slate-600 bg-slate-100' };
  return (<div className="card p-4"><div className="flex items-center gap-3 mb-2"><div className={`p-2 rounded-lg ${cls[color] || cls.slate}`}>{icon}</div></div><p className="text-2xl font-bold text-slate-900">{value}</p><p className="text-xs text-slate-500 mt-0.5">{label}</p></div>);
};

const InfoItem: React.FC<{ icon: React.ReactNode; label: string; value: string | null | undefined }> = ({ icon, label, value }) => (
  <div><div className="flex items-center gap-1.5 text-xs text-slate-500 mb-0.5">{icon}{label}</div><p className="text-sm font-semibold text-slate-800">{value || '—'}</p></div>
);

const DupGroup: React.FC<{ group: any; onMerge: (k: number, m: number[]) => void; merging: boolean }> = ({ group, onMerge, merging }) => {
  const [keepId, setKeepId] = useState<number | null>(null);
  const lbl = group.match_type === 'name' ? 'Same Name' : group.match_type === 'phone' ? 'Same Phone' : 'Same Email';
  const custs = group.customers || [];
  return (
    <div className="border border-amber-200 rounded-xl bg-amber-50/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">{lbl}</span>
          <span className="text-sm text-slate-600 font-medium">&ldquo;{group.match_value}&rdquo;</span>
          <span className="text-xs text-slate-400">({custs.length} records)</span>
        </div>
        <button onClick={() => { if (!keepId) return alert('Select which customer to keep.'); onMerge(keepId, custs.map((c: any) => c.id).filter((id: number) => id !== keepId)); }}
          disabled={!keepId || merging} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"><Merge size={13} />Merge</button>
      </div>
      <div className="space-y-2">
        {custs.map((c: any) => (
          <label key={c.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer ${keepId === c.id ? 'border-brand-400 bg-brand-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
            <input type="radio" name={`dup-${group.match_value}`} checked={keepId === c.id} onChange={() => setKeepId(c.id)} className="accent-brand-600" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-sm text-slate-900">{c.full_name}</span>
                {c.has_active_policy && <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-semibold">Active</span>}
                <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">{c.policy_count} policies</span>
              </div>
              <div className="flex gap-4 text-xs text-slate-500 mt-0.5">
                {c.email && <span>{c.email}</span>}{c.phone && <span>{c.phone}</span>}{c.city && c.state && <span>{c.city}, {c.state}</span>}
              </div>
            </div>
            {keepId === c.id && <span className="text-xs font-semibold text-brand-600">KEEP</span>}
          </label>
        ))}
      </div>
    </div>
  );
};

/* ── Non-Pay Modal with tabs ──────────────────────── */

const NonPayModal: React.FC<{
  onClose: () => void;
  uploading: boolean;
  result: any;
  history: any[];
  histLoading: boolean;
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  onDrop: (e: React.DragEvent) => void;
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  dryRun: boolean;
  setDryRun: (v: boolean) => void;
}> = ({ onClose, uploading, result, history, histLoading, dragOver, setDragOver, onDrop, onFileSelect, fileInputRef, dryRun, setDryRun }) => {
  const [tab, setTab] = useState<'upload' | 'preview'>('upload');
  const [carriers, setCarriers] = useState<any[]>([]);
  const [selectedCarrier, setSelectedCarrier] = useState('');
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewSubject, setPreviewSubject] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [sendingTest, setSendingTest] = useState(false);

  const loadCarriers = async () => {
    try {
      const r = await nonpayAPI.carriers();
      setCarriers(r.data.carriers || []);
      if (r.data.carriers?.length && !selectedCarrier) {
        setSelectedCarrier(r.data.carriers[0].key);
      }
    } catch {}
  };

  const loadPreview = async (carrier: string) => {
    setPreviewLoading(true);
    try {
      const r = await nonpayAPI.preview({ carrier, client_name: 'John Smith', policy_number: 'AUT-12345678', amount_due: 247.50, due_date: '02/28/2026' });
      setPreviewHtml(r.data.html || '');
      setPreviewSubject(r.data.subject || '');
    } catch {}
    setPreviewLoading(false);
  };

  useEffect(() => { if (tab === 'preview' && carriers.length === 0) loadCarriers(); }, [tab]);
  useEffect(() => { if (tab === 'preview' && selectedCarrier) loadPreview(selectedCarrier); }, [selectedCarrier, tab]);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-200">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Non-Pay Automation</h2>
            <p className="text-sm text-slate-500 mt-0.5">Upload notices or preview email templates</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg"><X size={20} /></button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-200 px-5">
          <button onClick={() => setTab('upload')} className={`px-4 py-3 text-sm font-semibold border-b-2 transition-colors ${tab === 'upload' ? 'border-brand-500 text-brand-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
            <Upload size={14} className="inline mr-1.5 -mt-0.5" />Upload & Send
          </button>
          <button onClick={() => setTab('preview')} className={`px-4 py-3 text-sm font-semibold border-b-2 transition-colors ${tab === 'preview' ? 'border-brand-500 text-brand-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
            <Mail size={14} className="inline mr-1.5 -mt-0.5" />Preview Templates
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {tab === 'upload' ? (
            <>
              {/* Dry Run Toggle */}
              <div className={`flex items-center justify-between p-4 rounded-xl mb-4 ${dryRun ? 'bg-amber-50 border border-amber-200' : 'bg-green-50 border border-green-200'}`}>
                <div>
                  <p className={`font-semibold text-sm ${dryRun ? 'text-amber-800' : 'text-green-800'}`}>
                    {dryRun ? '🧪 Test Mode — No emails will be sent' : '🚀 Live Mode — Emails will be sent to customers'}
                  </p>
                  <p className={`text-xs mt-0.5 ${dryRun ? 'text-amber-600' : 'text-green-600'}`}>
                    {dryRun ? 'Upload a file to preview which customers would be emailed' : 'Emails will go out to real customer addresses'}
                  </p>
                </div>
                <button
                  onClick={() => setDryRun(!dryRun)}
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors ${dryRun ? 'bg-amber-400' : 'bg-green-500'}`}
                >
                  <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform ${dryRun ? 'translate-x-1' : 'translate-x-6'}`} />
                </button>
              </div>

              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
                  dragOver ? 'border-brand-500 bg-brand-50' : 'border-slate-300 hover:border-slate-400 hover:bg-slate-50'
                } ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <input ref={fileInputRef as any} type="file" accept=".pdf,.csv,.tsv,.txt,.xlsx,.xls" onChange={onFileSelect} className="hidden" />
                {uploading ? (
                  <><Loader2 size={36} className="mx-auto mb-3 text-brand-500 animate-spin" /><p className="font-semibold text-slate-700">Processing file...</p><p className="text-sm text-slate-500 mt-1">Extracting policies and sending emails</p></>
                ) : (
                  <><Upload size={36} className="mx-auto mb-3 text-slate-400" /><p className="font-semibold text-slate-700">Drop non-pay file here or click to browse</p><p className="text-sm text-slate-500 mt-1">Supports PDF, CSV, and Excel files</p></>
                )}
              </div>

              <div className="mt-4 p-4 bg-slate-50 rounded-xl text-sm text-slate-600">
                <p className="font-semibold text-slate-700 mb-2">How it works:</p>
                <div className="space-y-1.5">
                  <p>1. Upload your carrier non-pay report (PDF or CSV)</p>
                  <p>2. System extracts policy numbers and matches to customers</p>
                  <p>3. Carrier-branded past-due emails sent automatically</p>
                  <p>4. <strong>Rate limit:</strong> Max 1 email per policy per week</p>
                </div>
              </div>

              {/* Upload result */}
              {result && (
                  <div className={`mt-5 border rounded-xl overflow-hidden ${result.dry_run ? 'border-amber-200' : 'border-slate-200'}`}>
                    <div className={`p-4 border-b ${result.dry_run ? 'bg-amber-50 border-amber-200' : 'bg-slate-50 border-slate-200'}`}>
                      <h3 className="font-bold text-slate-900">
                        {result.dry_run ? '🧪 Test Results — No emails were sent' : 'Processing Results'}
                      </h3>
                    </div>
                  <div className="p-4">
                    <div className="grid grid-cols-4 gap-3 mb-4">
                      <div className="text-center p-3 bg-blue-50 rounded-lg"><p className="text-xl font-bold text-blue-700">{result.policies_found}</p><p className="text-xs text-blue-600">Found</p></div>
                      <div className="text-center p-3 bg-green-50 rounded-lg"><p className="text-xl font-bold text-green-700">{result.policies_matched}</p><p className="text-xs text-green-600">Matched</p></div>
                      <div className={`text-center p-3 rounded-lg ${result.dry_run ? 'bg-amber-50' : 'bg-emerald-50'}`}>
                        <p className={`text-xl font-bold ${result.dry_run ? 'text-amber-700' : 'text-emerald-700'}`}>
                          {result.dry_run ? result.details?.filter((d: any) => d.would_send).length || 0 : result.emails_sent}
                        </p>
                        <p className={`text-xs ${result.dry_run ? 'text-amber-600' : 'text-emerald-600'}`}>{result.dry_run ? 'Would Send' : 'Sent'}</p>
                      </div>
                      <div className="text-center p-3 bg-amber-50 rounded-lg"><p className="text-xl font-bold text-amber-700">{result.emails_skipped}</p><p className="text-xs text-amber-600">Skipped</p></div>
                    </div>
                    {result.details?.length > 0 && (
                      <div className="max-h-60 overflow-y-auto">
                        <table className="w-full text-xs"><thead><tr className="text-left text-slate-500 border-b"><th className="pb-2 font-semibold">Policy</th><th className="pb-2 font-semibold">Customer</th><th className="pb-2 font-semibold">Email</th><th className="pb-2 font-semibold">Status</th></tr></thead>
                          <tbody>{result.details.map((d: any, i: number) => (
                            <tr key={i} className="border-b border-slate-100">
                              <td className="py-2 font-mono font-semibold">{d.policy_number}</td>
                              <td className="py-2">{d.customer_name || <span className="text-slate-400">—</span>}</td>
                              <td className="py-2 text-slate-500">{d.customer_email || '—'}</td>
                              <td className="py-2">
                                {d.would_send ? <span className="flex items-center gap-1 text-amber-600">✓ Would email {d.customer_email}</span>
                                : d.email_sent ? <span className="flex items-center gap-1 text-green-600"><Send size={11} />Sent to {d.customer_email}</span>
                                : d.skipped_rate_limit ? <span className="flex items-center gap-1 text-amber-600"><Clock size={11} />Sent recently</span>
                                : <span className="text-red-500">{d.error || 'Not matched'}</span>}
                              </td>
                            </tr>
                          ))}</tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* History */}
              <div className="mt-5">
                <h3 className="font-bold text-slate-900 mb-3">Recent Uploads</h3>
                {histLoading ? <div className="text-center py-6"><Loader2 size={18} className="animate-spin mx-auto" /></div>
                : history.length === 0 ? <p className="text-sm text-slate-500 text-center py-6">No uploads yet</p>
                : <div className="space-y-2">{history.map((n) => (
                    <div key={n.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg text-sm">
                      <div><span className="font-semibold text-slate-800">{n.filename}</span><span className="text-slate-400 ml-2">{n.uploaded_by}</span></div>
                      <div className="flex items-center gap-4 text-xs text-slate-500">
                        <span>{n.policies_found} found</span><span className="text-green-600">{n.emails_sent} sent</span>
                        {n.emails_skipped > 0 && <span className="text-amber-600">{n.emails_skipped} skipped</span>}
                        <span>{n.created_at ? new Date(n.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : ''}</span>
                      </div>
                    </div>
                  ))}</div>}
              </div>
            </>
          ) : (
            /* Preview Templates tab */
            <>
              <div className="flex gap-4 mb-4">
                <div className="w-56 flex-shrink-0">
                  <label className="text-xs font-semibold text-slate-500 mb-1.5 block">Select Carrier</label>
                  <select
                    value={selectedCarrier}
                    onChange={(e) => setSelectedCarrier(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:ring-2 focus:ring-brand-500"
                  >
                    <option value="">Generic (No Carrier)</option>
                    {carriers.map((c) => (
                      <option key={c.key} value={c.key}>{c.display_name}</option>
                    ))}
                  </select>
                  <p className="text-[11px] text-slate-400 mt-1.5">Sample data: John Smith, $247.50 due</p>
                </div>
                <div className="flex-1">
                  {previewSubject && (
                    <div className="mb-2">
                      <label className="text-xs font-semibold text-slate-500">Subject Line:</label>
                      <p className="text-sm font-semibold text-slate-800 mt-0.5">{previewSubject}</p>
                    </div>
                  )}
                  <label className="text-xs font-semibold text-slate-500 mb-1.5 block">Send Test Email</label>
                  <div className="flex gap-2">
                    <input
                      type="email"
                      value={testEmail}
                      onChange={(e) => setTestEmail(e.target.value)}
                      placeholder="your@email.com"
                      className="flex-1 px-3 py-2 rounded-lg border border-slate-200 text-sm focus:ring-2 focus:ring-brand-500"
                    />
                    <button
                      onClick={async () => {
                        if (!testEmail) return;
                        setSendingTest(true);
                        try {
                          const r = await nonpayAPI.sendTest({ to_email: testEmail, carrier: selectedCarrier || '' });
                          if (r.data.success) alert(`Test email sent to ${testEmail}!`);
                          else alert(`Failed: ${r.data.error || 'Unknown error'}`);
                        } catch (e: any) { alert(e.response?.data?.detail || 'Send failed'); }
                        setSendingTest(false);
                      }}
                      disabled={!testEmail || sendingTest}
                      className="px-4 py-2 rounded-lg text-sm font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40 flex items-center gap-1.5"
                    >
                      {sendingTest ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                      Send
                    </button>
                  </div>
                </div>
              </div>

              {previewLoading ? (
                <div className="text-center py-12"><Loader2 size={24} className="animate-spin mx-auto mb-3" />Loading preview...</div>
              ) : previewHtml ? (
                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <iframe
                    srcDoc={previewHtml}
                    className="w-full border-0"
                    style={{ height: '600px' }}
                    title="Email Preview"
                    sandbox="allow-same-origin"
                  />
                </div>
              ) : (
                <div className="text-center py-12 text-slate-500">Select a carrier to preview the email template</div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
