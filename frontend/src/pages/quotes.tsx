import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { quotesAPI, adminAPI } from '../lib/api';
import {
  Plus, FileText, Send, Upload, X, Check, Trash2, Loader2,
  AlertCircle, Eye, Phone, Mail, ChevronDown, Search, Filter,
  Clock, CheckCircle, XCircle, RotateCcw, TrendingUp, DollarSign,
} from 'lucide-react';

const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  quoted: { bg: 'bg-gray-500/20', text: 'text-gray-300', label: 'Quoted' },
  sent: { bg: 'bg-blue-500/20', text: 'text-blue-300', label: 'Sent' },
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
  const [carriers, setCarriers] = useState<string[]>([]);
  const [selectedQuote, setSelectedQuote] = useState<any>(null);
  const [showDetail, setShowDetail] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push('/');
  }, [user, loading, router]);

  const loadQuotes = useCallback(async () => {
    try {
      setLoadingQuotes(true);
      const params: any = {};
      if (filter !== 'all') params.status = filter;
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
  }, [filter]);

  useEffect(() => {
    if (user) {
      loadQuotes();
      adminAPI.dropdownOptions().then((r: any) => {
        setCarriers(r.data.carriers || []);
      }).catch(() => {});
    }
  }, [user, loadQuotes]);

  const filtered = quotes.filter((q) => {
    if (!searchQuery) return true;
    const s = searchQuery.toLowerCase();
    return (
      q.prospect_name?.toLowerCase().includes(s) ||
      q.carrier?.toLowerCase().includes(s) ||
      q.prospect_email?.toLowerCase().includes(s) ||
      q.policy_type?.toLowerCase().includes(s)
    );
  });

  if (loading || !user) return null;

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

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="relative flex-1 max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search quotes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-lg text-sm input-field"
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {['all', 'quoted', 'sent', 'following_up', 'converted', 'lost', 'remarket'].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  filter === f ? 'text-white' : 'filter-chip'
                }`}
                style={filter === f ? { background: '#0ea5e9' } : {}}
              >
                {f === 'all' ? 'All' : STATUS_COLORS[f]?.label || f}
              </button>
            ))}
          </div>
        </div>

        {/* Quote List */}
        {loadingQuotes ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={24} className="animate-spin text-cyan-400" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20">
            <FileText size={48} className="mx-auto mb-4 text-gray-500" />
            <p className="text-gray-400">No quotes yet. Create your first quote to get started.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((q) => {
              const sc = STATUS_COLORS[q.status] || STATUS_COLORS.quoted;
              return (
                <div
                  key={q.id}
                  className="card-bg rounded-lg p-4 cursor-pointer hover:border-cyan-500/30 transition-colors border border-transparent"
                  onClick={() => { setSelectedQuote(q); setShowDetail(true); }}
                >
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    {/* Left: Name & info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-sm page-title truncate">{q.prospect_name}</h3>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${sc.bg} ${sc.text}`}>
                          {sc.label}
                        </span>
                        {q.pdf_uploaded && (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-300">PDF</span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs page-subtitle flex-wrap">
                        <span className="capitalize">{q.carrier?.replace(/_/g, ' ')}</span>
                        <span>•</span>
                        <span className="capitalize">{q.policy_type}</span>
                        {q.prospect_email && (
                          <>
                            <span>•</span>
                            <span className="truncate max-w-[200px]">{q.prospect_email}</span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Right: Premium & date */}
                    <div className="flex items-center gap-4 flex-shrink-0">
                      {q.quoted_premium && (
                        <div className="text-right">
                          <p className="text-lg font-bold" style={{ color: '#0ea5e9' }}>
                            ${q.quoted_premium.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </p>
                        </div>
                      )}
                      <div className="text-right text-xs page-subtitle">
                        {q.email_sent ? (
                          <span className="text-blue-400">
                            Sent {q.days_since_sent != null ? `${q.days_since_sent}d ago` : ''}
                          </span>
                        ) : (
                          <span>Not sent</span>
                        )}
                        <br />
                        <span>{q.producer_name}</span>
                      </div>
                    </div>
                  </div>
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
  const [form, setForm] = useState({
    prospect_name: '', prospect_email: '', prospect_phone: '',
    prospect_address: '', prospect_city: '', prospect_state: '', prospect_zip: '',
    carrier: '', policy_type: 'auto', quoted_premium: '',
    effective_date: '', notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!form.prospect_name || !form.carrier) {
      setError('Name and carrier are required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await quotesAPI.create({
        ...form,
        quoted_premium: form.quoted_premium ? parseFloat(form.quoted_premium) : null,
      });
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
          <h2 className="text-lg font-bold page-title">New Quote</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10"><X size={18} /></button>
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 mb-4 rounded-lg bg-red-500/10 text-red-400 text-sm">
            <AlertCircle size={14} /> {error}
          </div>
        )}

        <div className="space-y-4">
          {/* Prospect Info */}
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
                placeholder="(614) 555-1234"
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

          {/* Quote Details */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1 page-subtitle">Carrier *</label>
              <select
                value={form.carrier}
                onChange={(e) => setForm({ ...form, carrier: e.target.value })}
                className="w-full px-3 py-2 rounded-lg text-sm input-field"
              >
                <option value="">Select carrier</option>
                {carriers.map((c) => (
                  <option key={c} value={c}>{c.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 page-subtitle">Policy Type</label>
              <select
                value={form.policy_type}
                onChange={(e) => setForm({ ...form, policy_type: e.target.value })}
                className="w-full px-3 py-2 rounded-lg text-sm input-field"
              >
                {POLICY_TYPES.map((t) => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1 page-subtitle">Quoted Premium</label>
              <div className="relative">
                <DollarSign size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="number"
                  step="0.01"
                  value={form.quoted_premium}
                  onChange={(e) => setForm({ ...form, quoted_premium: e.target.value })}
                  className="w-full pl-8 pr-3 py-2 rounded-lg text-sm input-field"
                  placeholder="847.00"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 page-subtitle">Effective Date</label>
              <input
                type="date"
                value={form.effective_date}
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                className="w-full px-3 py-2 rounded-lg text-sm input-field"
              />
            </div>
          </div>
        </div>

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

function QuoteDetailModal({ quote, onClose, onRefresh }: {
  quote: any;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [q, setQ] = useState(quote);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [notes, setNotes] = useState('');
  const [premiumTerm, setPremiumTerm] = useState('6 months');
  const [message, setMessage] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const sc = STATUS_COLORS[q.status] || STATUS_COLORS.quoted;

  // Refresh quote data
  const refreshQuote = async () => {
    try {
      const res = await quotesAPI.get(q.id);
      setQ(res.data);
    } catch {}
  };

  // PDF Upload
  const handleFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setMessage('Only PDF files allowed');
      setMsgType('error');
      return;
    }
    setUploading(true);
    try {
      await quotesAPI.uploadPDF(q.id, file);
      setMessage(`${file.name} uploaded`);
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

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
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

        {/* Follow-up Timeline */}
        {q.email_sent && (
          <div className="mb-5">
            <p className="text-xs font-medium page-subtitle mb-2">Pipeline Progress</p>
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

        {/* PDF Upload Zone */}
        <div className="mb-5">
          <p className="text-xs font-medium page-subtitle mb-2">Quote PDF</p>
          {q.pdf_uploaded ? (
            <div className="flex items-center gap-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <FileText size={18} className="text-emerald-400" />
              <div className="flex-1">
                <p className="text-sm font-medium text-emerald-300">{q.pdf_filename}</p>
                <p className="text-xs text-emerald-400/60">PDF attached — will be included in quote email</p>
              </div>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="text-xs text-cyan-400 hover:underline"
              >
                Replace
              </button>
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
                  <p className="text-sm page-subtitle">Drag & drop quote PDF here</p>
                  <p className="text-xs text-gray-500 mt-1">or click to browse</p>
                </>
              )}
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = '';
            }}
          />
        </div>

        {/* Send Email Section */}
        {!q.email_sent && q.prospect_email && q.quoted_premium && (
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
                  <option value="6 months">6 months</option>
                  <option value="year">Year</option>
                  <option value="month">Month</option>
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
            <button
              onClick={handleSendEmail}
              disabled={sending}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white w-full justify-center"
              style={{ background: '#0ea5e9' }}
            >
              {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              Send Quote Email {q.pdf_uploaded ? '+ PDF' : '(no PDF attached)'}
            </button>
          </div>
        )}

        {q.email_sent && (
          <div className="flex items-center gap-2 p-3 mb-5 rounded-lg bg-blue-500/10 text-blue-400 text-sm">
            <Check size={14} />
            Quote emailed on {new Date(q.email_sent_at).toLocaleDateString()} at {new Date(q.email_sent_at).toLocaleTimeString()}
            {q.nowcerts_prospect_created && ' • NowCerts prospect created'}
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
