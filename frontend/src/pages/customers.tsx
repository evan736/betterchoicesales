import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import USHeatmap from '../components/USHeatmap';
import { customersAPI, nonpayAPI, miaAPI, reshopAPI } from '../lib/api';
import {
  Search, RefreshCw, ChevronDown, ChevronUp, User, Users, Phone, Mail, MapPin,
  Calendar, DollarSign, Loader2, AlertCircle, CheckCircle2,
  FileText, AlertTriangle, Merge, X, Upload, Clock, Send, Ban, ExternalLink, TrendingUp,
  Shield, ShieldCheck, ShieldOff, Zap, Paperclip, Copy, ChevronRight, Eye, EyeOff, Target,
  Pencil, Save
} from 'lucide-react';

const CARRIER_DISPLAY: Record<string, string> = {
  'integon natl': 'National General', 'integon natl ins': 'National General',
  'integon national': 'National General', 'integon': 'National General',
  'ngic': 'National General', 'nat gen': 'National General',
};
function normCarrier(c: string | null): string {
  if (!c) return '—';
  return CARRIER_DISPLAY[c.toLowerCase().trim()] || c;
}

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
  const [copiedPolicy, setCopiedPolicy] = useState<string | null>(null);
  const [driversData, setDriversData] = useState<any>(null);
  const [driversLoading, setDriversLoading] = useState(false);
  const [driversOpen, setDriversOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailSubject, setEmailSubject] = useState('');
  const [emailBody, setEmailBody] = useState('');
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [emailSendAs, setEmailSendAs] = useState<'service' | 'personal'>('service');
  const [emailFiles, setEmailFiles] = useState<File[]>([]);
  const [emailCc, setEmailCc] = useState('');
  const emailFileRef = useRef<HTMLInputElement>(null);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [showCancelled, setShowCancelled] = useState(false);
  const [duplicates, setDuplicates] = useState<any[]>([]);
  const [dupsLoading, setDupsLoading] = useState(false);
  const [merging, setMerging] = useState(false);

  // Inline edit customer fields
  const [editing, setEditing] = useState(false);
  const [editFields, setEditFields] = useState<Record<string, string>>({});
  const [editSaving, setEditSaving] = useState(false);
  const [editMsg, setEditMsg] = useState<{type: 'success' | 'error', text: string} | null>(null);
  const [pushToNowCerts, setPushToNowCerts] = useState(true);

  // Non-pay automation
  const [showNonPay, setShowNonPay] = useState(false);
  const [nonpayUploading, setNonpayUploading] = useState(false);
  const [nonpayResult, setNonpayResult] = useState<any>(null);
  const [nonpayDryRun, setNonpayDryRun] = useState(true);
  const [nonpayHistory, setNonpayHistory] = useState<any[]>([]);
  const [nonpayHistLoading, setNonpayHistLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [nonpayCarrierOverride, setNonpayCarrierOverride] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // MIA Quick Temp Auth
  const [quickAuthPhone, setQuickAuthPhone] = useState('');
  const [quickAuthName, setQuickAuthName] = useState('');
  const [quickAuthDuration, setQuickAuthDuration] = useState(60);
  const [quickAuthSubmitting, setQuickAuthSubmitting] = useState(false);
  const [quickAuthResult, setQuickAuthResult] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
    else if (user) { loadStatus(); loadStats(); }
  }, [user, authLoading]);

  // SSE live updates
  useEffect(() => {
    if (!user) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${baseUrl}/api/events/stream`);
      es.addEventListener('customers:updated', () => { loadStats(); if (hasSearched) doSearch(); });
      es.onerror = () => es?.close();
    } catch {}
    return () => es?.close();
  }, [user, hasSearched]);

  const loadStatus = async () => { try { const r = await customersAPI.nowcertsStatus(); setNcStatus(r.data); } catch {} };
  const loadStats = async () => { setStatsLoading(true); try { const r = await customersAPI.agencyStats(); setStats(r.data); } catch {} setStatsLoading(false); };

  const doSearch = useCallback(async (q?: string, p?: number) => {
    const query = q ?? searchQuery;
    if (!query.trim()) return;
    setLoading(true); setHasSearched(true);
    try {
      const res = await customersAPI.search({ q: query, source: 'local', page: p ?? page, page_size: 50 });
      if ((res.data.total || 0) === 0 && query.trim().length >= 3) {
        // No local results — try NowCerts live search
        try {
          const ncRes = await customersAPI.search({ q: query, source: 'nowcerts', page: 1, page_size: 50 });
          setCustomers(ncRes.data.customers || []); setTotal(ncRes.data.total || 0);
        } catch {
          setCustomers([]); setTotal(0);
        }
      } else {
        setCustomers(res.data.customers || []); setTotal(res.data.total || 0);
      }
    } catch {} setLoading(false);
  }, [searchQuery, page]);

  const handleSearch = (e: React.FormEvent) => { e.preventDefault(); setPage(1); doSearch(searchQuery, 1); };

  const handleExpand = async (customer: any) => {
    const key = customer.id || customer.nowcerts_insured_id;
    if (expandedId === key) { setExpandedId(null); setDetail(null); setDriversData(null); setDriversOpen(false); setEditing(false); setEditMsg(null); return; }
    setExpandedId(key);
    setDriversData(null); setDriversOpen(false); setEditing(false); setEditMsg(null);
    if (customer.id) {
      setDetailLoading(true);
      try { const r = await customersAPI.get(customer.id); setDetail(r.data); } catch {}
      setDetailLoading(false);
    }
  };

  const loadDrivers = async (customerId: number) => {
    setDriversLoading(true);
    try {
      const r = await customersAPI.drivers(customerId);
      setDriversData(r.data);
    } catch (e: any) {
      console.error('Failed to load drivers:', e);
      setDriversData({ people: [], error: e.response?.data?.detail || 'Failed to load' });
    }
    setDriversLoading(false);
  };

  const handleSync = async (id: number) => {
    setDetailLoading(true);
    try { const r = await customersAPI.sync(id); setDetail(r.data); } catch (e: any) { alert(e.response?.data?.detail || 'Sync failed'); }
    setDetailLoading(false);
  };

  // Start editing customer fields
  const startEditing = () => {
    const c = detail?.customer;
    if (!c) return;
    setEditFields({
      email: c.email || '',
      phone: c.phone || '',
      mobile_phone: c.mobile_phone || '',
      address: c.address || '',
      city: c.city || '',
      state: c.state || '',
      zip_code: c.zip_code || '',
    });
    setEditing(true);
    setEditMsg(null);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditFields({});
    setEditMsg(null);
  };

  const saveCustomerEdits = async () => {
    if (!detail?.customer?.id) return;
    setEditSaving(true);
    setEditMsg(null);
    try {
      const r = await customersAPI.update(detail.customer.id, editFields, pushToNowCerts);
      setDetail({ ...detail, customer: r.data.customer });
      setEditing(false);
      const ncOk = r.data.nowcerts_update?.success;
      setEditMsg({
        type: 'success',
        text: pushToNowCerts
          ? (ncOk ? 'Saved & pushed to NowCerts ✓' : 'Saved locally — NowCerts push failed')
          : 'Saved locally',
      });
      setTimeout(() => setEditMsg(null), 4000);
      // Also refresh the list item
      loadStats();
    } catch (e: any) {
      setEditMsg({ type: 'error', text: e.response?.data?.detail || 'Save failed' });
    }
    setEditSaving(false);
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

  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [showCarrierPrompt, setShowCarrierPrompt] = useState(false);

  const handleNonpayUpload = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'csv', 'tsv', 'txt', 'xlsx', 'xls'].includes(ext || '')) {
      alert('Please upload a PDF, CSV, or Excel file.'); return;
    }
    setNonpayUploading(true); setNonpayResult(null); setShowCarrierPrompt(false);
    try {
      // Always do dry run first to preview results
      const r = await nonpayAPI.upload(file, true, nonpayCarrierOverride);
      setNonpayResult(r.data);
      setPendingFile(file);
      loadNonpayHistory();

      // Check if any policies have no carrier detected
      const details = r.data.details || [];
      const noCarrier = details.filter((d: any) => !d.carrier || d.carrier === '' || d.carrier === 'unknown');
      if (noCarrier.length > 0 && !nonpayCarrierOverride) {
        setShowCarrierPrompt(true);
      }
    } catch (e: any) {
      console.error('Upload error full:', e);
      const msg = e.response?.data?.detail
        || e.response?.data?.message
        || (e.response ? `HTTP ${e.response.status}: ${JSON.stringify(e.response.data).slice(0,200)}` : `${e.message} — Open browser console (F12) for details`);
      alert(msg);
    }
    setNonpayUploading(false);
  };

  const handleNonpaySendLive = async () => {
    if (!pendingFile) return;
    setNonpayUploading(true); setShowCarrierPrompt(false);
    try {
      const r = await nonpayAPI.upload(pendingFile, false, nonpayCarrierOverride);
      setNonpayResult(r.data);
      setPendingFile(null);
      loadNonpayHistory();
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.response?.data?.message || 'Send failed';
      alert(msg);
    }
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

  if (authLoading || !user) return (
    <div className="min-h-screen">
      <div className="glass sticky top-0 z-50 border-b border-white/20 h-14" />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="h-10 w-64 rounded-lg bg-slate-200 animate-pulse mb-4" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          {[1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl bg-slate-200 animate-pulse" />)}
        </div>
        <div className="h-12 rounded-lg bg-slate-200 animate-pulse mb-4" />
        {[1,2,3,4,5].map(i => <div key={i} className="h-20 rounded-xl bg-slate-200 animate-pulse mb-3" />)}
      </main>
    </div>
  );
  const isAdmin = user.role?.toLowerCase() === 'admin';
  const fmt = (n: number) => n?.toLocaleString('en-US') ?? '0';
  const fmtMoney = (n: number) => '$' + (n || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

  const handleQuickAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    const digits = quickAuthPhone.replace(/\D/g, '');
    if (digits.length < 10) { setQuickAuthResult({ type: 'error', msg: 'Enter a valid 10-digit phone number' }); return; }
    setQuickAuthSubmitting(true); setQuickAuthResult(null);
    try {
      const r = await miaAPI.createAuth({
        phone: digits,
        customer_name: quickAuthName.trim() || undefined,
        duration_minutes: quickAuthDuration,
      });
      const label = quickAuthDuration >= 1440 ? `${quickAuthDuration / 1440}d` : quickAuthDuration >= 60 ? `${quickAuthDuration / 60}h` : `${quickAuthDuration}m`;
      setQuickAuthResult({ type: 'success', msg: `Authorized ${digits.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3')} for ${label}` });
      setQuickAuthPhone(''); setQuickAuthName('');
      setTimeout(() => setQuickAuthResult(null), 5000);
    } catch (e: any) {
      setQuickAuthResult({ type: 'error', msg: e.response?.data?.detail || 'Failed to authorize' });
    }
    setQuickAuthSubmitting(false);
  };

  return (
    <div className="min-h-screen bg-slate-50 overflow-x-hidden">
      <Navbar />
      <main className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 sm:mb-6">
          <div>
            <h1 className="font-display text-2xl sm:text-4xl font-bold text-slate-900 mb-0.5">Customers</h1>
            <p className="text-slate-600 text-xs sm:text-sm">Agency customer directory</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {ncStatus && (
              <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold ${ncStatus.connected ? 'bg-green-100 text-green-800' : ncStatus.configured ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-500'}`}>
                {ncStatus.connected ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                <span className="hidden sm:inline">NowCerts</span> {ncStatus.connected ? 'Connected' : ncStatus.configured ? 'Auth Error' : 'Not Configured'}
              </div>
            )}
            {isAdmin && (
              <>
                <button onClick={openNonPay} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-red-50 text-red-700 hover:bg-red-100 border border-red-200">
                  <Ban size={14} /> Non-Pay
                </button>
                <button onClick={loadDuplicates} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-amber-50 text-amber-700 hover:bg-amber-100 border border-amber-200">
                  <AlertTriangle size={14} /> <span className="hidden sm:inline">Duplicates</span><span className="sm:hidden">Dups</span>
                </button>
                <button onClick={handleSyncAll} disabled={syncing} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
                  {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  <span className="hidden sm:inline">{syncing ? 'Syncing...' : 'Sync All from NowCerts'}</span>
                  <span className="sm:hidden">{syncing ? 'Syncing...' : 'Sync All'}</span>
                </button>
              </>
            )}
          </div>
        </div>

        {/* Agency Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4 mb-8">
          <StatCard icon={<Users size={18} />} label="Active Customers" value={statsLoading ? '...' : fmt(stats?.active_customers)} color="green" />
          <StatCard icon={<FileText size={18} />} label="Active Policies" value={statsLoading ? '...' : fmt(stats?.active_policies)} color="indigo" />
          <StatCard icon={<DollarSign size={18} />} label="Annual Premium" value={statsLoading ? '...' : fmtMoney(stats?.total_active_premium_annualized)} color="emerald" />
          <StatCard icon={<TrendingUp size={18} />} label="Monthly Growth" value={statsLoading ? '...' : (stats?.monthly_customer_growth != null ? `${stats.monthly_customer_growth > 0 ? '+' : ''}${stats.monthly_customer_growth}` : '—')} color={stats?.monthly_customer_growth > 0 ? 'green' : stats?.monthly_customer_growth < 0 ? 'red' : 'slate'} />
          <StatCard icon={<Calendar size={18} />} label="Last Sync" value={statsLoading ? '...' : (stats?.last_sync ? new Date(stats.last_sync).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Never')} color="slate" />
        </div>

        {/* Search Bar */}
        <form onSubmit={handleSearch} className="card p-3 sm:p-4 mb-6">
          <div className="flex gap-2 sm:gap-3">
            <div className="relative flex-1">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name, email, phone number, or address"
                className="w-full pl-10 pr-4 py-2.5 sm:py-3 rounded-lg border border-slate-200 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500" />
            </div>
            <button type="submit" disabled={!searchQuery.trim()} className="btn-primary px-4 sm:px-6 py-2.5 sm:py-3 flex items-center gap-2 disabled:opacity-40">
              <Search size={16} /> <span className="hidden sm:inline">Search</span>
            </button>
          </div>
        </form>

        {/* MIA Quick Temp Auth */}
        <div className="card p-3 mb-6 border border-slate-200">
          <form onSubmit={handleQuickAuth} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 shrink-0">
              <Zap size={13} className="text-blue-500" />
              <span>MIA Temp Auth</span>
              <span className="text-[9px] bg-slate-100 text-slate-400 px-1 py-0.5 rounded">Framework</span>
            </div>
            <input
              type="tel"
              value={quickAuthPhone}
              onChange={e => setQuickAuthPhone(e.target.value)}
              placeholder="Phone number"
              className="flex-1 min-w-0 px-3 py-1.5 rounded border border-slate-200 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <input
              type="text"
              value={quickAuthName}
              onChange={e => setQuickAuthName(e.target.value)}
              placeholder="Name (optional)"
              className="flex-1 min-w-0 px-3 py-1.5 rounded border border-slate-200 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <select
              value={quickAuthDuration}
              onChange={e => setQuickAuthDuration(Number(e.target.value))}
              className="px-2 py-1.5 rounded border border-slate-200 text-xs focus:ring-2 focus:ring-blue-500"
            >
              <option value={30}>30 min</option>
              <option value={60}>1 hr</option>
              <option value={120}>2 hr</option>
              <option value={480}>8 hr</option>
              <option value={1440}>1 day</option>
              <option value={2880}>2 days</option>
              <option value={4320}>3 days</option>
              <option value={7200}>5 days</option>
            </select>
            <button
              type="submit"
              disabled={quickAuthSubmitting || !quickAuthPhone.trim()}
              className="px-4 py-1.5 rounded-md bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-40 shrink-0"
            >
              {quickAuthSubmitting ? 'Saving...' : 'Authorize'}
            </button>
            {quickAuthResult && (
              <span className={`text-xs font-semibold shrink-0 ${quickAuthResult.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                {quickAuthResult.type === 'success' ? '✓' : '✗'} {quickAuthResult.msg}
              </span>
            )}
          </form>
        </div>

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
                    <button onClick={() => handleExpand(c)} className="w-full text-left p-3 sm:p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                      <div className="flex items-center gap-3 sm:gap-4 flex-1 min-w-0">
                        <div className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0 ${c.has_active_policy ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
                          {(c.full_name || '?')[0]?.toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="font-bold text-slate-900 truncate text-sm sm:text-base">{c.full_name}</p>
                            {c.has_active_policy ? (
                              <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-semibold">Active</span>
                            ) : (
                              <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-semibold">Inactive</span>
                            )}
                            {c.is_prospect && <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-semibold">Prospect</span>}
                          </div>
                          <div className="flex flex-col sm:flex-row sm:items-center gap-0.5 sm:gap-4 text-xs text-slate-500 mt-0.5">
                            {c.email && <span className="flex items-center gap-1 truncate"><Mail size={11} /><span className="truncate">{c.email}</span></span>}
                            {c.phone && <span className="flex items-center gap-1"><Phone size={11} />{c.phone}</span>}
                            {c.city && c.state && <span className="flex items-center gap-1 hidden sm:flex"><MapPin size={11} />{c.city}, {c.state}</span>}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0 ml-2">
                        {c.policy_count > 0 && <span className="text-xs text-slate-400 hidden sm:inline">{c.policy_count} {c.policy_count === 1 ? 'policy' : 'policies'}</span>}
                        {isExpanded ? <ChevronUp size={18} className="text-slate-400" /> : <ChevronDown size={18} className="text-slate-400" />}
                      </div>
                    </button>
                    {isExpanded && (
                      <div className="border-t border-slate-200 bg-slate-50 p-3 sm:p-5">
                        {detailLoading ? (
                          <div className="text-center py-8 text-slate-500"><Loader2 size={20} className="animate-spin mx-auto mb-2" />Loading...</div>
                        ) : detail ? (
                          <>
                            {/* Edit / Save bar */}
                            <div className="flex items-center justify-between mb-3">
                              {!editing ? (
                                <button onClick={startEditing} className="flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 font-semibold">
                                  <Pencil size={12} /> Edit Info
                                </button>
                              ) : (
                                <div className="flex items-center gap-2 flex-wrap">
                                  <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
                                    <input type="checkbox" checked={pushToNowCerts} onChange={e => setPushToNowCerts(e.target.checked)} className="rounded" />
                                    Save to NowCerts
                                  </label>
                                  <button onClick={saveCustomerEdits} disabled={editSaving} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-white hover:bg-emerald-600 transition-colors disabled:opacity-50">
                                    {editSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                                    {pushToNowCerts ? 'Save & Push to NowCerts' : 'Save Locally'}
                                  </button>
                                  <button onClick={cancelEditing} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 hover:text-slate-700 hover:bg-slate-200 transition-colors">
                                    <X size={12} /> Cancel
                                  </button>
                                </div>
                              )}
                              {editMsg && (
                                <span className={`text-xs font-medium ${editMsg.type === 'success' ? 'text-emerald-600' : 'text-red-500'}`}>
                                  {editMsg.text}
                                </span>
                              )}
                            </div>

                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                              <InfoItem icon={<User size={14} />} label="Name" value={detail.customer?.full_name} />
                              {editing ? (
                                <EditableField icon={<Mail size={14} />} label="Email" value={editFields.email} onChange={v => setEditFields({...editFields, email: v})} placeholder="email@example.com" />
                              ) : (
                                <InfoItem icon={<Mail size={14} />} label="Email" value={detail.customer?.email} />
                              )}
                              {editing ? (
                                <EditableField icon={<Phone size={14} />} label="Phone" value={editFields.phone} onChange={v => setEditFields({...editFields, phone: v})} placeholder="(555) 123-4567" />
                              ) : (
                                <InfoItem icon={<Phone size={14} />} label="Phone" value={detail.customer?.phone} />
                              )}
                              {editing ? (
                                <EditableField icon={<Phone size={14} />} label="Mobile" value={editFields.mobile_phone} onChange={v => setEditFields({...editFields, mobile_phone: v})} placeholder="(555) 123-4567" />
                              ) : (
                                <InfoItem icon={<Phone size={14} />} label="Mobile" value={detail.customer?.mobile_phone} />
                              )}
                              {editing ? (
                                <EditableField icon={<MapPin size={14} />} label="Address" value={editFields.address} onChange={v => setEditFields({...editFields, address: v})} placeholder="123 Main St" />
                              ) : (
                                <InfoItem icon={<MapPin size={14} />} label="Address" value={detail.customer?.address} />
                              )}
                              {editing ? (
                                <div className="col-span-2 md:col-span-1">
                                  <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-0.5"><MapPin size={14} />City / State / Zip</div>
                                  <div className="flex gap-1">
                                    <input value={editFields.city} onChange={e => setEditFields({...editFields, city: e.target.value})} placeholder="City" className="w-full px-2 py-1 text-sm border border-slate-300 rounded focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                                    <input value={editFields.state} onChange={e => setEditFields({...editFields, state: e.target.value})} placeholder="ST" className="w-16 px-2 py-1 text-sm border border-slate-300 rounded focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                                    <input value={editFields.zip_code} onChange={e => setEditFields({...editFields, zip_code: e.target.value})} placeholder="Zip" className="w-20 px-2 py-1 text-sm border border-slate-300 rounded focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none" />
                                  </div>
                                </div>
                              ) : (
                                <InfoItem icon={<MapPin size={14} />} label="City" value={detail.customer?.city ? `${detail.customer.city}, ${detail.customer.state} ${detail.customer.zip_code}` : null} />
                              )}
                              <InfoItem icon={<User size={14} />} label="Agent" value={detail.customer?.agent_name} />
                              <InfoItem icon={<Calendar size={14} />} label="Last Synced" value={detail.customer?.last_synced_at ? new Date(detail.customer.last_synced_at).toLocaleDateString() : 'Never'} />
                            </div>
                            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                              <h3 className="font-bold text-slate-900">Policies ({detail.policies?.filter((p: any) => p.status?.toLowerCase() === 'active').length || 0} active)</h3>
                              <div className="flex items-center gap-3 flex-wrap">
                                {detail.customer?.nowcerts_insured_id && (
                                  <a
                                    href={`https://www6.nowcerts.com/AMSINS/Insureds/Details/${detail.customer.nowcerts_insured_id}/Information`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-1.5 text-xs text-emerald-600 hover:text-emerald-700 font-semibold"
                                  >
                                    <ExternalLink size={13} />NowCerts
                                  </a>
                                )}
                                {detail.customer?.id && (
                                  <button onClick={() => handleSync(detail.customer.id)} className="flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-700 font-semibold"><RefreshCw size={13} />Refresh</button>
                                )}
                              </div>
                            </div>
                            {(() => {
                              const now = new Date();
                              const oneYearAgo = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
                              const allPolicies = detail.policies || [];

                              // Active policies
                              const activePolicies = allPolicies.filter((p: any) => {
                                const st = (p.status || '').toLowerCase();
                                return st === 'active' || st === 'in force' || st === 'inforce';
                              });

                              // Recently cancelled (within 1 year, by expiration or effective date)
                              const cancelledPolicies = allPolicies.filter((p: any) => {
                                const st = (p.status || '').toLowerCase();
                                if (st === 'active' || st === 'in force' || st === 'inforce') return false;
                                if (st !== 'cancelled' && st !== 'non-renewed' && st !== 'nonrenewed') return false;
                                const expDate = p.expiration_date ? new Date(p.expiration_date) : null;
                                const effDate = p.effective_date ? new Date(p.effective_date) : null;
                                const refDate = expDate || effDate;
                                return refDate ? refDate >= oneYearAgo : true;
                              });

                              const showPolicies = showCancelled ? [...activePolicies, ...cancelledPolicies] : activePolicies;

                              const PolicyRow = ({ p, i }: { p: any; i: number }) => (
                                <div key={p.id || i} className="flex items-center gap-3 py-2.5 border-b border-slate-100 last:border-0">
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <button
                                        onClick={() => {
                                          let pn = p.policy_number || '';
                                          const carrierKey = (p.carrier || '').toLowerCase();
                                          if (carrierKey.includes('grange') && pn.toUpperCase().startsWith('PA3')) {
                                            pn = pn.substring(3);
                                          }
                                          navigator.clipboard.writeText(pn);
                                          setCopiedPolicy(pn);
                                          setTimeout(() => setCopiedPolicy(null), 2000);
                                          const carrierPortals: Record<string, string> = {
                                            'grange': 'https://agentware.grangeagent.com/default.aspx?ReturnUrl=https%3a%2f%2fgainwebpl.grangeagent.com%2fGainweb%2f',
                                            'safeco': 'https://now.safeco.com',
                                            'national general': 'https://natgenagency.com',
                                            'nat gen': 'https://natgenagency.com',
                                            'integon': 'https://natgenagency.com',
                                            'integon natl': 'https://natgenagency.com',
                                            'integon national': 'https://natgenagency.com',
                                            'openly': 'https://portal.openly.com',
                                            'progressive': 'https://www.foragentsonly.com',
                                            'travelers': 'https://foragents.travelers.com/Personal',
                                            'branch': 'https://app.ourbranch.com',
                                            'hippo': 'https://agent.hippo.com',
                                            'bristol west': 'https://www.bristolwest.com',
                                            'clearcover': 'https://agent.clearcover.com',
                                            'american modern': 'https://www.amig.com/agent',
                                            'steadily': 'https://app.steadily.com',
                                          };
                                          const portal = Object.entries(carrierPortals).find(([k]) => carrierKey.includes(k));
                                          if (portal) window.open(portal[1], '_blank');
                                        }}
                                        className="text-brand-600 hover:text-brand-700 hover:underline font-bold text-sm"
                                        title={`Copy & open ${p.carrier || 'carrier'} portal`}
                                      >
                                        {copiedPolicy === (p.policy_number || '') ? '✓ Copied!' : (p.policy_number || '—')}
                                      </button>
                                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${p.status?.toLowerCase() === 'active' ? 'bg-green-100 text-green-700' : p.status?.toLowerCase() === 'cancelled' ? 'bg-red-100 text-red-700' : p.status?.toLowerCase() === 'non-renewed' || p.status?.toLowerCase() === 'nonrenewed' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>{p.status || '?'}</span>
                                    </div>
                                    <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5 flex-wrap">
                                      <span>{normCarrier(p.carrier)}</span>
                                      <span>·</span>
                                      <span className="capitalize">{p.line_of_business || p.policy_type || '—'}</span>
                                      {p.premium && <><span>·</span><span className="font-semibold text-slate-700">${parseFloat(p.premium).toLocaleString()}</span></>}
                                    </div>
                                    <div className="text-[10px] text-slate-400 mt-0.5">
                                      {p.effective_date ? new Date(p.effective_date).toLocaleDateString() : '?'} → {p.expiration_date ? new Date(p.expiration_date).toLocaleDateString() : '?'}
                                    </div>
                                  </div>
                                </div>
                              );

                              return (
                                <div>
                                  {showPolicies.length > 0 ? (
                                    <div>{showPolicies.map((p: any, i: number) => <PolicyRow key={p.id || i} p={p} i={i} />)}</div>
                                  ) : (
                                    <p className="text-sm text-slate-500 py-4 text-center">No active policies. Try refreshing from NowCerts.</p>
                                  )}
                                  {cancelledPolicies.length > 0 && (
                                    <button
                                      onClick={() => setShowCancelled(!showCancelled)}
                                      className="mt-2 w-full text-center text-xs font-semibold text-slate-500 hover:text-slate-700 py-2 border border-dashed border-slate-200 rounded-lg transition-colors"
                                    >
                                      {showCancelled ? 'Hide' : 'Show'} {cancelledPolicies.length} cancelled/non-renewed (last 12 months)
                                    </button>
                                  )}
                                </div>
                              );
                            })()}

                            {/* Drivers & Contacts from NowCerts */}
                            {detail.customer?.id && (
                              <div className="mt-4 border-t border-slate-200 pt-4">
                                <button
                                  onClick={() => {
                                    if (!driversOpen) {
                                      setDriversOpen(true);
                                      if (!driversData) loadDrivers(detail.customer.id);
                                    } else {
                                      setDriversOpen(false);
                                    }
                                  }}
                                  className="flex items-center gap-2 text-sm font-semibold text-slate-700 hover:text-slate-900 transition-colors"
                                >
                                  <Users size={15} />
                                  Drivers & Contacts
                                  <ChevronRight size={14} className={`transition-transform ${driversOpen ? 'rotate-90' : ''}`} />
                                </button>
                                {driversOpen && (
                                  <div className="mt-3">
                                    {driversLoading ? (
                                      <div className="flex items-center gap-2 text-sm text-slate-500 py-3">
                                        <Loader2 size={14} className="animate-spin" />Fetching from NowCerts...
                                      </div>
                                    ) : driversData?.error ? (
                                      <div className="flex items-center gap-2 text-sm text-red-600 py-2">
                                        <AlertCircle size={14} />{driversData.error}
                                      </div>
                                    ) : driversData?.people?.length === 0 ? (
                                      <p className="text-sm text-slate-500 py-2">No drivers or contacts found in NowCerts.</p>
                                    ) : (
                                      <div className="space-y-2">
                                        {driversData?.people?.map((person: any, idx: number) => (
                                          <DriverCard key={idx} person={person} />
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Quick Reshop Refer */}
                            {detail.customer?.id && (
                              <div className="mt-4 border-t border-slate-200 pt-4">
                                <button
                                  onClick={async () => {
                                    try {
                                      await reshopAPI.fromCustomer(detail.customer.id, { source: 'producer_referral' });
                                      alert('Customer added to Reshop Pipeline!');
                                    } catch (e: any) {
                                      alert(e.response?.data?.detail || 'Failed to create reshop');
                                    }
                                  }}
                                  className="flex items-center gap-2 text-sm font-semibold text-amber-600 hover:text-amber-700 transition-colors"
                                >
                                  <Target size={15} />
                                  Refer for Reshop
                                </button>
                              </div>
                            )}

                            {/* MIA Bypass Controls */}
                            {detail.customer?.phone && (
                              <MiaBypassPanel
                                phone={detail.customer.phone}
                                customerName={detail.customer.full_name}
                              />
                            )}

                            {/* Quick Email Composer */}
                            {detail.customer?.email && (
                              <div className="mt-4 border-t border-slate-200 pt-4">
                                {!emailOpen ? (
                                  <button
                                    onClick={() => { setEmailOpen(true); setEmailSent(false); setEmailSubject(''); setEmailBody(''); setEmailFiles([]); setEmailSendAs('service'); setEmailCc(''); }}
                                    className="flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 transition-colors"
                                  >
                                    <Mail size={15} />
                                    Send Email to {detail.customer.full_name?.split(' ')[0] || 'Customer'}
                                  </button>
                                ) : (
                                  <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                                    <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-100">
                                      <div className="flex items-center gap-2">
                                        <Mail size={14} className="text-brand-600" />
                                        <span className="text-sm font-semibold text-slate-800">Quick Email</span>
                                        <span className="text-xs text-slate-400">→ {detail.customer.email}</span>
                                      </div>
                                      <button onClick={() => setEmailOpen(false)} className="text-slate-400 hover:text-slate-600"><X size={16} /></button>
                                    </div>
                                    {emailSent ? (
                                      <div className="px-4 py-6 text-center">
                                        <CheckCircle2 size={28} className="text-green-500 mx-auto mb-2" />
                                        <p className="text-sm font-semibold text-green-700">Email sent!</p>
                                        <p className="text-xs text-slate-500 mt-1">Delivered to {detail.customer.email}</p>
                                        {emailFiles.length > 0 && (
                                          <div className="mt-3 text-left bg-slate-50 rounded-lg p-3">
                                            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Attachments Sent ({emailFiles.length})</p>
                                            {emailFiles.map((f, i) => (
                                              <div key={i} className="flex items-center gap-2 text-xs text-slate-600 py-0.5">
                                                <Paperclip size={11} className="text-green-500 flex-shrink-0" />
                                                <span className="truncate">{f.name}</span>
                                                <span className="text-slate-400 flex-shrink-0">{(f.size / 1024).toFixed(0)}KB</span>
                                              </div>
                                            ))}
                                          </div>
                                        )}
                                        <button onClick={() => { setEmailOpen(false); setEmailFiles([]); }} className="mt-3 text-xs text-brand-600 hover:text-brand-700 font-semibold">Close</button>
                                      </div>
                                    ) : (
                                      <div className="p-4 space-y-3">
                                        {/* Send As Toggle */}
                                        <div>
                                          <label className="block text-xs font-semibold text-slate-500 mb-1.5">Send As</label>
                                          <div className="flex gap-2">
                                            <button
                                              onClick={() => setEmailSendAs('service')}
                                              className={`flex-1 px-3 py-2 rounded-lg text-xs font-semibold border transition-colors ${
                                                emailSendAs === 'service'
                                                  ? 'bg-brand-50 border-brand-300 text-brand-700'
                                                  : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
                                              }`}
                                            >
                                              service@betterchoiceins.com
                                            </button>
                                            <button
                                              onClick={() => setEmailSendAs('personal')}
                                              className={`flex-1 px-3 py-2 rounded-lg text-xs font-semibold border transition-colors ${
                                                emailSendAs === 'personal'
                                                  ? 'bg-brand-50 border-brand-300 text-brand-700'
                                                  : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
                                              }`}
                                            >
                                              My Email
                                            </button>
                                          </div>
                                          <p className="text-[10px] text-slate-400 mt-1">
                                            Replies go to {emailSendAs === 'service' ? 'service@betterchoiceins.com' : 'your email'}
                                          </p>
                                        </div>
                                        <div>
                                          <label className="block text-xs font-semibold text-slate-500 mb-1">Subject</label>
                                          <input
                                            value={emailSubject}
                                            onChange={e => setEmailSubject(e.target.value)}
                                            placeholder="e.g. Your Policy Update"
                                            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
                                          />
                                        </div>
                                        <div>
                                          <label className="block text-xs font-semibold text-slate-500 mb-1">CC <span className="font-normal text-slate-400">(optional, comma-separated)</span></label>
                                          <input
                                            value={emailCc}
                                            onChange={e => setEmailCc(e.target.value)}
                                            placeholder="e.g. agent@email.com, manager@email.com"
                                            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
                                          />
                                        </div>
                                        <div>
                                          <label className="block text-xs font-semibold text-slate-500 mb-1">Message</label>
                                          <textarea
                                            value={emailBody}
                                            onChange={e => setEmailBody(e.target.value)}
                                            placeholder={`Hi ${detail.customer.full_name?.split(' ')[0] || ''},\n\n`}
                                            rows={5}
                                            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none resize-none"
                                          />
                                        </div>
                                        {/* Attachments */}
                                        <div>
                                          <input
                                            ref={emailFileRef}
                                            type="file"
                                            multiple
                                            className="hidden"
                                            onChange={e => {
                                              if (e.target.files) setEmailFiles(prev => [...prev, ...Array.from(e.target.files!)]);
                                              e.target.value = '';
                                            }}
                                          />
                                          <button
                                            onClick={() => emailFileRef.current?.click()}
                                            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 font-semibold transition-colors border border-dashed border-slate-300 rounded-lg px-3 py-2 w-full justify-center hover:border-brand-400 hover:bg-brand-50"
                                          >
                                            <Paperclip size={13} />
                                            {emailFiles.length > 0 ? `Add More Files (${emailFiles.length} attached)` : 'Attach Files'}
                                          </button>
                                          {emailFiles.length > 0 && (
                                            <div className="mt-2 space-y-1.5 bg-slate-50 rounded-lg p-2">
                                              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-1">Attachments ({emailFiles.length})</p>
                                              {emailFiles.map((f, i) => (
                                                <div key={i} className="flex items-center gap-2 text-xs bg-white rounded-lg px-2.5 py-2 border border-slate-100">
                                                  {f.type?.startsWith('image/') ? (
                                                    <img src={URL.createObjectURL(f)} alt={f.name} className="w-8 h-8 rounded object-cover flex-shrink-0" />
                                                  ) : f.type === 'application/pdf' ? (
                                                    <div className="w-8 h-8 rounded bg-red-50 flex items-center justify-center flex-shrink-0"><FileText size={14} className="text-red-500" /></div>
                                                  ) : (
                                                    <div className="w-8 h-8 rounded bg-slate-100 flex items-center justify-center flex-shrink-0"><FileText size={14} className="text-slate-400" /></div>
                                                  )}
                                                  <div className="flex-1 min-w-0">
                                                    <p className="font-medium text-slate-700 truncate">{f.name}</p>
                                                    <p className="text-[10px] text-slate-400">{f.size < 1024 * 1024 ? `${(f.size / 1024).toFixed(0)} KB` : `${(f.size / (1024 * 1024)).toFixed(1)} MB`}</p>
                                                  </div>
                                                  <button onClick={() => setEmailFiles(prev => prev.filter((_, j) => j !== i))} className="text-slate-300 hover:text-red-500 flex-shrink-0 p-1"><X size={14} /></button>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between pt-2 gap-2">
                                          <span className="text-[10px] text-slate-400 text-center sm:text-left">Better Choice Insurance · (847) 908-5665</span>
                                          <div className="flex items-center gap-2 justify-end">
                                            <button onClick={() => setEmailOpen(false)} className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700">Cancel</button>
                                            <button
                                              disabled={!emailSubject.trim() || !emailBody.trim() || emailSending}
                                              onClick={async () => {
                                                setEmailSending(true);
                                                try {
                                                  await customersAPI.quickEmail({
                                                    to_email: detail.customer.email,
                                                    to_name: detail.customer.full_name || '',
                                                    cc_emails: emailCc || undefined,
                                                    subject: emailSubject,
                                                    body: emailBody,
                                                    send_as: emailSendAs,
                                                    customer_id: detail.customer.id || undefined,
                                                    attachments: emailFiles.length > 0 ? emailFiles : undefined,
                                                  });
                                                  setEmailSent(true);
                                                } catch (e: any) {
                                                  alert(e.response?.data?.detail || 'Failed to send email');
                                                } finally {
                                                  setEmailSending(false);
                                                }
                                              }}
                                              className="flex items-center gap-1.5 px-4 py-1.5 bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                            >
                                              {emailSending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                                              {emailSending ? 'Sending...' : 'Send'}
                                            </button>
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )}
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
          <USHeatmap />
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
            carrierOverride={nonpayCarrierOverride}
            setCarrierOverride={setNonpayCarrierOverride}
            showCarrierPrompt={showCarrierPrompt}
            onSendLive={handleNonpaySendLive}
            hasPendingFile={!!pendingFile}
          />
        )}
      </main>
    </div>
  );
}

const StatCard: React.FC<{ icon: React.ReactNode; label: string; value: string; color: string }> = ({ icon, label, value, color }) => {
  const cls: Record<string, string> = { blue: 'text-blue-600 bg-blue-50', green: 'text-green-600 bg-green-50', indigo: 'text-indigo-600 bg-indigo-50', emerald: 'text-emerald-600 bg-emerald-50', slate: 'text-slate-600 bg-slate-100' };
  return (<div className="card p-3 sm:p-4"><div className="flex items-center gap-2 mb-2"><div className={`p-1.5 sm:p-2 rounded-lg ${cls[color] || cls.slate}`}>{icon}</div></div><p className="text-xl sm:text-2xl font-bold text-slate-900 truncate">{value}</p><p className="text-[11px] sm:text-xs text-slate-500 mt-0.5">{label}</p></div>);
};

const InfoItem: React.FC<{ icon: React.ReactNode; label: string; value: string | null | undefined }> = ({ icon, label, value }) => (
  <div className="min-w-0"><div className="flex items-center gap-1.5 text-xs text-slate-500 mb-0.5">{icon}{label}</div><p className="text-sm font-semibold text-slate-800 break-words">{value || '—'}</p></div>
);

const EditableField: React.FC<{ icon: React.ReactNode; label: string; value: string; onChange: (v: string) => void; placeholder?: string }> = ({ icon, label, value, onChange, placeholder }) => (
  <div className="min-w-0">
    <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-0.5">{icon}{label}</div>
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-2 py-1 text-sm font-semibold border border-slate-300 rounded focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none bg-white"
    />
  </div>
);

// ── Driver / Contact Card ─────────────────────────────────────────
const DriverCard: React.FC<{ person: any }> = ({ person }) => {
  const [copied, setCopied] = useState<string | null>(null);
  const [showDL, setShowDL] = useState(false);

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 1500);
  };

  const formatDOB = (val: string | null) => {
    if (!val) return null;
    try {
      const d = new Date(val);
      if (isNaN(d.getTime())) return null;
      return d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' });
    } catch { return null; }
  };

  const dob = formatDOB(person.birthday);
  const dl = person.license_number;
  const dlState = person.license_state;
  const fullName = [person.first_name, person.middle_name, person.last_name].filter(Boolean).join(' ');

  return (
    <div className="bg-white border border-slate-200 rounded-lg px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white ${person.is_driver ? 'bg-blue-500' : 'bg-slate-400'}`}>
            {(person.first_name || '?')[0]}{(person.last_name || '?')[0]}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-800">{fullName || '—'}</span>
              {person.is_driver && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">DRIVER</span>}
              {person.primary_contact && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">PRIMARY</span>}
            </div>
            {(person.phone || person.email) && (
              <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                {person.phone && <span>{person.phone}</span>}
                {person.email && <span>{person.email}</span>}
              </div>
            )}
          </div>
        </div>
      </div>

      {(dob || dl) && (
        <div className="flex items-center gap-4 mt-2.5 pl-10">
          {dob && (
            <button
              onClick={() => copyToClipboard(dob, 'dob')}
              className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors group"
              title="Copy date of birth"
            >
              <Calendar size={12} className="text-slate-400" />
              <span className="font-medium">DOB:</span>
              <span>{dob}</span>
              {copied === 'dob' ? (
                <CheckCircle2 size={11} className="text-emerald-500" />
              ) : (
                <Copy size={11} className="text-slate-300 group-hover:text-slate-500" />
              )}
            </button>
          )}
          {dl && (
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <Shield size={12} className="text-slate-400" />
              <span className="font-medium">DL:</span>
              {showDL ? (
                <button
                  onClick={() => copyToClipboard(dl, 'dl')}
                  className="flex items-center gap-1 hover:text-slate-900 transition-colors group"
                  title="Copy license number"
                >
                  <span>{dl}{dlState ? ` (${dlState})` : ''}</span>
                  {copied === 'dl' ? (
                    <CheckCircle2 size={11} className="text-emerald-500" />
                  ) : (
                    <Copy size={11} className="text-slate-300 group-hover:text-slate-500" />
                  )}
                </button>
              ) : (
                <button
                  onClick={() => setShowDL(true)}
                  className="flex items-center gap-1 text-blue-600 hover:text-blue-700 transition-colors"
                >
                  <span>••••••{dl.slice(-4)}{dlState ? ` (${dlState})` : ''}</span>
                  <Eye size={11} />
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── MIA Bypass Panel ──────────────────────────────────────────────
const MiaBypassPanel: React.FC<{ phone: string; customerName: string }> = ({ phone, customerName }) => {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [showAuthForm, setShowAuthForm] = useState(false);
  const [authDuration, setAuthDuration] = useState(60);
  const [authReason, setAuthReason] = useState('');

  const loadStatus = useCallback(async () => {
    try {
      const r = await miaAPI.bypassStatus(phone);
      setStatus(r.data);
    } catch { setStatus(null); }
    setLoading(false);
  }, [phone]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleToggleVip = async () => {
    setActing(true);
    try {
      if (status?.vip) {
        await miaAPI.toggleVip(status.vip.id);
      } else {
        await miaAPI.addVip({ phone, customer_name: customerName, reason: 'Added from customer card' });
      }
      await loadStatus();
    } catch (e: any) { alert(e.response?.data?.detail || 'Failed'); }
    setActing(false);
  };

  const handleRemoveVip = async () => {
    if (!status?.vip || !confirm('Remove from VIP list permanently?')) return;
    setActing(true);
    try {
      await miaAPI.removeVip(status.vip.id);
      await loadStatus();
    } catch (e: any) { alert(e.response?.data?.detail || 'Failed'); }
    setActing(false);
  };

  const handleCreateAuth = async () => {
    setActing(true);
    try {
      await miaAPI.createAuth({ phone, customer_name: customerName, reason: authReason || undefined, duration_minutes: authDuration });
      setShowAuthForm(false);
      setAuthReason('');
      await loadStatus();
    } catch (e: any) { alert(e.response?.data?.detail || 'Failed'); }
    setActing(false);
  };

  const handleRevokeAuth = async () => {
    if (!status?.temp_auth) return;
    setActing(true);
    try {
      await miaAPI.revokeAuth(status.temp_auth.id);
      await loadStatus();
    } catch (e: any) { alert(e.response?.data?.detail || 'Failed'); }
    setActing(false);
  };

  if (loading) return null;

  const isVipActive = status?.vip?.is_active;
  const hasTempAuth = !!status?.temp_auth;
  const isBypassing = isVipActive || hasTempAuth;

  return (
    <div className="mt-5 pt-4 border-t border-slate-200">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield size={15} className={isBypassing ? 'text-amber-600' : 'text-slate-400'} />
          <h3 className="font-bold text-slate-900 text-sm">MIA Direct Line</h3>
          {isBypassing && (
            <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-semibold">
              {isVipActive ? 'VIP' : 'Temp Auth'}
            </span>
          )}
          <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">Framework — not live</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {/* VIP Toggle */}
        <div className={`rounded-lg border p-3 ${isVipActive ? 'border-amber-200 bg-amber-50/50' : 'border-slate-200 bg-white'}`}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <ShieldCheck size={13} />Permanent VIP
            </span>
            {status?.vip && (
              <button onClick={handleRemoveVip} disabled={acting} className="text-[10px] text-red-500 hover:text-red-700">Remove</button>
            )}
          </div>
          <p className="text-[11px] text-slate-500 mb-2">Calls always bypass MIA and ring office directly.</p>
          <button
            onClick={handleToggleVip}
            disabled={acting}
            className={`w-full text-xs font-semibold py-1.5 px-3 rounded-md transition-colors ${
              isVipActive
                ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {acting ? 'Saving...' : isVipActive ? '✓ VIP Active — Click to Deactivate' : 'Add to VIP List'}
          </button>
        </div>

        {/* Temp Authorization */}
        <div className={`rounded-lg border p-3 ${hasTempAuth ? 'border-blue-200 bg-blue-50/50' : 'border-slate-200 bg-white'}`}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <Zap size={13} />Temp Direct Line
            </span>
            {hasTempAuth && (
              <button onClick={handleRevokeAuth} disabled={acting} className="text-[10px] text-red-500 hover:text-red-700">Revoke</button>
            )}
          </div>

          {hasTempAuth ? (
            <div>
              <p className="text-[11px] text-blue-700 mb-1">
                <Clock size={10} className="inline mr-1" />
                {status.temp_auth.minutes_remaining >= 1440
                  ? `${Math.round(status.temp_auth.minutes_remaining / 1440 * 10) / 10} days remaining`
                  : status.temp_auth.minutes_remaining >= 120
                    ? `${Math.round(status.temp_auth.minutes_remaining / 60 * 10) / 10} hrs remaining`
                    : `${status.temp_auth.minutes_remaining} min remaining`}
              </p>
              <p className="text-[10px] text-slate-500">
                By {status.temp_auth.authorized_by}
                {status.temp_auth.reason ? ` — ${status.temp_auth.reason}` : ''}
              </p>
            </div>
          ) : showAuthForm ? (
            <div className="space-y-2">
              <select
                value={authDuration}
                onChange={e => setAuthDuration(Number(e.target.value))}
                className="w-full text-xs border border-slate-200 rounded px-2 py-1.5"
              >
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
                <option value={120}>2 hours</option>
                <option value={480}>Rest of day (~8hr)</option>
                <option value={1440}>1 day</option>
                <option value={2880}>2 days</option>
                <option value={4320}>3 days</option>
                <option value={7200}>5 days</option>
              </select>
              <input
                type="text"
                placeholder="Reason (optional)"
                value={authReason}
                onChange={e => setAuthReason(e.target.value)}
                className="w-full text-xs border border-slate-200 rounded px-2 py-1.5"
              />
              <div className="flex gap-2">
                <button
                  onClick={handleCreateAuth}
                  disabled={acting}
                  className="flex-1 text-xs font-semibold py-1.5 px-3 rounded-md bg-blue-600 text-white hover:bg-blue-700"
                >
                  {acting ? 'Authorizing...' : 'Authorize'}
                </button>
                <button
                  onClick={() => setShowAuthForm(false)}
                  className="text-xs py-1.5 px-3 rounded-md bg-slate-100 text-slate-600 hover:bg-slate-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-[11px] text-slate-500 mb-2">Grant temporary bypass while working with this customer.</p>
              <button
                onClick={() => setShowAuthForm(true)}
                className="w-full text-xs font-semibold py-1.5 px-3 rounded-md bg-slate-100 text-slate-600 hover:bg-slate-200"
              >
                Authorize Direct Line
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

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
  carrierOverride: string;
  setCarrierOverride: (v: string) => void;
  showCarrierPrompt: boolean;
  onSendLive: () => void;
  hasPendingFile: boolean;
}> = ({ onClose, uploading, result, history, histLoading, dragOver, setDragOver, onDrop, onFileSelect, fileInputRef, dryRun, setDryRun, carrierOverride, setCarrierOverride, showCarrierPrompt, onSendLive, hasPendingFile }) => {
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
  useEffect(() => { if (tab === 'upload' && carriers.length === 0) loadCarriers(); }, [tab]);
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

              {/* Carrier Override Selector */}
              <div className="flex items-center gap-3 p-4 bg-slate-50 rounded-xl mb-4">
                <div className="flex-1">
                  <p className="font-semibold text-sm text-slate-700">Carrier</p>
                  <p className="text-xs text-slate-500 mt-0.5">Select if the file doesn't include carrier info</p>
                </div>
                <select
                  value={carrierOverride}
                  onChange={(e) => setCarrierOverride(e.target.value)}
                  className="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm text-slate-700 font-medium min-w-[200px]"
                >
                  <option value="">Auto-detect from file</option>
                  {carriers.map((c: any) => (
                    <option key={c.key} value={c.key}>{c.display_name}</option>
                  ))}
                </select>
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
                    <div className="grid grid-cols-5 gap-3 mb-4">
                      <div className="text-center p-3 bg-blue-50 rounded-lg"><p className="text-xl font-bold text-blue-700">{result.policies_found}</p><p className="text-xs text-blue-600">Found</p></div>
                      <div className="text-center p-3 bg-green-50 rounded-lg"><p className="text-xl font-bold text-green-700">{result.policies_matched}</p><p className="text-xs text-green-600">Matched</p></div>
                      <div className={`text-center p-3 rounded-lg ${result.dry_run ? 'bg-amber-50' : 'bg-emerald-50'}`}>
                        <p className={`text-xl font-bold ${result.dry_run ? 'text-amber-700' : 'text-emerald-700'}`}>
                          {result.dry_run ? result.details?.filter((d: any) => d.would_send).length || 0 : result.emails_sent}
                        </p>
                        <p className={`text-xs ${result.dry_run ? 'text-amber-600' : 'text-emerald-600'}`}>{result.dry_run ? 'Would Email' : 'Emailed'}</p>
                      </div>
                      <div className="text-center p-3 bg-purple-50 rounded-lg">
                        <p className="text-xl font-bold text-purple-700">
                          {result.dry_run ? result.details?.filter((d: any) => d.would_send_letter).length || 0 : result.letters_sent || 0}
                        </p>
                        <p className="text-xs text-purple-600">{result.dry_run ? 'Would Mail' : 'Mailed'}</p>
                      </div>
                      <div className="text-center p-3 bg-amber-50 rounded-lg"><p className="text-xl font-bold text-amber-700">{result.emails_skipped}</p><p className="text-xs text-amber-600">Skipped</p></div>
                    </div>
                    {result.details?.length > 0 && (
                      <div className="max-h-60 overflow-y-auto">
                        <table className="w-full text-xs"><thead><tr className="text-left text-slate-500 border-b"><th className="pb-2 font-semibold">Policy</th><th className="pb-2 font-semibold">Customer</th><th className="pb-2 font-semibold">Reason</th><th className="pb-2 font-semibold">Status</th></tr></thead>
                          <tbody>{result.details.map((d: any, i: number) => (
                            <tr key={i} className={`border-b border-slate-100 ${d.skipped_reason ? 'opacity-50' : ''}`}>
                              <td className="py-2 font-mono font-semibold">{d.policy_number}</td>
                              <td className="py-2">{d.insured_name || d.customer_name || <span className="text-slate-400">—</span>}</td>
                              <td className="py-2 text-slate-500 text-[11px]">
                                {d.cancel_reason ? (
                                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                    d.notice_type === 'non-pay' ? 'bg-red-100 text-red-700' :
                                    d.notice_type === 'underwriting' ? 'bg-orange-100 text-orange-700' :
                                    d.notice_type === 'voluntary' ? 'bg-slate-100 text-slate-600' :
                                    'bg-slate-100 text-slate-600'
                                  }`}>{d.cancel_reason}</span>
                                ) : d.customer_email || '—'}
                              </td>
                              <td className="py-2">
                                {d.skipped_reason ? <span className="text-slate-400 italic">Ignored</span>
                                : d.would_send ? <span className="flex items-center gap-1 text-amber-600">✓ Would email {d.customer_email}</span>
                                : d.would_send_letter ? <span className="flex items-center gap-1 text-purple-600">✉ Would mail letter to {d.letter_address || 'address on file'}</span>
                                : d.email_sent ? <span className="flex items-center gap-1 text-green-600"><Send size={11} />Sent to {d.customer_email}</span>
                                : d.letter_sent ? <span className="flex items-center gap-1 text-purple-600">📬 Letter mailed via Thanks.io</span>
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

              {/* Carrier Detection Warning + Send Confirmation */}
              {result && result.dry_run && hasPendingFile && (
                <div className="mt-4">
                  {showCarrierPrompt && (
                    <div className="p-4 bg-orange-50 border border-orange-200 rounded-xl mb-3">
                      <div className="flex items-start gap-3">
                        <AlertTriangle size={20} className="text-orange-500 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          <p className="font-semibold text-sm text-orange-800">Carrier not detected for some policies</p>
                          <p className="text-xs text-orange-600 mt-1">
                            The system couldn't identify the carrier for {result.details?.filter((d: any) => !d.carrier || d.carrier === '' || d.carrier === 'unknown').length || 'some'} policies. 
                            Select a carrier below so the correct email template is used.
                          </p>
                          <div className="mt-3">
                            <select
                              value={carrierOverride}
                              onChange={(e) => setCarrierOverride(e.target.value)}
                              className="px-3 py-2 rounded-lg border border-orange-300 bg-white text-sm text-slate-700 font-medium w-full max-w-xs"
                            >
                              <option value="">— Select carrier —</option>
                              {carriers.map((c: any) => (
                                <option key={c.key} value={c.key}>{c.display_name}</option>
                              ))}
                            </select>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="flex items-center justify-between p-4 bg-green-50 border border-green-200 rounded-xl">
                    <div>
                      <p className="font-semibold text-sm text-green-800">Ready to send?</p>
                      <p className="text-xs text-green-600 mt-0.5">
                        {result.details?.filter((d: any) => d.would_send).length || 0} emails will be sent to customers
                      </p>
                    </div>
                    <button
                      onClick={onSendLive}
                      disabled={uploading || (showCarrierPrompt && !carrierOverride)}
                      className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-green-600 rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                    >
                      {uploading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                      Send Emails Now
                    </button>
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
