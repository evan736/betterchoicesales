import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { lifeCrossSellAPI } from '../lib/api';
import {
  Send, Loader2, Eye, Check, CheckCircle, Users, Search,
  Heart, Shield, Mail, Phone, DollarSign, TrendingUp, ExternalLink,
} from 'lucide-react';

const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  pending: { bg: 'bg-gray-500/20', text: 'text-gray-300', label: 'Pending' },
  email_sent: { bg: 'bg-blue-500/20', text: 'text-blue-300', label: 'Email Sent' },
  clicked: { bg: 'bg-cyan-500/20', text: 'text-cyan-300', label: 'Clicked' },
  app_started: { bg: 'bg-yellow-500/20', text: 'text-yellow-300', label: 'App Started' },
  app_submitted: { bg: 'bg-orange-500/20', text: 'text-orange-300', label: 'App Submitted' },
  approved: { bg: 'bg-emerald-500/20', text: 'text-emerald-300', label: 'Approved' },
  inforce: { bg: 'bg-green-500/20', text: 'text-green-300', label: 'In Force' },
  error: { bg: 'bg-red-500/20', text: 'text-red-300', label: 'Error' },
};

export default function LifeCrossSell() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<'eligible' | 'campaigns'>('eligible');
  const [eligible, setEligible] = useState<any[]>([]);
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [eligibleMeta, setEligibleMeta] = useState<any>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingData, setLoadingData] = useState(true);
  const [fetchTeaser, setFetchTeaser] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [user, loading, router]);

  const loadData = useCallback(async () => {
    setLoadingData(true);
    try {
      const [eRes, cRes, sRes] = await Promise.all([
        lifeCrossSellAPI.eligible(),
        lifeCrossSellAPI.campaigns(),
        lifeCrossSellAPI.stats(),
      ]);
      setEligible(eRes.data.eligible || []);
      setEligibleMeta(eRes.data);
      setCampaigns(cRes.data.campaigns || []);
      setStats(sRes.data || {});
    } catch (e) { console.error(e); }
    finally { setLoadingData(false); }
  }, []);

  useEffect(() => { if (user) loadData(); }, [user, loadData]);

  const handleSend = async () => {
    if (selected.size === 0) return;
    setSending(true);
    setSendResult(null);
    try {
      const res = await lifeCrossSellAPI.send(Array.from(selected), fetchTeaser);
      setSendResult(res.data);
      setSelected(new Set());
      loadData();
    } catch (e) { console.error(e); }
    finally { setSending(false); }
  };

  const toggleSelect = (saleId: number) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(saleId) ? next.delete(saleId) : next.add(saleId);
      return next;
    });
  };

  const selectAllEligible = () => {
    const unsent = eligible.filter(e => !e.already_sent);
    if (selected.size === unsent.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(unsent.map(e => e.sale_id)));
    }
  };

  const filtered = eligible.filter(e => {
    if (!searchQuery) return true;
    const s = searchQuery.toLowerCase();
    return e.client_name?.toLowerCase().includes(s) ||
           e.client_email?.toLowerCase().includes(s) ||
           e.carrier?.toLowerCase().includes(s) ||
           e.producer_name?.toLowerCase().includes(s);
  });

  const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

  if (loading || !user) return null;

  return (
    <div className="min-h-screen page-bg">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-6">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold page-title flex items-center gap-2">
              <Heart size={24} className="text-rose-400" />
              Life Insurance Cross-Sell
            </h1>
            <p className="text-sm page-subtitle mt-1">
              Cross-sell life insurance to your P&C customers via Back9 Quote & Apply
            </p>
          </div>
        </div>

        {/* Funnel Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 mb-6">
          {[
            { label: 'Total', value: stats.total || 0, color: 'text-white' },
            { label: 'Sent', value: stats.sent || 0, color: 'text-blue-400' },
            { label: 'Clicked', value: stats.clicked || 0, color: 'text-cyan-400' },
            { label: 'Apps Started', value: stats.apps_started || 0, color: 'text-yellow-400' },
            { label: 'Submitted', value: stats.submitted || 0, color: 'text-orange-400' },
            { label: 'Approved', value: stats.approved || 0, color: 'text-emerald-400' },
            { label: 'In Force', value: stats.inforce || 0, color: 'text-green-400' },
          ].map(s => (
            <div key={s.label} className="card-bg rounded-lg p-3 text-center">
              <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-xs page-subtitle">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setTab('eligible')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === 'eligible' ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' : 'card-bg page-subtitle hover:text-white'
            }`}
          >
            <Users size={14} className="inline mr-1.5" />
            Eligible ({eligibleMeta.ready_to_send || 0})
          </button>
          <button
            onClick={() => setTab('campaigns')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === 'campaigns' ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30' : 'card-bg page-subtitle hover:text-white'
            }`}
          >
            <Mail size={14} className="inline mr-1.5" />
            Campaigns ({campaigns.length})
          </button>
        </div>

        {loadingData ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-cyan-400" />
          </div>
        ) : tab === 'eligible' ? (
          <>
            {/* Search & Actions */}
            <div className="flex flex-col sm:flex-row gap-3 mb-4">
              <div className="relative flex-1">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  className="w-full pl-9 pr-4 py-2 rounded-lg card-bg border border-transparent focus:border-cyan-500/30 text-sm page-title placeholder-gray-500 outline-none"
                  placeholder="Search by name, email, carrier, producer..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs page-subtitle cursor-pointer">
                  <input
                    type="checkbox"
                    checked={fetchTeaser}
                    onChange={e => setFetchTeaser(e.target.checked)}
                    className="rounded"
                  />
                  Fetch live rates
                </label>
                <button
                  onClick={selectAllEligible}
                  className="px-3 py-2 rounded-lg card-bg text-xs page-subtitle hover:text-white transition-colors"
                >
                  {selected.size === eligible.filter(e => !e.already_sent).length ? 'Deselect All' : 'Select All'}
                </button>
                <button
                  onClick={handleSend}
                  disabled={selected.size === 0 || sending}
                  className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors"
                >
                  {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  Send ({selected.size})
                </button>
              </div>
            </div>

            {/* Send Result */}
            {sendResult && (
              <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <p className="text-sm text-emerald-300">
                  <CheckCircle size={14} className="inline mr-1" />
                  Sent: {sendResult.sent} | Skipped: {sendResult.skipped} | Errors: {sendResult.errors}
                </p>
              </div>
            )}

            {/* Eligible List */}
            <div className="space-y-1.5">
              {filtered.map(e => (
                <div
                  key={e.sale_id}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg card-bg border transition-colors cursor-pointer ${
                    selected.has(e.sale_id) ? 'border-rose-500/40 bg-rose-500/5' :
                    e.already_sent ? 'border-transparent opacity-50' : 'border-transparent hover:border-cyan-500/20'
                  }`}
                  onClick={() => !e.already_sent && toggleSelect(e.sale_id)}
                >
                  {/* Checkbox */}
                  <div className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                    e.already_sent ? 'border-gray-600 bg-gray-700' :
                    selected.has(e.sale_id) ? 'border-rose-400 bg-rose-500' : 'border-gray-500'
                  }`}>
                    {(selected.has(e.sale_id) || e.already_sent) && <Check size={12} className="text-white" />}
                  </div>

                  {/* Customer Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm page-title truncate">{e.client_name}</span>
                      {e.already_sent && (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-blue-500/20 text-blue-300">Already Sent</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 text-xs page-subtitle">
                      <span className="truncate max-w-[180px]">{e.client_email}</span>
                      <span>&middot;</span>
                      <span className="capitalize">{e.carrier?.replace(/_/g, ' ')}</span>
                      <span>&middot;</span>
                      <span className="capitalize">{e.policy_type}</span>
                    </div>
                  </div>

                  {/* Producer */}
                  <div className="text-xs text-cyan-400/70 flex-shrink-0 hidden sm:block">
                    {e.producer_name || 'Unassigned'}
                  </div>

                  {/* Premium */}
                  <div className="text-right flex-shrink-0">
                    <p className="text-sm font-semibold" style={{ color: '#0ea5e9' }}>
                      {e.written_premium ? `$${e.written_premium.toLocaleString()}` : ''}
                    </p>
                    <p className="text-xs page-subtitle">{e.state || ''}</p>
                  </div>

                  {/* Preview */}
                  <a
                    href={`${API_URL}/api/life-crosssell/preview-email/${e.sale_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-shrink-0 p-1.5 rounded hover:bg-white/10 transition-colors"
                    onClick={ev => ev.stopPropagation()}
                    title="Preview email"
                  >
                    <Eye size={14} className="text-gray-400" />
                  </a>
                </div>
              ))}
            </div>

            {filtered.length === 0 && (
              <div className="text-center py-16">
                <Heart size={48} className="mx-auto mb-4 text-gray-500" />
                <p className="text-gray-400">No eligible customers found. Close some P&C sales first!</p>
              </div>
            )}
          </>
        ) : (
          /* Campaigns Tab */
          <div className="space-y-1.5">
            {campaigns.length === 0 ? (
              <div className="text-center py-16">
                <Mail size={48} className="mx-auto mb-4 text-gray-500" />
                <p className="text-gray-400">No campaigns sent yet. Select eligible customers and send!</p>
              </div>
            ) : campaigns.map(c => {
              const sc = STATUS_COLORS[c.status] || STATUS_COLORS.pending;
              return (
                <div key={c.id} className="flex items-center gap-3 px-4 py-3 rounded-lg card-bg border border-transparent">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm page-title truncate">{c.client_name}</span>
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${sc.bg} ${sc.text}`}>{sc.label}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 text-xs page-subtitle">
                      <span>{c.client_email}</span>
                      <span>&middot;</span>
                      <span className="capitalize">{c.pc_carrier?.replace(/_/g, ' ')} {c.pc_policy_type}</span>
                      <span>&middot;</span>
                      <span>{c.producer_name}</span>
                    </div>
                  </div>

                  {/* Back9 info */}
                  <div className="text-right flex-shrink-0 hidden sm:block">
                    {c.back9_carrier && (
                      <p className="text-xs page-subtitle">{c.back9_carrier}</p>
                    )}
                    {c.back9_quote_premium && (
                      <p className="text-sm font-semibold text-emerald-400">
                        ${c.back9_quote_premium.toFixed(0)}/mo
                      </p>
                    )}
                  </div>

                  {/* Timeline dots */}
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <div className={`w-2 h-2 rounded-full ${c.email_sent_at ? 'bg-blue-400' : 'bg-gray-600'}`} title="Sent" />
                    <div className={`w-2 h-2 rounded-full ${c.link_clicked_at ? 'bg-cyan-400' : 'bg-gray-600'}`} title="Clicked" />
                    <div className={`w-2 h-2 rounded-full ${c.app_started_at ? 'bg-yellow-400' : 'bg-gray-600'}`} title="App Started" />
                    <div className={`w-2 h-2 rounded-full ${c.app_submitted_at ? 'bg-orange-400' : 'bg-gray-600'}`} title="Submitted" />
                    <div className={`w-2 h-2 rounded-full ${c.approved_at ? 'bg-emerald-400' : 'bg-gray-600'}`} title="Approved" />
                    <div className={`w-2 h-2 rounded-full ${c.inforce_at ? 'bg-green-400' : 'bg-gray-600'}`} title="In Force" />
                  </div>

                  {/* Sent date */}
                  <div className="text-xs page-subtitle flex-shrink-0 w-16 text-right">
                    {c.email_sent_at ? new Date(c.email_sent_at).toLocaleDateString() : ''}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
