import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { quotesAPI, adminAPI } from '../lib/api';
import axios from 'axios';
import {
  Plus, FileText, Send, Upload, X, Check, Trash2, Loader2,
  AlertCircle, Eye, Phone, Mail, ChevronDown, Search, Filter,
  Clock, CheckCircle, XCircle, RotateCcw, TrendingUp, DollarSign,
} from 'lucide-react';

const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  quoted: { bg: 'bg-gray-500/20', text: 'text-gray-300', label: 'Quoted' },
  sent: { bg: 'bg-blue-500/20', text: 'text-blue-300', label: 'Sent' },
  bind_requested: { bg: 'bg-emerald-500/20', text: 'text-emerald-300', label: 'Bind Requested' },
  following_up: { bg: 'bg-yellow-500/20', text: 'text-yellow-300', label: 'Following Up' },
  converted: { bg: 'bg-green-500/20', text: 'text-green-300', label: 'Converted' },
  lost: { bg: 'bg-red-500/20', text: 'text-red-300', label: 'Lost' },
  remarket: { bg: 'bg-purple-500/20', text: 'text-purple-300', label: 'Remarket' },
};

const POLICY_TYPES = [
  'auto', 'home', 'renters', 'condo', 'landlord', 'umbrella',
  'motorcycle', 'boat', 'rv', 'life', 'commercial', 'bundled', 'other',
];

export default function Quotes() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [quotes, setQuotes] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loadingQuotes, setLoadingQuotes] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [filter, setFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const searchTimerRef = useRef<any>(null);
  const [carriers, setCarriers] = useState<string[]>([]);
  const [selectedQuote, setSelectedQuote] = useState<any>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [expandedProspect, setExpandedProspect] = useState<string | null>(null);
  const [showAbPanel, setShowAbPanel] = useState(false);
  const [abStats, setAbStats] = useState<any>(null);
  const [abLoading, setAbLoading] = useState(false);
  const isAdminOrManager = user?.role && ['admin', 'manager'].includes(user.role.toLowerCase());

  const loadAbStats = async () => {
    setAbLoading(true);
    try {
      const r = await axios.get(
        `${process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com'}/api/quotes/ab-test/stats?days=30`,
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      setAbStats(r.data);
    } catch (e: any) {
      console.error('A/B stats load failed', e);
    }
    setAbLoading(false);
  };

  useEffect(() => {
    if (!loading && !user) router.push('/');
  }, [user, loading, router]);

  const loadQuotes = useCallback(async () => {
    try {
      setLoadingQuotes(true);
      const params: any = {};
      if (filter !== 'all') params.status = filter;
      if (searchQuery.trim()) params.search = searchQuery.trim();
      const [qRes, sRes] = await Promise.all([
        quotesAPI.list(params),
        quotesAPI.stats(),
      ]);
      setQuotes(qRes.data.quotes || []);
      setStats(sRes.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingQuotes(false);
    }
  }, [filter, searchQuery]);

  useEffect(() => {
    if (user) {
      loadQuotes();
      adminAPI.dropdownOptions().then((r: any) => {
        setCarriers((r.data.carriers || []).map((c: any) => typeof c === 'string' ? c : (c.value || c.label || '')).filter((c: string) => c));
      }).catch(() => {});
    }
  }, [user, loadQuotes]);

  // SSE live refresh
  useEffect(() => {
    if (!user) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${baseUrl}/api/events/stream`);
      es.addEventListener('sales:new', () => loadQuotes());
      es.addEventListener('sales:updated', () => loadQuotes());
      es.onerror = () => es?.close();
    } catch {}
    return () => es?.close();
  }, [user]);

  // Search is now server-side — quotes are already filtered
  const filtered = quotes;

  // Group quotes by prospect email to show grouping indicators
  const prospectGroups = useMemo(() => {
    const groups: Record<string, number[]> = {};
    quotes.forEach((q) => {
      const key = (q.prospect_email || '').toLowerCase().trim() || `name:${(q.prospect_name || '').toLowerCase().trim()}`;
      if (!groups[key]) groups[key] = [];
      groups[key].push(q.id);
    });
    return groups;
  }, [quotes]);

  // Group filtered quotes by prospect
  const groupedProspects = useMemo(() => {
    const groups: Record<string, any[]> = {};
    const order: string[] = [];
    filtered.forEach((q) => {
      const key = (q.prospect_email || '').toLowerCase().trim() || `name:${(q.prospect_name || '').toLowerCase().trim()}`;
      if (!groups[key]) { groups[key] = []; order.push(key); }
      groups[key].push(q);
    });
    // Sort each group by created_at desc
    Object.values(groups).forEach(g => g.sort((a: any, b: any) => 
      new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
    ));
    return order.map(key => groups[key]);
  }, [filtered]);

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

  return (
    <div className="min-h-screen page-bg">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold page-title">Quotes</h1>
            <p className="text-sm page-subtitle mt-1">Quote-to-close pipeline</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white transition-colors"
            style={{ background: '#0ea5e9' }}
          >
            <Plus size={16} /> New Quote
          </button>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
            {[
              { label: 'Total', value: stats.total_quotes, icon: <FileText size={14} /> },
              { label: 'MTD', value: stats.mtd_quotes, icon: <Calendar size={14} /> },
              { label: 'Sent', value: stats.sent, icon: <Send size={14} /> },
              { label: 'Active', value: stats.active_pipeline, icon: <Clock size={14} /> },
              { label: 'Won', value: stats.converted, icon: <CheckCircle size={14} />, color: '#10b981' },
              { label: 'Lost', value: stats.lost, icon: <XCircle size={14} />, color: '#ef4444' },
              { label: 'Close %', value: `${stats.conversion_rate}%`, icon: <TrendingUp size={14} />, color: '#0ea5e9' },
            ].map((s, i) => (
              <div key={i} className="stat-card rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <span style={{ color: s.color || '#64748b' }}>{s.icon}</span>
                  <span className="text-xs stat-label">{s.label}</span>
                </div>
                <p className="text-xl font-bold stat-value" style={s.color ? { color: s.color } : {}}>
                  {s.value}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* A/B Test Panel — admin/manager only */}
        {isAdminOrManager && (
          <div className="mb-6">
            <button
              onClick={() => {
                const next = !showAbPanel;
                setShowAbPanel(next);
                if (next && !abStats) loadAbStats();
              }}
              className="flex items-center gap-2 text-xs font-semibold text-cyan-400 hover:text-cyan-300 mb-2"
            >
              <span style={{ display: 'inline-block', transform: showAbPanel ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}>▶</span>
              Email A/B Test (last 30 days)
              {abStats && abStats.total_with_variant > 0 && (
                <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 ml-1">
                  {abStats.total_with_variant} quotes
                </span>
              )}
            </button>
            {showAbPanel && (
              <div className="rounded-lg p-4" style={{ background: 'rgba(14,165,233,0.04)', border: '1px solid rgba(14,165,233,0.2)' }}>
                {abLoading ? (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Loader2 size={12} className="animate-spin" /> Loading…
                  </div>
                ) : !abStats ? (
                  <div className="text-xs text-slate-400">No data yet — send quotes to start collecting.</div>
                ) : abStats.total_with_variant === 0 ? (
                  <div className="text-xs text-slate-400 italic">
                    No A/B test data yet. New quotes will be randomly assigned to variant A or B at first send.
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { key: 'A', label: 'Variant A', sub: 'Branded + coverage limits', color: '#a855f7', data: abStats.variant_a },
                      { key: 'B', label: 'Variant B', sub: 'Plain-text personal style', color: '#10b981', data: abStats.variant_b },
                    ].map((arm) => (
                      <div key={arm.key} className="p-3 rounded-lg" style={{ background: 'rgba(15,23,42,0.4)', border: `1px solid ${arm.color}30` }}>
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <div className="text-sm font-bold" style={{ color: arm.color }}>{arm.label}</div>
                            <div className="text-[10px] text-slate-400">{arm.sub}</div>
                          </div>
                          <div className="text-2xl font-bold text-slate-200">{arm.data.sent}</div>
                        </div>
                        <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-slate-700">
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Replied</div>
                            <div className="text-sm font-bold text-amber-400">{arm.data.replied}</div>
                            <div className="text-[10px] text-slate-400">{arm.data.reply_rate.toFixed(1)}%</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Bound</div>
                            <div className="text-sm font-bold text-emerald-400">{arm.data.bound}</div>
                            <div className="text-[10px] text-slate-400">{arm.data.bind_rate.toFixed(1)}%</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Lost</div>
                            <div className="text-sm font-bold text-rose-400">{arm.data.lost}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-slate-500 mt-3 italic">
                  Variants are assigned 50/50 at first send and stay sticky through all 5 follow-ups (initial + day 3, 7, 14, 30).
                </p>
              </div>
            )}
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="relative flex-1 max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search by name, email, carrier, producer..."
              value={searchQuery}
              onChange={(e) => {
                setSearchInput(e.target.value);
                if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
                searchTimerRef.current = setTimeout(() => setSearchQuery(e.target.value), 400);
              }}
              value={searchInput}
              className="w-full pl-9 pr-3 py-2 rounded-lg text-sm input-field"
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {['all', 'sent', 'following_up', 'converted', 'lost', 'remarket'].map((f) => {
              const count = stats?.by_status?.[f] ?? '';
              return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  filter === f ? 'text-white' : 'filter-chip'
                }`}
                style={filter === f ? { background: '#0ea5e9' } : {}}
              >
                {f === 'all' ? 'All' : STATUS_COLORS[f]?.label || f}
                {count > 0 && <span className="ml-1 opacity-70">({count})</span>}
              </button>
              );
            })}
          </div>
        </div>

        {/* Quote List */}
        {loadingQuotes ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-cyan-400" />
          </div>
        ) : groupedProspects.length === 0 ? (
          <div className="text-center py-20">
            <FileText size={48} className="mx-auto mb-4 text-gray-500" />
            <p className="text-gray-400">No quotes yet. Create your first quote to get started.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {groupedProspects.map((group) => {
              const primary = group[0];
              const hasMultiple = group.length > 1;
              const statusPriority: Record<string, number> = { bind_requested: 5, converted: 4, following_up: 3, sent: 2, quoted: 1, lost: 0, remarket: 0 };
              const bestQuote = group.reduce((best: any, q: any) => (statusPriority[q.status] || 0) > (statusPriority[best.status] || 0) ? q : best, primary);
              const sc = STATUS_COLORS[bestQuote.status] || STATUS_COLORS.quoted;
              const anyDisabled = group.some((q: any) => q.followup_disabled);

              const annualize = (q: any) => {
                const p = q.quoted_premium || 0;
                if (!p) return Infinity;
                const term = (q.premium_term || '6 months').toLowerCase();
                if (term.includes('12') || term.includes('year')) return p;
                if (term.includes('6')) return p * 2;
                if (term.includes('month') && !term.includes('6') && !term.includes('12')) return p * 12;
                return p * 2;
              };
              const lowestQuote = group.reduce((best: any, q: any) => annualize(q) < annualize(best) ? q : best, group[0]);
              const lowestPremium = lowestQuote.quoted_premium || 0;
              const lowestTerm = lowestQuote.premium_term || '6 months';
              const lowestCarrier = (lowestQuote.carrier || '').replace(/_/g, ' ');
              const groupKey = primary.prospect_email || `id-${primary.id}`;

              return (
                <div key={groupKey} className="card-bg rounded-lg border border-transparent hover:border-cyan-500/30 transition-colors">
                  <div className="flex items-center gap-3 px-4 py-3">
                    {/* Expand toggle for multi-quote */}
                    {hasMultiple ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); setExpandedProspect(expandedProspect === groupKey ? null : groupKey); }}
                        className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded bg-white/5 hover:bg-white/10 transition-colors"
                      >
                        <ChevronDown size={14} className={`transition-transform ${expandedProspect === groupKey ? 'rotate-180' : ''}`} style={{ color: '#94a3b8' }} />
                      </button>
                    ) : (
                      <div className="w-6" />
                    )}

                    {/* Prospect info */}
                    <div className="flex-1 min-w-0 cursor-pointer" onClick={() => { setSelectedQuote(primary); setShowDetail(true); }}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-sm page-title truncate">{primary.prospect_name}</h3>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${sc.bg} ${sc.text}`}>{sc.label}</span>
                        {hasMultiple && (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-violet-500/20 text-violet-300">{group.length} quotes</span>
                        )}
                        {anyDisabled && (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-gray-500/20 text-gray-400">No F/U</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-xs page-subtitle flex-wrap">
                        {primary.prospect_email && <span className="truncate max-w-[180px]">{primary.prospect_email}</span>}
                        <span>•</span>
                        <span className="font-medium text-cyan-400/70">{primary.producer_name || 'Unassigned'}</span>
                      </div>
                    </div>

                    {/* Premium & carrier */}
                    <div className="flex-shrink-0 text-right cursor-pointer" onClick={() => { setSelectedQuote(lowestQuote); setShowDetail(true); }}>
                      {hasMultiple && <p className="text-xs page-subtitle capitalize">Best: {lowestCarrier}</p>}
                      {!hasMultiple && <p className="text-xs page-subtitle capitalize">{lowestCarrier} • {primary.policy_type}</p>}
                      <p className="text-base font-bold" style={{ color: '#0ea5e9' }}>
                        {lowestPremium > 0 ? `$${lowestPremium.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : ''}
                      </p>
                      <p className="text-xs page-subtitle">/{lowestTerm}</p>
                    </div>

                    {/* Sent date */}
                    <div className="flex-shrink-0 text-right text-xs page-subtitle w-16">
                      {primary.email_sent ? (
                        <span className="text-blue-400">Sent {primary.days_since_sent != null ? `${primary.days_since_sent}d` : ''}</span>
                      ) : (
                        <span>Draft</span>
                      )}
                    </div>
                  </div>

                  {/* Collapsible quote lines */}
                  {hasMultiple && expandedProspect === groupKey && (
                    <div className="border-t border-white/5 px-4 pb-2 pt-1">
                      {group.map((q: any) => {
                        const qsc = STATUS_COLORS[q.status] || STATUS_COLORS.quoted;
                        return (
                          <div
                            key={q.id}
                            className="flex items-center justify-between pl-8 pr-2 py-1.5 rounded hover:bg-white/5 cursor-pointer transition-colors text-xs"
                            onClick={() => { setSelectedQuote(q); setShowDetail(true); }}
                          >
                            <div className="flex items-center gap-2">
                              <span className="capitalize page-title">{q.carrier?.replace(/_/g, ' ')}</span>
                              <span className="page-subtitle">• {q.policy_type}</span>
                              <span className={`px-1.5 py-0.5 rounded ${qsc.bg} ${qsc.text}`}>{qsc.label}</span>
                              {q.pdf_uploaded && <span className="px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-300">PDF</span>}
                            </div>
                            <span className="font-semibold" style={{ color: '#0ea5e9' }}>
                              {q.quoted_premium ? `$${q.quoted_premium.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : ''}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Create Quote Modal */}
      {showCreate && (
        <ModalErrorBoundary><CreateQuoteModal
          carriers={carriers}
          onClose={() => setShowCreate(false)}
          onCreated={(q) => {
            setShowCreate(false);
            loadQuotes();
            setSelectedQuote(q);
            setShowDetail(true);
          }}
        />
        </ModalErrorBoundary>
      )}

      {/* Quote Detail Modal */}
      {showDetail && selectedQuote && (
        <QuoteDetailModal
          quote={selectedQuote}
          onClose={() => { setShowDetail(false); setSelectedQuote(null); }}
          onRefresh={loadQuotes}
          allQuotes={quotes}
        />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// CREATE QUOTE MODAL
// ═══════════════════════════════════════════════════════════════


class ModalErrorBoundary extends React.Component<{children: React.ReactNode}, {error: string | null}> {
  constructor(props: any) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(e: any) { return { error: e?.message || String(e) }; }
  render() {
    if (this.state.error) return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div className="bg-red-900/80 rounded-xl p-6 max-w-lg text-white">
          <h2 className="text-lg font-bold mb-2">Modal Error</h2>
          <p className="text-sm font-mono break-all">{this.state.error}</p>
          <button onClick={() => window.location.reload()} className="mt-4 px-4 py-2 bg-white/20 rounded">Reload</button>
        </div>
      </div>
    );
    return this.props.children;
  }
}

function CreateQuoteModal({ carriers, onClose, onCreated }: {
  carriers: string[];
  onClose: () => void;
  onCreated: (q: any) => void;
}) {
  const [phase, setPhase] = useState<'upload' | 'form'>('upload');
  const [form, setForm] = useState({
    prospect_name: '', prospect_email: '', prospect_phone: '',
    prospect_address: '', prospect_city: '', prospect_state: '', prospect_zip: '',
    carrier: '', effective_date: '', premium_term: '6 months',
    // Coverage limits — used by Variant A email rendering. Stored as
    // strings here for input field compatibility; converted on submit.
    coverage_dwelling: '', coverage_personal_property: '', coverage_liability: '',
    auto_bi_limit: '', auto_pd_limit: '', auto_um_limit: '',
  });
  // Each policy line from extraction (or one default for manual entry)
  const [policyLines, setPolicyLines] = useState<Array<{
    policy_type: string; quoted_premium: string; notes: string; enabled: boolean;
  }>>([{ policy_type: 'auto', quoted_premium: '', notes: '', enabled: true }]);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  // Multi-PDF: collect all dropped/selected files in one array.
  // Extraction merges them; upload sends them all to one quote.
  const [pdfFiles, setPdfFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Separate ref for the "Add another PDF" button on the review screen
  // so it's independent of the initial drop-zone input ref.
  const addPdfInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: File[]) => {
    // Filter to PDFs only — silently ignore non-PDFs rather than erroring,
    // since users sometimes drag the whole folder by accident.
    const pdfs = files.filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfs.length === 0) {
      setError('Please upload at least one PDF');
      return;
    }
    if (pdfs.length > 5) {
      setError('Maximum 5 PDFs per quote');
      return;
    }
    setPdfFiles(pdfs);
    setExtracting(true);
    setError('');
    try {
      // Use the multi-PDF endpoint for 2+ files; singular for 1
      // (mostly to avoid unnecessary multipart parsing overhead, but
      // also so the endpoint logs cleanly distinguish the two paths).
      const res = pdfs.length === 1
        ? await quotesAPI.extractPDF(pdfs[0])
        : await quotesAPI.extractPDFs(pdfs);
      const d = res.data;
      setForm({
        prospect_name: d.prospect_name || '',
        prospect_email: d.prospect_email || '',
        prospect_phone: d.prospect_phone || '',
        prospect_address: d.prospect_address || '',
        prospect_city: d.prospect_city || '',
        prospect_state: d.prospect_state || '',
        prospect_zip: d.prospect_zip || '',
        carrier: d.carrier || '',
        effective_date: d.effective_date || '',
        premium_term: d.premium_term || '6 months',
        coverage_dwelling: d.coverage_dwelling != null ? String(d.coverage_dwelling) : '',
        coverage_personal_property: d.coverage_personal_property != null ? String(d.coverage_personal_property) : '',
        coverage_liability: d.coverage_liability != null ? String(d.coverage_liability) : '',
        auto_bi_limit: d.auto_bi_limit || '',
        auto_pd_limit: d.auto_pd_limit || '',
        auto_um_limit: d.auto_um_limit || '',
      });
      if (d.carrier && carriers.length > 0) {
        const extracted = (d.carrier || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        const match = carriers.find(c => {
          const normalized = c.toLowerCase().replace(/[^a-z0-9]/g, '');
          return normalized === extracted || normalized.includes(extracted) || extracted.includes(normalized);
        });
        if (match) {
          setForm(prev => ({ ...prev, carrier: match }));
        }
      }
      const allPolicies = d.all_policies || [];
      if (allPolicies.length > 0) {
        setPolicyLines(allPolicies.map((p: any) => ({
          policy_type: p.policy_type || 'other',
          quoted_premium: String(p.written_premium || ''),
          notes: p.notes || '',
          enabled: true,
        })));
      } else {
        setPolicyLines([{
          policy_type: d.policy_type || 'other',
          quoted_premium: d.quoted_premium || '',
          notes: d.notes || '',
          enabled: true,
        }]);
      }
      setPhase('form');
    } catch (e: any) {
      setError(e.response?.data?.detail || 'PDF extraction failed');
    } finally {
      setExtracting(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length > 0) handleFiles(dropped);
  };

  const handleSubmit = async () => {
    const enabledLines = policyLines.filter(l => l.enabled);
    if (!form.prospect_name || !form.carrier) {
      setError('Name and carrier are required');
      return;
    }
    if (enabledLines.length === 0) {
      setError('Select at least one policy line');
      return;
    }
    setSaving(true);
    setError('');
    try {
      // Calculate total premium from enabled lines
      const totalPremium = enabledLines.reduce((sum, l) => sum + (parseFloat(l.quoted_premium) || 0), 0);
      // Determine policy type
      const policyType = enabledLines.length > 1 ? 'bundled' : enabledLines[0].policy_type;
      // Build notes from all lines
      const notes = enabledLines.map(l => {
        const t = l.policy_type.charAt(0).toUpperCase() + l.policy_type.slice(1);
        const p = l.quoted_premium ? `$${parseFloat(l.quoted_premium).toLocaleString('en-US', {minimumFractionDigits: 2})}` : '';
        return `${t}: ${p}${l.notes ? ' — ' + l.notes : ''}`;
      }).join(' | ');

      const res = await quotesAPI.create({
        ...form,
        policy_type: policyType,
        quoted_premium: totalPremium || null,
        notes,
        policy_lines: enabledLines.map(l => ({
          policy_type: l.policy_type,
          premium: parseFloat(l.quoted_premium) || 0,
          notes: l.notes,
        })),
        // Coverage limits — empty strings → null so backend doesn't store 0
        coverage_dwelling: form.coverage_dwelling ? parseFloat(form.coverage_dwelling) : null,
        coverage_personal_property: form.coverage_personal_property ? parseFloat(form.coverage_personal_property) : null,
        coverage_liability: form.coverage_liability ? parseFloat(form.coverage_liability) : null,
        auto_bi_limit: form.auto_bi_limit || null,
        auto_pd_limit: form.auto_pd_limit || null,
        auto_um_limit: form.auto_um_limit || null,
      });

      // Attach PDF(s) — uploadPDFs handles 1+ in a single call
      if (pdfFiles.length > 0) {
        try { await quotesAPI.uploadPDFs(res.data.id, pdfFiles); } catch {}
      }
      onCreated(res.data);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to create quote');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="modal-bg rounded-xl w-full max-w-xl max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold page-title">
            {phase === 'upload' ? 'New Quote' : 'Review & Create Quote'}
          </h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10"><X size={18} /></button>
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 mb-4 rounded-lg bg-red-500/10 text-red-400 text-sm">
            <AlertCircle size={14} /> {error}
          </div>
        )}

        {/* Phase 1: Upload PDF */}
        {phase === 'upload' && !extracting && (
          <div className="space-y-4">
            <div
              className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer ${
                dragOver ? 'border-cyan-400 bg-cyan-400/10' : 'border-gray-600 hover:border-gray-400'
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={36} className="mx-auto mb-3 text-gray-400" />
              <p className="text-sm font-medium page-title mb-1">Drop quote PDF(s) here</p>
              <p className="text-xs page-subtitle">or click to browse — up to 5 files for one quote</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                multiple
                className="hidden"
                onChange={(e) => {
                  const fs = Array.from(e.target.files || []);
                  if (fs.length > 0) handleFiles(fs);
                }}
              />
            </div>

            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-gray-700" />
              <span className="text-xs page-subtitle">or</span>
              <div className="flex-1 h-px bg-gray-700" />
            </div>

            <button
              onClick={() => setPhase('form')}
              className="w-full py-2.5 rounded-lg text-sm font-medium filter-chip text-center"
            >
              Enter manually
            </button>
          </div>
        )}

        {/* Extracting spinner */}
        {extracting && (
          <div className="py-12 text-center">
            <Loader2 size={32} className="mx-auto mb-3 animate-spin text-cyan-400" />
            <p className="text-sm font-medium page-title">Extracting quote details...</p>
            <p className="text-xs page-subtitle mt-1">
              Reading {pdfFiles.length === 1 ? 'PDF' : `${pdfFiles.length} PDFs`} with AI
            </p>
          </div>
        )}

        {/* Phase 2: Form (pre-filled or manual) */}
        {phase === 'form' && !extracting && (
          <>
            {pdfFiles.length > 0 && (
              <div className="p-2 mb-4 rounded-lg bg-cyan-500/10 text-cyan-400 text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <FileText size={14} />
                  <span className="font-semibold">
                    Extracted from {pdfFiles.length} {pdfFiles.length === 1 ? 'file' : 'files'}:
                  </span>
                  <button onClick={() => {
                    setPdfFiles([]);
                    setPhase('upload');
                    setForm({
                      prospect_name: '', prospect_email: '', prospect_phone: '',
                      prospect_address: '', prospect_city: '', prospect_state: '', prospect_zip: '',
                      carrier: '', effective_date: '', premium_term: '6 months',
                      coverage_dwelling: '', coverage_personal_property: '', coverage_liability: '',
                      auto_bi_limit: '', auto_pd_limit: '', auto_um_limit: '',
                    });
                    setPolicyLines([{ policy_type: 'auto', quoted_premium: '', notes: '', enabled: true }]);
                  }} className="ml-auto hover:text-white" title="Start over">
                    <RotateCcw size={12} />
                  </button>
                </div>
                <ul className="ml-5 space-y-0.5">
                  {pdfFiles.map((f, i) => (
                    <li key={i} className="flex items-center justify-between gap-2">
                      <span className="truncate">• {f.name}</span>
                      <button
                        onClick={() => {
                          // Remove a single file from the list. We DON'T
                          // re-run extraction here — coverage/premium values
                          // stay as they are; producer can edit manually.
                          // The removed file just won't be attached on submit.
                          setPdfFiles(pdfFiles.filter((_, idx) => idx !== i));
                        }}
                        className="text-cyan-300/60 hover:text-rose-400 flex-shrink-0"
                        title="Remove from upload"
                      >
                        <X size={12} />
                      </button>
                    </li>
                  ))}
                </ul>
                {pdfFiles.length < 5 && (
                  <div className="ml-5 mt-2">
                    <button
                      type="button"
                      onClick={() => addPdfInputRef.current?.click()}
                      className="text-[11px] font-medium text-cyan-300 hover:text-cyan-200 underline-offset-2 hover:underline flex items-center gap-1"
                      title="Add another PDF and re-run extraction"
                    >
                      <Plus size={11} /> Add another PDF
                    </button>
                    <input
                      ref={addPdfInputRef}
                      type="file"
                      accept=".pdf"
                      multiple
                      className="hidden"
                      onChange={(e) => {
                        const newFiles = Array.from(e.target.files || []);
                        e.target.value = '';
                        if (newFiles.length === 0) return;
                        const pdfs = newFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'));
                        if (pdfs.length === 0) {
                          setError('Please select PDF files only');
                          return;
                        }
                        // Combine with existing — dedupe by filename so re-clicking
                        // the same file doesn't double-add.
                        const existingNames = new Set(pdfFiles.map(f => f.name));
                        const fresh = pdfs.filter(f => !existingNames.has(f.name));
                        if (fresh.length === 0) {
                          setError('Already added — pick a different PDF');
                          return;
                        }
                        const combined = [...pdfFiles, ...fresh].slice(0, 5);
                        // Re-extract from the combined list. handleFiles will
                        // refill the form from scratch (so premium/coverage
                        // limits reflect ALL PDFs together).
                        handleFiles(combined);
                      }}
                    />
                  </div>
                )}
                <p className="ml-5 mt-1 text-[10px] text-cyan-300/60 italic">
                  All listed PDFs will be attached to the customer's email.
                </p>
              </div>
            )}

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1 page-subtitle">Prospect Name *</label>
                <input
                  type="text"
                  value={form.prospect_name}
                  onChange={(e) => setForm({ ...form, prospect_name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm input-field"
                  placeholder="John Smith"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1 page-subtitle">Email</label>
                  <input
                    type="email"
                    value={form.prospect_email}
                    onChange={(e) => setForm({ ...form, prospect_email: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm input-field"
                    placeholder="john@example.com"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1 page-subtitle">Phone</label>
                  <input
                    type="tel"
                    value={form.prospect_phone}
                    onChange={(e) => setForm({ ...form, prospect_phone: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm input-field"
                    placeholder="(317) 555-1234"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium mb-1 page-subtitle">Address</label>
                <input
                  type="text"
                  value={form.prospect_address}
                  onChange={(e) => setForm({ ...form, prospect_address: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm input-field"
                  placeholder="123 Main St"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <input
                  type="text"
                  value={form.prospect_city}
                  onChange={(e) => setForm({ ...form, prospect_city: e.target.value })}
                  className="px-3 py-2 rounded-lg text-sm input-field"
                  placeholder="City"
                />
                <input
                  type="text"
                  value={form.prospect_state}
                  onChange={(e) => setForm({ ...form, prospect_state: e.target.value })}
                  className="px-3 py-2 rounded-lg text-sm input-field"
                  placeholder="State"
                  maxLength={2}
                />
                <input
                  type="text"
                  value={form.prospect_zip}
                  onChange={(e) => setForm({ ...form, prospect_zip: e.target.value })}
                  className="px-3 py-2 rounded-lg text-sm input-field"
                  placeholder="Zip"
                  maxLength={5}
                />
              </div>

              <div>
                <label className="block text-xs font-medium mb-1 page-subtitle">Carrier *</label>
                <select
                  value={form.carrier}
                  onChange={(e) => setForm({ ...form, carrier: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm input-field"
                >
                  <option value="">Select carrier</option>
                  {form.carrier && !carriers.includes(form.carrier) && (
                    <option value={form.carrier}>
                      {form.carrier.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                    </option>
                  )}
                  {carriers.filter(c => typeof c === 'string' && c).map((c) => (
                    <option key={c} value={c}>{c.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1 page-subtitle">Effective Date</label>
                  <input
                    type="date"
                    value={form.effective_date}
                    onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm input-field"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1 page-subtitle">Policy Term</label>
                  <select
                    value={form.premium_term}
                    onChange={(e) => setForm({ ...form, premium_term: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm input-field"
                  >
                    <option value="6 months">6 Months</option>
                    <option value="12 months">12 Months</option>
                  </select>
                </div>
              </div>

              {/* Policy Lines */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium page-subtitle">
                    Policy Lines {policyLines.length > 1 && `(${policyLines.filter(l => l.enabled).length} selected)`}
                  </label>
                  {policyLines.length === 1 && (
                    <button
                      type="button"
                      onClick={() => setPolicyLines([...policyLines, { policy_type: 'auto', quoted_premium: '', notes: '', enabled: true }])}
                      className="text-xs text-cyan-400 hover:text-cyan-300"
                    >+ Add line</button>
                  )}
                </div>
                <div className="space-y-2">
                  {policyLines.map((line, i) => (
                    <div key={i} className={`rounded-lg border p-3 transition-colors ${
                      line.enabled ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-gray-700 bg-gray-800/30 opacity-50'
                    }`}>
                      <div className="flex items-center gap-2 mb-2">
                        {policyLines.length > 1 && (
                          <input
                            type="checkbox"
                            checked={line.enabled}
                            onChange={(e) => {
                              const updated = [...policyLines];
                              updated[i] = { ...updated[i], enabled: e.target.checked };
                              setPolicyLines(updated);
                            }}
                            className="rounded"
                          />
                        )}
                        <select
                          value={line.policy_type}
                          onChange={(e) => {
                            const updated = [...policyLines];
                            updated[i] = { ...updated[i], policy_type: e.target.value };
                            setPolicyLines(updated);
                          }}
                          className="flex-1 px-2 py-1.5 rounded text-sm input-field"
                        >
                          {POLICY_TYPES.map((t) => (
                            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                          ))}
                        </select>
                        <div className="relative flex-1">
                          <DollarSign size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
                          <input
                            type="number"
                            step="0.01"
                            value={line.quoted_premium}
                            onChange={(e) => {
                              const updated = [...policyLines];
                              updated[i] = { ...updated[i], quoted_premium: e.target.value };
                              setPolicyLines(updated);
                            }}
                            className="w-full pl-6 pr-2 py-1.5 rounded text-sm input-field"
                            placeholder="Premium"
                          />
                        </div>
                      </div>
                      {line.notes && (
                        <p className="text-xs page-subtitle pl-6 truncate">{line.notes}</p>
                      )}
                    </div>
                  ))}
                </div>
                {policyLines.length > 1 && (
                  <div className="flex justify-between mt-2 text-xs page-subtitle">
                    <span>Total: {policyLines.filter(l => l.enabled).length} lines</span>
                    <span className="font-medium" style={{ color: '#0ea5e9' }}>
                      ${policyLines.filter(l => l.enabled).reduce((sum, l) => sum + (parseFloat(l.quoted_premium) || 0), 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Coverage Limits — pre-filled from PDF, editable.
                Used by Variant A's branded email to render Coverage Highlights.
                Variant B (plain text) ignores these fields. */}
            {(() => {
              const enabledTypes = policyLines.filter(l => l.enabled).map(l => l.policy_type.toLowerCase());
              const showHome = enabledTypes.some(t => ['home', 'condo', 'renters', 'landlord', 'dwelling'].includes(t));
              const showAuto = enabledTypes.includes('auto');
              if (!showHome && !showAuto) return null;
              return (
                <div className="mt-5 p-4 rounded-lg" style={{ background: 'rgba(14,165,233,0.04)', border: '1px solid rgba(14,165,233,0.2)' }}>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-cyan-400">Coverage Limits (for client-facing email)</h3>
                    <span className="text-[10px] text-slate-400 italic">A/B test: shown in branded variant only</span>
                  </div>
                  {showHome && (
                    <div className="grid grid-cols-3 gap-3 mb-3">
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Dwelling (Cov A)</label>
                        <input type="number" placeholder="350000" value={form.coverage_dwelling}
                          onChange={(e) => setForm({ ...form, coverage_dwelling: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Personal Property (Cov C)</label>
                        <input type="number" placeholder="175000" value={form.coverage_personal_property}
                          onChange={(e) => setForm({ ...form, coverage_personal_property: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Liability (Cov E)</label>
                        <input type="number" placeholder="300000" value={form.coverage_liability}
                          onChange={(e) => setForm({ ...form, coverage_liability: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                    </div>
                  )}
                  {showAuto && (
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Bodily Injury</label>
                        <input type="text" placeholder="100/300" value={form.auto_bi_limit}
                          onChange={(e) => setForm({ ...form, auto_bi_limit: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Property Damage</label>
                        <input type="text" placeholder="100" value={form.auto_pd_limit}
                          onChange={(e) => setForm({ ...form, auto_pd_limit: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium mb-1 text-slate-400">Uninsured Motorist</label>
                        <input type="text" placeholder="100/300" value={form.auto_um_limit}
                          onChange={(e) => setForm({ ...form, auto_um_limit: e.target.value })}
                          className="w-full px-3 py-2 rounded text-sm" style={{ background: 'rgba(15,23,42,0.4)', color: '#f1f5f9', border: '1px solid rgba(148,163,184,0.2)' }} />
                      </div>
                    </div>
                  )}
                  <p className="text-[10px] text-slate-500 mt-2 italic">
                    Auto formats: "100/300" = $100k/$300k split limit, "100" = $100k. Leave any blank to omit from email.
                  </p>
                </div>
              );
            })()}

            <div className="flex justify-end gap-3 mt-6">
              <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm font-medium filter-chip">
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white"
                style={{ background: '#0ea5e9' }}
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                Create Quote
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// QUOTE DETAIL MODAL (with PDF upload + send email)
// ═══════════════════════════════════════════════════════════════

function Calendar({ size }: { size: number }) {
  return <Clock size={size} />;
}

function QuoteDetailModal({ quote, onClose, onRefresh, allQuotes }: {
  quote: any;
  onClose: () => void;
  onRefresh: () => void;
  allQuotes: any[];
}) {
  const [q, setQ] = useState(quote);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [notes, setNotes] = useState('');
  const [premiumTerm, setPremiumTerm] = useState(quote.premium_term || '6 months');
  const [message, setMessage] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [previewHtml, setPreviewHtml] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);

  const sc = STATUS_COLORS[q.status] || STATUS_COLORS.quoted;

  // Refresh quote data
  const refreshQuote = async () => {
    try {
      const res = await quotesAPI.get(q.id);
      setQ(res.data);
    } catch {}
  };

  // PDF Upload — supports multiple files at once. Each call appends to
  // the quote's pdf_paths list, so users can also upload one-at-a-time.
  const handleFiles = async (files: File[]) => {
    const pdfs = files.filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfs.length === 0) {
      setMessage('Only PDF files allowed');
      setMsgType('error');
      return;
    }
    setUploading(true);
    try {
      await quotesAPI.uploadPDFs(q.id, pdfs);
      setMessage(`${pdfs.length} ${pdfs.length === 1 ? 'file' : 'files'} uploaded`);
      setMsgType('success');
      await refreshQuote();
      onRefresh();
    } catch (e: any) {
      setMessage(e.response?.data?.detail || 'Upload failed');
      setMsgType('error');
    } finally {
      setUploading(false);
    }
  };

  // Remove a single attached PDF by its index in the list
  const handleDeletePdf = async (idx: number) => {
    if (!confirm('Remove this PDF from the quote?')) return;
    try {
      await quotesAPI.deletePDF(q.id, idx);
      setMessage('PDF removed');
      setMsgType('success');
      await refreshQuote();
      onRefresh();
    } catch (e: any) {
      setMessage(e.response?.data?.detail || 'Delete failed');
      setMsgType('error');
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length > 0) handleFiles(dropped);
  };

  // Send Email
  const handleSendEmail = async () => {
    setSending(true);
    setMessage('');
    try {
      const res = await quotesAPI.sendEmail(q.id, {
        additional_notes: notes || undefined,
        premium_term: premiumTerm,
      });
      if (res.data.email_sent) {
        setMessage('Quote email sent successfully!');
        setMsgType('success');
        await refreshQuote();
        onRefresh();
      } else {
        setMessage(res.data.error || 'Failed to send');
        setMsgType('error');
      }
    } catch (e: any) {
      setMessage(e.response?.data?.detail || 'Failed to send email');
      setMsgType('error');
    } finally {
      setSending(false);
    }
  };

  // Mark won/lost
  const handleMarkConverted = async () => {
    try {
      await quotesAPI.markConverted(q.id);
      setMessage('Marked as converted!');
      setMsgType('success');
      await refreshQuote();
      onRefresh();
    } catch {}
  };

  const handleMarkLost = async () => {
    const reason = prompt('Reason for losing this quote?', 'Went with another carrier');
    if (reason === null) return;
    try {
      await quotesAPI.markLost(q.id, reason);
      setMessage('Marked as lost');
      setMsgType('success');
      await refreshQuote();
      onRefresh();
    } catch {}
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="modal-bg rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-lg font-bold page-title">{q.prospect_name}</h2>
            <div className="flex items-center gap-2 mt-1">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${sc.bg} ${sc.text}`}>{sc.label}</span>
              <span className="text-xs page-subtitle capitalize">{q.carrier?.replace(/_/g, ' ')} • {q.policy_type}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10"><X size={18} /></button>
        </div>

        {/* Message */}
        {message && (
          <div className={`flex items-center gap-2 p-3 mb-4 rounded-lg text-sm ${
            msgType === 'success' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
          }`}>
            {msgType === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
            {message}
          </div>
        )}

        {/* Info Grid */}
        <div className="grid grid-cols-2 gap-4 mb-5">
          <div className="space-y-2 text-sm">
            {q.prospect_email && (
              <div className="flex items-center gap-2 page-subtitle">
                <Mail size={13} /> {q.prospect_email}
              </div>
            )}
            {q.prospect_phone && (
              <div className="flex items-center gap-2 page-subtitle">
                <Phone size={13} /> {q.prospect_phone}
              </div>
            )}
            {(q.prospect_city || q.prospect_state) && (
              <div className="page-subtitle text-xs">
                {[q.prospect_address, q.prospect_city, q.prospect_state, q.prospect_zip].filter(Boolean).join(', ')}
              </div>
            )}
          </div>
          <div className="text-right">
            {q.quoted_premium && (
              <p className="text-2xl font-bold" style={{ color: '#0ea5e9' }}>
                ${q.quoted_premium.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </p>
            )}
            <p className="text-xs page-subtitle mt-1">Producer: {q.producer_name}</p>
            {q.effective_date && (
              <p className="text-xs page-subtitle">Effective: {new Date(q.effective_date).toLocaleDateString()}</p>
            )}
          </div>
        </div>

        {/* Related Quotes (same prospect) */}
        {(() => {
          const key = (q.prospect_email || '').toLowerCase().trim() || `name:${(q.prospect_name || '').toLowerCase().trim()}`;
          const related = allQuotes.filter((rq: any) => {
            const rKey = (rq.prospect_email || '').toLowerCase().trim() || `name:${(rq.prospect_name || '').toLowerCase().trim()}`;
            return rKey === key && rq.id !== q.id;
          });
          if (related.length === 0) return null;
          return (
            <div className="mb-5">
              <p className="text-xs font-medium page-subtitle mb-2">
                Linked Quotes ({related.length + 1} quotes for this prospect — follow-ups grouped)
              </p>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-sm">
                  <span className="page-title font-medium">{q.carrier?.replace(/_/g, ' ')} — {q.policy_type}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300">Current</span>
                </div>
                {related.map((rq: any) => (
                  <div key={rq.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/5 text-sm cursor-pointer hover:bg-white/10"
                    onClick={() => { setQ(rq); }}>
                    <span className="page-subtitle">{rq.carrier?.replace(/_/g, ' ')} — {rq.policy_type}</span>
                    <span className="text-xs page-subtitle">${rq.quoted_premium?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-gray-500 mt-2">Only the most recent quote triggers follow-up emails.</p>
            </div>
          );
        })()}

        {/* Policy Lines (bundle breakdown) */}
        {q.policy_lines && q.policy_lines.length > 1 && (
          <div className="mb-5">
            <p className="text-xs font-medium page-subtitle mb-2">Coverage Breakdown</p>
            <div className="space-y-1.5">
              {q.policy_lines.map((line: any, i: number) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/5 text-sm">
                  <span className="capitalize page-title">{(line.policy_type || '').replace(/_/g, ' ')}</span>
                  <span className="font-semibold" style={{ color: '#0ea5e9' }}>
                    ${(line.premium || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Follow-up Timeline */}
        {q.email_sent && (
          <div className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium page-subtitle">Pipeline Progress</p>
              {!q.followup_disabled ? (
                <button
                  onClick={async () => {
                    try {
                      await quotesAPI.update(q.id, { followup_disabled: true });
                      onRefresh();
                    } catch {}
                  }}
                  className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                >
                  Disable Follow-ups
                </button>
              ) : (
                <span className="text-xs px-2 py-1 rounded bg-gray-500/10 text-gray-400">
                  Follow-ups Disabled
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              {[
                { label: 'Sent', done: q.email_sent },
                { label: '3-Day', done: q.followup_3day_sent },
                { label: '7-Day', done: q.followup_7day_sent },
                { label: '14-Day', done: q.followup_14day_sent },
                { label: 'Remarket', done: q.entered_remarket },
              ].map((step, i) => (
                <React.Fragment key={i}>
                  <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                    step.done ? 'bg-cyan-500/20 text-cyan-300' : 'bg-white/5 text-gray-500'
                  }`}>
                    {step.done ? <Check size={10} /> : <Clock size={10} />}
                    {step.label}
                  </div>
                  {i < 4 && <div className={`w-4 h-0.5 ${step.done ? 'bg-cyan-500/40' : 'bg-white/10'}`} />}
                </React.Fragment>
              ))}
            </div>
          </div>
        )}

        {/* PDF Upload Zone — supports multiple files. Shows list view with
            delete-X per file when 1+ are attached, and an "Add more" link.
            Drag-drop / click both accept multiple PDFs in one go. */}
        <div className="mb-5">
          <p className="text-xs font-medium page-subtitle mb-2">
            Quote PDFs {q.pdf_count > 0 && <span className="text-emerald-400">({q.pdf_count} attached)</span>}
          </p>
          {q.pdf_count > 0 ? (
            <div className="space-y-2">
              {(q.pdf_paths || []).map((p: any, i: number) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <FileText size={16} className="text-emerald-400 flex-shrink-0" />
                  <p className="text-sm font-medium text-emerald-300 flex-1 truncate">{p.filename || `Quote_${i+1}.pdf`}</p>
                  <button
                    onClick={() => handleDeletePdf(i)}
                    className="text-rose-400/70 hover:text-rose-300 flex-shrink-0"
                    title="Remove this PDF"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full py-2 rounded-lg text-xs font-medium border border-dashed border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 transition-colors flex items-center justify-center gap-1.5"
                disabled={uploading || (q.pdf_count >= 5)}
              >
                {uploading ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                {q.pdf_count >= 5 ? 'Maximum 5 PDFs' : 'Add another PDF'}
              </button>
              <p className="text-[10px] text-emerald-400/60 italic px-1">
                All attached PDFs will be included in the customer's email.
              </p>
            </div>
          ) : (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                dragOver ? 'border-cyan-400 bg-cyan-400/10' : 'border-white/10 hover:border-white/20'
              }`}
            >
              {uploading ? (
                <Loader2 size={24} className="mx-auto animate-spin text-cyan-400" />
              ) : (
                <>
                  <Upload size={28} className="mx-auto mb-2 text-gray-400" />
                  <p className="text-sm page-subtitle">Drag & drop quote PDF(s) here</p>
                  <p className="text-xs text-gray-500 mt-1">or click to browse — up to 5 files</p>
                </>
              )}
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            multiple
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files || []);
              if (fs.length > 0) handleFiles(fs);
              e.target.value = '';
            }}
          />
        </div>

        {/* Send Email Section */}
        {!q.email_sent && q.prospect_email && q.quoted_premium && !q.pdf_uploaded && (
          <div className="flex items-center gap-2 p-3 mb-5 rounded-lg bg-yellow-500/10 text-yellow-400 text-sm">
            <AlertCircle size={14} />
            Upload a quote PDF before sending
          </div>
        )}

        {!q.email_sent && q.prospect_email && q.quoted_premium && q.pdf_uploaded && (
          <div className="mb-5 p-4 rounded-lg border border-white/10 bg-white/5">
            <p className="text-sm font-medium page-title mb-3">Send Quote Email</p>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-xs page-subtitle mb-1">Premium Term</label>
                <select
                  value={premiumTerm}
                  onChange={(e) => setPremiumTerm(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm input-field"
                >
                  <option value="6 months">6 Months</option>
                  <option value="12 months">12 Months</option>
                </select>
              </div>
            </div>
            <div className="mb-3">
              <label className="block text-xs page-subtitle mb-1">Personal Note (optional)</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 rounded-lg text-sm input-field"
                placeholder="e.g., This is $120 less than your current carrier!"
              />
            </div>

            {/* Preview Panel */}
            {showPreview && previewHtml && (
              <div className="mb-3 rounded-lg border border-white/10 overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 bg-white/5">
                  <span className="text-xs font-medium page-subtitle">Email Preview</span>
                  <button onClick={() => setShowPreview(false)} className="text-xs page-subtitle hover:text-white">Close</button>
                </div>
                <div className="bg-white rounded-b" style={{ maxHeight: '400px', overflow: 'auto' }}>
                  <iframe
                    srcDoc={previewHtml}
                    className="w-full border-0"
                    style={{ height: '400px' }}
                    title="Email Preview"
                  />
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={async () => {
                  setLoadingPreview(true);
                  try {
                    const res = await quotesAPI.emailPreview(q.id);
                    setPreviewHtml(res.data.html);
                    setShowPreview(true);
                  } catch (e: any) {
                    setMessage(e.response?.data?.detail || 'Preview failed');
                    setMsgType('error');
                  } finally {
                    setLoadingPreview(false);
                  }
                }}
                disabled={loadingPreview}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium filter-chip"
              >
                {loadingPreview ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
                Preview
              </button>
              <button
                onClick={handleSendEmail}
                disabled={sending}
                className="flex-1 flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white justify-center"
                style={{ background: '#0ea5e9' }}
              >
                {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Send Quote Email
              </button>
            </div>
            <p className="text-xs page-subtitle mt-2 opacity-60">
              Sending will also create a prospect in NowCerts
            </p>
          </div>
        )}

        {q.email_sent && (
          <div className="flex items-center justify-between gap-2 p-3 mb-5 rounded-lg bg-blue-500/10 text-blue-400 text-sm">
            <div className="flex items-center gap-2 flex-wrap">
              <Check size={14} />
              Quote emailed on {new Date(q.email_sent_at).toLocaleDateString()} at {new Date(q.email_sent_at).toLocaleTimeString()}
              {q.nowcerts_prospect_created && ' • NowCerts prospect created'}
              {q.email_variant && (
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${q.email_variant === 'A' ? 'bg-purple-500/20 text-purple-300' : 'bg-emerald-500/20 text-emerald-300'}`}
                  title={q.email_variant === 'A' ? 'Variant A: branded email with coverage limits' : 'Variant B: plain-text personal-style email'}>
                  Variant {q.email_variant}
                </span>
              )}
              {q.reply_received && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300" title={q.reply_received_at ? `Replied ${new Date(q.reply_received_at).toLocaleDateString()}` : ''}>
                  ✉ Replied
                </span>
              )}
            </div>
            <button
              onClick={handleSendEmail}
              disabled={sending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 transition-colors whitespace-nowrap"
            >
              {sending ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
              Resend
            </button>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-wrap gap-2">
          {q.status !== 'converted' && q.status !== 'lost' && (
            <>
              <button
                onClick={handleMarkConverted}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 transition-colors"
              >
                <CheckCircle size={14} /> Won — Converted to Sale
              </button>
              <button
                onClick={handleMarkLost}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-colors"
              >
                <XCircle size={14} /> Lost
              </button>
            </>
          )}
          {q.status === 'lost' && q.lost_reason && (
            <div className="text-xs page-subtitle">
              Lost reason: {q.lost_reason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
