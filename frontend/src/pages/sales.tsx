import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { salesAPI, surveyAPI, adminAPI } from '../lib/api';
import { Plus, FileText, Upload, X, Check, Trash2, FileUp, Loader2, AlertCircle, Edit3, Calendar, ChevronDown } from 'lucide-react';

// ── Date range helpers ──────────────────────────────────────────────

function getPresetRange(preset: string): { from: string; to: string; label: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth(); // 0-indexed

  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const startOf = (year: number, month: number) => new Date(year, month, 1);
  const endOf = (year: number, month: number) => new Date(year, month + 1, 0);

  switch (preset) {
    case 'this_month':
      return { from: fmt(startOf(y, m)), to: fmt(endOf(y, m)), label: 'This Month' };
    case 'last_month':
      return { from: fmt(startOf(m === 0 ? y - 1 : y, m === 0 ? 11 : m - 1)), to: fmt(endOf(m === 0 ? y - 1 : y, m === 0 ? 11 : m - 1)), label: 'Last Month' };
    case 'this_year':
      return { from: fmt(startOf(y, 0)), to: fmt(endOf(y, 11)), label: 'This Year' };
    case 'last_year':
      return { from: fmt(startOf(y - 1, 0)), to: fmt(endOf(y - 1, 11)), label: 'Last Year' };
    case 'all':
      return { from: '', to: '', label: 'All Time' };
    default:
      return { from: '', to: '', label: 'All Time' };
  }
}

function getMonthPresets(): { value: string; label: string; from: string; to: string }[] {
  const presets = [];
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    const label = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    presets.push({
      value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      label,
      from: d.toISOString().slice(0, 10),
      to: end.toISOString().slice(0, 10),
    });
  }
  return presets;
}

export default function Sales() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sales, setSales] = useState<any[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [loadingSales, setLoadingSales] = useState(true);
  const [dropdownOptions, setDropdownOptions] = useState<any>({ lead_sources: [], carriers: [] });

  // Date filter state
  const [activePreset, setActivePreset] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [showMonthPicker, setShowMonthPicker] = useState(false);
  const monthPresets = useMemo(() => getMonthPresets(), []);

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) {
      loadSales();
      loadDropdowns();
    }
  }, [user, loading]);

  const loadDropdowns = async () => {
    try {
      const res = await adminAPI.dropdownOptions();
      setDropdownOptions(res.data);
    } catch (e) { console.error('Failed to load dropdown options:', e); }
  };

  const loadSales = async (from?: string, to?: string) => {
    setLoadingSales(true);
    try {
      const params: any = {};
      const f = from ?? dateFrom;
      const t = to ?? dateTo;
      if (f) params.date_from = f;
      if (t) params.date_to = t;
      const response = await salesAPI.list(params);
      setSales(response.data);
    } catch (error) {
      console.error('Failed to load sales:', error);
    } finally {
      setLoadingSales(false);
    }
  };

  const applyPreset = (preset: string) => {
    const range = getPresetRange(preset);
    setActivePreset(preset);
    setDateFrom(range.from);
    setDateTo(range.to);
    setShowMonthPicker(false);
    loadSales(range.from, range.to);
  };

  const applyMonth = (from: string, to: string, value: string) => {
    setActivePreset(value);
    setDateFrom(from);
    setDateTo(to);
    setShowMonthPicker(false);
    loadSales(from, to);
  };

  const applyCustomRange = () => {
    setActivePreset('custom');
    setShowMonthPicker(false);
    loadSales(dateFrom, dateTo);
  };

  // Stats
  const totalPremium = sales.reduce((sum, s) => sum + parseFloat(s.written_premium || 0), 0);
  const totalSales = sales.length;

  const [importResult, setImportResult] = useState<any>(null);
  const [importing, setImporting] = useState(false);

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    try {
      const res = await salesAPI.importCSV(file);
      setImportResult(res.data);
      loadSales(dateFrom, dateTo);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Import failed');
    } finally {
      setImporting(false);
      e.target.value = '';
    }
  };

  if (loading || !user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="font-display text-4xl font-bold text-slate-900 mb-1">Sales</h1>
            <p className="text-slate-600">Manage your policy sales and applications</p>
          </div>
          <div className="flex items-center space-x-3">
            {user.role?.toLowerCase() === 'admin' && (
              <label className="inline-flex items-center space-x-2 bg-white border-2 border-slate-300 hover:border-blue-500 text-slate-700 font-semibold px-4 py-2 rounded-lg cursor-pointer transition-colors text-sm">
                <Upload size={18} />
                <span>{importing ? 'Importing...' : 'Import CSV'}</span>
                <input type="file" accept=".csv" onChange={handleImportCSV} className="hidden" disabled={importing} />
              </label>
            )}
            <button onClick={() => setShowCreateModal(true)} className="btn-primary flex items-center space-x-2">
              <Plus size={20} />
              <span>New Sale</span>
            </button>
          </div>
        </div>

        {importResult && (
          <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg">
            <p className="font-semibold text-green-800">
              Import complete: {importResult.created} created, {importResult.skipped} skipped
              {importResult.errors?.length > 0 && `, ${importResult.errors.length} errors`}
            </p>
          </div>
        )}

        {/* Date Filter Bar */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-3 mb-6">
          <div className="flex items-center flex-wrap gap-2">
            {/* Quick presets */}
            {[
              { key: 'this_month', label: 'This Month' },
              { key: 'last_month', label: 'Last Month' },
              { key: 'this_year', label: 'This Year' },
              { key: 'all', label: 'All Time' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => applyPreset(key)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  activePreset === key
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {label}
              </button>
            ))}

            {/* Month picker dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowMonthPicker(!showMonthPicker)}
                className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  monthPresets.some(m => m.value === activePreset)
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                <Calendar size={14} />
                <span>{monthPresets.find(m => m.value === activePreset)?.label || 'Pick Month'}</span>
                <ChevronDown size={14} />
              </button>
              {showMonthPicker && (
                <div className="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-20 w-48 max-h-64 overflow-y-auto">
                  {monthPresets.map((mp) => (
                    <button
                      key={mp.value}
                      onClick={() => applyMonth(mp.from, mp.to, mp.value)}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-blue-50 ${
                        activePreset === mp.value ? 'bg-blue-50 text-blue-700 font-semibold' : 'text-slate-700'
                      }`}
                    >
                      {mp.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Custom range */}
            <div className="flex items-center space-x-1 ml-auto">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="border border-slate-300 rounded-lg px-2 py-1.5 text-sm w-36"
              />
              <span className="text-slate-400 text-sm">to</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="border border-slate-300 rounded-lg px-2 py-1.5 text-sm w-36"
              />
              <button
                onClick={applyCustomRange}
                className="px-3 py-1.5 bg-slate-700 text-white rounded-lg text-sm font-medium hover:bg-slate-800"
              >
                Apply
              </button>
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
          <div className="bg-white rounded-lg border border-slate-200 p-3 text-center">
            <div className="text-2xl font-bold text-slate-900">{totalSales}</div>
            <div className="text-xs text-slate-500">Total Sales</div>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-3 text-center">
            <div className="text-2xl font-bold text-green-700">${totalPremium.toLocaleString(undefined, { minimumFractionDigits: 0 })}</div>
            <div className="text-xs text-slate-500">Written Premium</div>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-3 text-center">
            <div className="text-2xl font-bold text-slate-900">{sales.filter(s => s.policy_type === 'bundled').length}</div>
            <div className="text-xs text-slate-500">Bundles</div>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-3 text-center">
            <div className="text-2xl font-bold text-slate-900">{sales.reduce((sum, s) => sum + (s.item_count || 1), 0)}</div>
            <div className="text-xs text-slate-500">Total Items</div>
          </div>
          <div className="bg-white rounded-lg border border-green-200 p-3 text-center">
            <div className="text-2xl font-bold text-green-700">
              ${sales.filter((s: any) => s.commission_status === 'paid').reduce((sum: number, s: any) => sum + parseFloat(s.written_premium || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}
            </div>
            <div className="text-xs text-green-600">Commission Paid</div>
          </div>
          <div className="bg-white rounded-lg border border-amber-200 p-3 text-center">
            <div className="text-2xl font-bold text-amber-600">
              ${sales.filter((s: any) => s.commission_status !== 'paid').reduce((sum: number, s: any) => sum + parseFloat(s.written_premium || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}
            </div>
            <div className="text-xs text-amber-600">Commission Pending</div>
          </div>
        </div>

        {/* Commission Paid Progress Bar */}
        {totalSales > 0 && (() => {
          const paidCount = sales.filter((s: any) => s.commission_status === 'paid').length;
          const paidPct = Math.round((paidCount / totalSales) * 100);
          return (
            <div className="mb-6 bg-white rounded-lg border border-slate-200 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-slate-700">Commission Payment Progress</span>
                <span className="text-sm text-slate-500">{paidCount} of {totalSales} policies paid ({paidPct}%)</span>
              </div>
              <div className="w-full bg-slate-200 rounded-full h-3">
                <div
                  className="bg-green-500 h-3 rounded-full transition-all duration-500"
                  style={{ width: `${paidPct}%` }}
                />
              </div>
            </div>
          );
        })()}

        {loadingSales ? (
          <div className="text-center py-12">
            <div className="animate-pulse text-brand-600 font-semibold">Loading sales...</div>
          </div>
        ) : sales.length === 0 ? (
          <div className="card text-center py-12">
            <FileText size={64} className="mx-auto mb-4 text-slate-300" />
            <h3 className="font-display text-2xl font-bold text-slate-900 mb-2">No sales yet</h3>
            <p className="text-slate-600 mb-6">Get started by uploading a PDF application</p>
            <button onClick={() => setShowCreateModal(true)} className="btn-primary">
              Create Your First Sale
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {sales.map((sale) => (
              <SaleListItem key={sale.id} sale={sale} onUpdate={loadSales} />
            ))}
          </div>
        )}

        {showCreateModal && (
          <CreateSaleModal
            onClose={() => setShowCreateModal(false)}
            onSuccess={() => { setShowCreateModal(false); loadSales(); }}
            dropdownOptions={dropdownOptions}
          />
        )}
      </main>
    </div>
  );
}

/* ========== SALE LIST ITEM ========== */
const SaleListItem: React.FC<{ sale: any; onUpdate: () => void }> = ({ sale, onUpdate }) => {
  const [deleting, setDeleting] = useState(false);
  const [sendingSig, setSendingSig] = useState(false);
  const [sigStatus, setSigStatus] = useState(sale.signature_status || 'not_sent');
  const [sendingWelcome, setSendingWelcome] = useState(false);
  const [welcomeSent, setWelcomeSent] = useState(sale.welcome_email_sent || false);
  const [addingEmail, setAddingEmail] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [savingEmail, setSavingEmail] = useState(false);
  const [currentEmail, setCurrentEmail] = useState(sale.client_email || '');

  const handleAddEmail = async () => {
    if (!newEmail.trim() || !newEmail.includes('@')) {
      alert('Please enter a valid email address');
      return;
    }
    setSavingEmail(true);
    try {
      await salesAPI.update(sale.id, { client_email: newEmail.trim() });
      setCurrentEmail(newEmail.trim());
      sale.client_email = newEmail.trim();
      setAddingEmail(false);
      setNewEmail('');
      onUpdate();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to save email');
    } finally {
      setSavingEmail(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Delete sale for ${sale.client_name} (${sale.policy_number})?`)) return;
    setDeleting(true);
    try {
      await salesAPI.delete(sale.id);
      onUpdate();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Failed to delete sale');
    } finally {
      setDeleting(false);
    }
  };

  const handleSendForSignature = async () => {
    if (!currentEmail) {
      alert('Client email is required to send for signature');
      return;
    }

    const hasSavedPdf = !!sale.application_pdf_path;

    const doSend = async (file?: File) => {
      setSendingSig(true);
      try {
        const res = await salesAPI.sendForSignature(sale.id, file);
        const sendUrl = res.data?.send_url;
        setSigStatus('draft');

        if (sendUrl) {
          window.open(sendUrl, '_blank');
          alert('BoldSign opened in a new tab. Place the signature fields on the PDF and click Send.');
        } else {
          alert('Document created but no BoldSign URL returned. Check the BoldSign dashboard.');
        }
        onUpdate();
      } catch (error: any) {
        console.error('Send for signature error:', error);
        let msg = 'Unknown error';
        if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
          msg = 'Request timed out. The PDF may be too large. Try a smaller file.';
        } else if (error.response?.data?.detail) {
          const detail = error.response.data.detail;
          msg = typeof detail === 'object' ? JSON.stringify(detail) : detail;
        } else if (error.message) {
          msg = error.message;
        }
        alert(`Error sending for signature: ${msg}`);
      } finally {
        setSendingSig(false);
      }
    };

    if (hasSavedPdf) {
      // PDF already uploaded with the sale — use it directly
      if (!confirm(`Open BoldSign to place signature fields for ${currentEmail}?`)) return;
      await doSend();
    } else {
      // No PDF on file — prompt agent to upload one
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.pdf';
      input.onchange = async (e: any) => {
        const selectedFile = e.target.files?.[0];
        if (!selectedFile) return;
        if (!confirm(`Upload "${selectedFile.name}" and open BoldSign to place signature fields for ${currentEmail}?`)) return;
        await doSend(selectedFile);
      };
      input.click();
    }
  };

  const handleCheckStatus = async () => {
    try {
      const res = await salesAPI.signatureStatus(sale.id);
      setSigStatus(res.data.status);
      if (res.data.status === 'completed') {
        alert('✓ Document has been signed!');
        onUpdate();
      } else if (res.data.status === 'sent') {
        alert('⏳ Waiting for signature...');
      } else if (res.data.status === 'declined') {
        alert('✗ Signer declined');
      } else {
        alert(`Status: ${res.data.status}`);
      }
    } catch (error: any) {
      alert('Failed to check status');
    }
  };

  const sigBadge = () => {
    switch (sigStatus) {
      case 'draft': return <span className="badge bg-blue-100 text-blue-800">📝 Draft - Place Fields</span>;
      case 'sent': return <span className="badge bg-yellow-100 text-yellow-800">⏳ Awaiting Signature</span>;
      case 'completed': return <span className="badge bg-green-100 text-green-800">✓ Signed</span>;
      case 'declined': return <span className="badge bg-red-100 text-red-800">✗ Declined</span>;
      default: return null;
    }
  };

  return (
    <div className="card hover:shadow-xl transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center space-x-3 mb-3">
            <h3 className="font-display text-xl font-bold text-slate-900">{sale.client_name}</h3>
            <span className={`badge ${sale.status === 'active' ? 'badge-success' : sale.status === 'pending' ? 'badge-warning' : 'badge-danger'}`}>
              {sale.status}
            </span>
            {sale.commission_status === 'paid' ? (
              <span className="badge bg-green-100 text-green-700">💰 Comm Paid</span>
            ) : (
              <span className="badge bg-amber-100 text-amber-700">⏳ Comm Pending</span>
            )}
            {sale.welcome_email_sent && (
              <span className="badge bg-purple-100 text-purple-700">📧 Welcome Sent</span>
            )}
            {sale.policy_type && (
              <span className="badge bg-blue-100 text-blue-800 capitalize">{sale.policy_type.replace(/_/g, ' ')}</span>
            )}
            {sigBadge()}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2">
            <InfoItem label="Policy #" value={sale.policy_number} />
            <InfoItem label="Premium" value={`$${parseFloat(sale.written_premium).toLocaleString()}`} />
            <InfoItem label="Carrier" value={sale.carrier || '—'} />
            <InfoItem label="Items" value={sale.item_count} />
            <InfoItem label="Lead Source" value={(sale.lead_source || '').replace(/_/g, ' ')} />
            <InfoItem label="State" value={sale.state || '—'} />
            <InfoItem label="Email" value={currentEmail || '—'} />
            <InfoItem label="Phone" value={sale.client_phone || '—'} />
          </div>
          {/* Add Email prompt when missing */}
          {!currentEmail && (
            <div className="mt-2 mb-1">
              {addingEmail ? (
                <div className="flex items-center gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg">
                  <span className="text-amber-600 text-sm">📧</span>
                  <input
                    type="email"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="client@email.com"
                    className="flex-1 border border-amber-300 rounded-md px-2 py-1.5 text-sm focus:ring-2 focus:ring-amber-500 focus:border-amber-500 outline-none bg-white"
                    onKeyDown={(e) => e.key === 'Enter' && handleAddEmail()}
                    autoFocus
                  />
                  <button onClick={handleAddEmail} disabled={savingEmail} className="px-3 py-1.5 bg-amber-600 text-white rounded-md text-sm font-semibold hover:bg-amber-700 disabled:opacity-50">
                    {savingEmail ? '...' : 'Save'}
                  </button>
                  <button onClick={() => { setAddingEmail(false); setNewEmail(''); }} className="px-2 py-1.5 text-slate-400 hover:text-slate-600 text-sm">
                    ✕
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setAddingEmail(true)}
                  className="flex items-center gap-1.5 text-sm text-amber-700 hover:text-amber-800 font-semibold bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-lg px-3 py-1.5 transition-all"
                >
                  <span>⚠️</span> Add Email — required for welcome email &amp; e-sign
                </button>
              )}
            </div>
          )}
        </div>
        <div className="ml-4 flex flex-col gap-2">
          {/* Send for Signature */}
          {currentEmail && sigStatus !== 'completed' && (
            <button
              onClick={handleSendForSignature}
              disabled={sendingSig}
              className="flex items-center space-x-2 px-3 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-all text-sm font-semibold"
            >
              <FileText size={16} />
              <span>{sendingSig ? 'Uploading...' : (sigStatus === 'sent' || sigStatus === 'draft' ? 'Resend for Signature' : 'Send for Signature')}</span>
            </button>
          )}
          {/* Check Status */}
          {(sigStatus === 'sent' || sigStatus === 'draft') && (
            <button
              onClick={handleCheckStatus}
              className="flex items-center space-x-2 px-3 py-2 rounded-lg border border-yellow-300 text-yellow-700 hover:bg-yellow-50 transition-all text-sm font-semibold"
            >
              <span>Check Status</span>
            </button>
          )}
          {/* Send Welcome Email */}
          {currentEmail && (
            <div className="relative">
              <button
                onClick={async () => {
                  const hasPdf = !!sale.application_pdf_path;

                  // Build options
                  const choices = ['Send without attachment'];
                  if (hasPdf) choices.push('Attach saved application PDF');
                  choices.push('Attach a different PDF...');

                  const msg = choices.map((c, i) => `${i + 1}. ${c}`).join('\n');
                  const pick = prompt(
                    `Send welcome email to ${currentEmail}?\n\n${msg}\n\nEnter choice (1-${choices.length}):`,
                    '1'
                  );
                  if (!pick) return;

                  const choice = parseInt(pick.trim(), 10);
                  if (isNaN(choice) || choice < 1 || choice > choices.length) return;

                  setSendingWelcome(true);
                  try {
                    if (choice === 1) {
                      // No attachment
                      await surveyAPI.sendWelcome(sale.id);
                    } else if (hasPdf && choice === 2) {
                      // Attach saved PDF
                      await surveyAPI.sendWelcome(sale.id, { attachSavedPdf: true });
                    } else {
                      // Upload a different PDF
                      const uploaded = await new Promise<File | null>((resolve) => {
                        const input = document.createElement('input');
                        input.type = 'file';
                        input.accept = '.pdf';
                        input.onchange = (e: any) => resolve(e.target.files?.[0] || null);
                        input.click();
                      });
                      if (!uploaded) { setSendingWelcome(false); return; }
                      await surveyAPI.sendWelcome(sale.id, { file: uploaded });
                    }
                    setWelcomeSent(true);
                    alert('Welcome email sent!');
                  } catch (err: any) {
                    alert(err.response?.data?.detail || 'Failed to send welcome email');
                  } finally {
                    setSendingWelcome(false);
                  }
                }}
                disabled={sendingWelcome}
                className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-semibold transition-all ${
                  welcomeSent
                    ? 'border border-green-200 text-green-700 bg-green-50'
                    : 'border border-purple-200 text-purple-700 hover:bg-purple-50'
                }`}
              >
                <span>{sendingWelcome ? 'Sending...' : welcomeSent ? '✓ Welcome Sent' : '📧 Send Welcome Email'}</span>
              </button>
            </div>
          )}
          {/* Delete */}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="flex items-center space-x-2 px-3 py-2 rounded-lg border border-red-200 text-red-600 hover:bg-red-50 hover:border-red-400 transition-all text-sm font-semibold"
          >
            <Trash2 size={16} />
            <span>{deleting ? '...' : 'Delete'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

const InfoItem: React.FC<{ label: string; value: any }> = ({ label, value }) => (
  <div>
    <div className="text-xs text-slate-500 font-medium mb-0.5">{label}</div>
    <div className="text-sm font-semibold text-slate-900 capitalize">{value}</div>
  </div>
);

/* ========== CREATE SALE MODAL — 3 STEPS ========== */
type Step = 'upload' | 'review' | 'manual';

const CreateSaleModal: React.FC<{ onClose: () => void; onSuccess: () => void; dropdownOptions: any }> = ({ onClose, onSuccess, dropdownOptions }) => {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [leadSource, setLeadSource] = useState('referral');
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState('');
  const [extractedData, setExtractedData] = useState<any>(null);
  const [policies, setPolicies] = useState<any[]>([]);
  const [clientInfo, setClientInfo] = useState({ client_name: '', client_email: '', client_phone: '', carrier: '', state: '' });
  const [saving, setSaving] = useState(false);
  const [saveResults, setSaveResults] = useState<any[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [welcomeAttach, setWelcomeAttach] = useState<'none' | 'application' | 'custom'>('none');
  const [welcomeFile, setWelcomeFile] = useState<File | null>(null);

  // Drag and drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(true); }, []);
  const handleDragLeave = useCallback(() => setDragOver(false), []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile?.type === 'application/pdf') setFile(droppedFile);
    else setExtractError('Please upload a PDF file');
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  // Step 1: Extract PDF
  const handleExtract = async () => {
    if (!file) return;
    setExtracting(true);
    setExtractError('');
    try {
      const res = await salesAPI.extractPDF(file);
      const data = res.data.data;
      setExtractedData(data);
      setClientInfo({
        client_name: data.client_name || '',
        client_email: data.client_email || '',
        client_phone: data.client_phone || '',
        carrier: data.carrier || '',
        state: data.state || '',
      });
      // Build policies array for review
      const pols = (data.policies || []).map((p: any, i: number) => ({
        ...p,
        policy_number: p.policy_number || '',
        written_premium: p.written_premium || 0,
        item_count: p.item_count || 1,
        policy_type: p.policy_type || 'other',
        include: true,
      }));
      setPolicies(pols.length > 0 ? pols : [{
        policy_number: '', policy_type: 'auto', written_premium: data.total_premium || 0,
        item_count: data.total_items || 1, effective_date: null, notes: '', include: true,
      }]);
      setStep('review');
    } catch (err: any) {
      setExtractError(err.response?.data?.detail || 'Failed to extract PDF data. Please try again or enter manually.');
    } finally {
      setExtracting(false);
    }
  };

  // Step 2: Save reviewed data
  const handleSave = async () => {
    setSaving(true);
    const results: any[] = [];
    const includedPolicies = policies.filter(p => p.include);
    
    // Auto-suffix duplicate policy numbers
    const policyNumbers: Record<string, number> = {};
    for (const pol of includedPolicies) {
      const base = pol.policy_number;
      if (!base) { alert('Please enter a policy number for all policies'); setSaving(false); return; }
      if (policyNumbers[base] !== undefined) {
        policyNumbers[base]++;
        pol._saveNumber = `${base}-${pol.policy_type?.toUpperCase()?.slice(0,3) || policyNumbers[base]}`;
      } else {
        policyNumbers[base] = 0;
        pol._saveNumber = base;
      }
    }

    const createdSaleIds: number[] = [];

    for (const pol of includedPolicies) {
      try {
        // Fix effective_date format — append time if it's just a date
        let effectiveDate = pol.effective_date || undefined;
        if (effectiveDate && typeof effectiveDate === 'string' && !effectiveDate.includes('T')) {
          effectiveDate = `${effectiveDate}T00:00:00`;
        }
        const res = await salesAPI.createFromPdf({
          policy_number: pol._saveNumber || pol.policy_number,
          written_premium: parseFloat(pol.written_premium) || 0,
          lead_source: leadSource,
          policy_type: pol.policy_type || undefined,
          carrier: clientInfo.carrier || undefined,
          state: clientInfo.state || undefined,
          client_name: clientInfo.client_name,
          client_email: clientInfo.client_email || undefined,
          client_phone: clientInfo.client_phone || undefined,
          item_count: parseInt(pol.item_count) || 1,
          effective_date: effectiveDate,
          notes: pol.notes || undefined,
        });
        
        // Upload the PDF to the sale for e-signature later
        const saleId = res.data.sale?.id;
        if (saleId && file) {
          try {
            await salesAPI.uploadPDF(saleId, file);
          } catch (uploadErr) {
            console.warn('PDF upload failed but sale was created:', uploadErr);
          }
        }

        if (saleId) createdSaleIds.push(saleId);
        
        results.push({ success: true, policy: pol._saveNumber || pol.policy_number, household: res.data.household, saleId });
      } catch (err: any) {
        const detail = err.response?.data?.detail;
        const errMsg = typeof detail === 'object' ? JSON.stringify(detail) : (detail || 'Failed to save');
        results.push({ success: false, policy: pol._saveNumber || pol.policy_number, error: errMsg });
      }
    }
    setSaveResults(results);

    // Send welcome emails for all successfully created sales
    if (clientInfo.client_email && createdSaleIds.length > 0) {
      // Only send welcome email for the first sale to avoid spamming
      const firstSaleId = createdSaleIds[0];
      try {
        if (welcomeAttach === 'application' && file) {
          await surveyAPI.sendWelcome(firstSaleId, { file });
        } else if (welcomeAttach === 'custom' && welcomeFile) {
          await surveyAPI.sendWelcome(firstSaleId, { file: welcomeFile });
        } else {
          await surveyAPI.sendWelcome(firstSaleId);
        }
      } catch (err) {
        console.warn('Welcome email failed but sale was created:', err);
      }
    }

    const anySuccess = results.some(r => r.success);
    if (anySuccess && results.every(r => r.success)) {
      setTimeout(() => onSuccess(), 1500);
    }
    setSaving(false);
  };

  // Manual entry fallback
  const [manualData, setManualData] = useState({
    policy_number: '', written_premium: '', lead_source: 'referral', policy_type: '',
    carrier: '', state: '', client_name: '', client_email: '', client_phone: '', item_count: 1, notes: '',
  });

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await salesAPI.create({
        ...manualData,
        written_premium: parseFloat(manualData.written_premium),
        policy_type: manualData.policy_type || undefined,
        carrier: manualData.carrier || undefined,
        state: manualData.state || undefined,
      });
      onSuccess();
    } catch (err: any) {
      setExtractError(err.response?.data?.detail || 'Failed to create sale');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="font-display text-2xl font-bold text-slate-900">
            {step === 'upload' ? 'New Sale — Upload Application' : step === 'review' ? 'Review Extracted Data' : 'Manual Entry'}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={24} /></button>
        </div>

        <div className="p-6">
          {/* STEP 1: Upload */}
          {step === 'upload' && (
            <div className="space-y-6">
              {/* Drop Zone */}
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
                  dragOver ? 'border-brand-500 bg-brand-50' : file ? 'border-green-400 bg-green-50' : 'border-slate-300 hover:border-brand-400 hover:bg-slate-50'
                }`}
                onClick={() => document.getElementById('pdf-input')?.click()}
              >
                <input id="pdf-input" type="file" accept=".pdf" onChange={handleFileSelect} className="hidden" />
                {file ? (
                  <div className="flex flex-col items-center">
                    <Check size={48} className="text-green-500 mb-3" />
                    <p className="font-bold text-green-700 text-lg">{file.name}</p>
                    <p className="text-green-600 text-sm mt-1">{(file.size / 1024).toFixed(0)} KB — Ready to extract</p>
                    <button onClick={(e) => { e.stopPropagation(); setFile(null); }} className="mt-3 text-sm text-red-500 hover:text-red-700">Remove</button>
                  </div>
                ) : (
                  <div className="flex flex-col items-center">
                    <FileUp size={48} className="text-slate-400 mb-3" />
                    <p className="font-bold text-slate-700 text-lg">Drag & drop your PDF application here</p>
                    <p className="text-slate-500 text-sm mt-1">or click to browse</p>
                  </div>
                )}
              </div>

              {/* Lead Source */}
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-2">Lead Source *</label>
                <select value={leadSource} onChange={(e) => setLeadSource(e.target.value)} className="input-field">
                  {(dropdownOptions?.lead_sources || []).map((s: any) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                  {(!dropdownOptions?.lead_sources?.length) && <option value="referral">Referral</option>}
                </select>
              </div>

              {extractError && (
                <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
                  <AlertCircle size={20} className="text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-red-800 text-sm">{extractError}</p>
                    <button onClick={() => { setExtractError(''); setStep('manual'); }} className="text-red-600 text-sm font-semibold mt-1 hover:underline">
                      Enter manually instead →
                    </button>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-between pt-4 border-t border-slate-200">
                <button onClick={() => setStep('manual')} className="text-brand-600 hover:text-brand-700 font-semibold text-sm">
                  <Edit3 size={16} className="inline mr-1" /> Enter manually
                </button>
                <div className="flex gap-3">
                  <button onClick={onClose} className="btn-secondary">Cancel</button>
                  <button
                    onClick={handleExtract}
                    disabled={!file || extracting}
                    className="btn-primary flex items-center gap-2"
                  >
                    {extracting ? <><Loader2 size={18} className="animate-spin" /> Analyzing PDF...</> : <>Submit</>}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: Review */}
          {step === 'review' && (
            <div className="space-y-6">
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
                Review the extracted data below. Edit any fields that need correction, then save.
              </div>

              {/* Client Info */}
              <div className="card bg-slate-50">
                <h3 className="font-bold text-slate-900 mb-3">Client Information</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Client Name *</label>
                    <input value={clientInfo.client_name} onChange={(e) => setClientInfo({ ...clientInfo, client_name: e.target.value })} className="input-field" required />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Carrier</label>
                    <input value={clientInfo.carrier} onChange={(e) => setClientInfo({ ...clientInfo, carrier: e.target.value })} className="input-field" />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Email</label>
                    <input value={clientInfo.client_email} onChange={(e) => setClientInfo({ ...clientInfo, client_email: e.target.value })} className="input-field" />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Phone</label>
                    <input value={clientInfo.client_phone} onChange={(e) => setClientInfo({ ...clientInfo, client_phone: e.target.value })} className="input-field" />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">State</label>
                    <input value={clientInfo.state} onChange={(e) => setClientInfo({ ...clientInfo, state: e.target.value.toUpperCase().slice(0, 2) })} className="input-field" maxLength={2} />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Lead Source</label>
                    <select value={leadSource} onChange={(e) => setLeadSource(e.target.value)} className="input-field capitalize">
                      {(dropdownOptions?.lead_sources || []).map((s: any) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Policies */}
              <div>
                <h3 className="font-bold text-slate-900 mb-3">Policies Found ({policies.filter(p => p.include).length})</h3>
                <div className="space-y-4">
                  {policies.map((pol, i) => (
                    <div key={i} className={`card border-2 ${pol.include ? 'border-brand-200' : 'border-slate-200 opacity-50'}`}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <input type="checkbox" checked={pol.include} onChange={() => {
                            const next = [...policies]; next[i].include = !next[i].include; setPolicies(next);
                          }} className="w-4 h-4 rounded border-slate-300" />
                          <span className="font-bold text-slate-900 capitalize">{(pol.policy_type || 'policy').replace(/_/g, ' ')}</span>
                        </div>
                        {pol.notes && <span className="text-xs text-slate-500">{pol.notes}</span>}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div>
                          <label className="block text-xs font-semibold text-slate-600 mb-1">Policy # *</label>
                          <input value={pol.policy_number} onChange={(e) => {
                            const next = [...policies]; next[i].policy_number = e.target.value; setPolicies(next);
                          }} className="input-field" placeholder="Enter policy number" />
                        </div>
                        <div>
                          <label className="block text-xs font-semibold text-slate-600 mb-1">Type</label>
                          <select value={pol.policy_type} onChange={(e) => {
                            const next = [...policies]; next[i].policy_type = e.target.value; setPolicies(next);
                          }} className="input-field capitalize">
                            {['auto','home','renters','condo','landlord','umbrella','motorcycle','boat','rv','life','health','bundled','commercial','other'].map(t => (
                              <option key={t} value={t}>{t}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-semibold text-slate-600 mb-1">Premium</label>
                          <input type="number" step="0.01" value={pol.written_premium} onChange={(e) => {
                            const next = [...policies]; next[i].written_premium = e.target.value; setPolicies(next);
                          }} className="input-field" />
                        </div>
                        <div>
                          <label className="block text-xs font-semibold text-slate-600 mb-1">Items</label>
                          <input type="number" min="1" value={pol.item_count} onChange={(e) => {
                            const next = [...policies]; next[i].item_count = e.target.value; setPolicies(next);
                          }} className="input-field" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Totals */}
                <div className="mt-4 p-4 bg-brand-50 rounded-lg border border-brand-200">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-brand-900">
                      Total: {policies.filter(p => p.include).length} {policies.filter(p => p.include).length === 1 ? 'policy' : 'policies'},
                      {' '}{policies.filter(p => p.include).reduce((s, p) => s + (parseInt(p.item_count) || 1), 0)} items
                    </span>
                    <span className="font-bold text-brand-700 text-lg">
                      ${policies.filter(p => p.include).reduce((s, p) => s + (parseFloat(p.written_premium) || 0), 0).toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>

              {/* Save Results */}
              {saveResults.length > 0 && (
                <div className="space-y-2">
                  {saveResults.map((r, i) => (
                    <div key={i} className={`p-3 rounded-lg text-sm ${r.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'}`}>
                      {r.success ? `✓ ${r.policy} saved` : `✗ ${r.policy}: ${r.error}`}
                      {r.household?.is_bundle && <span className="ml-2 font-semibold">📦 Household: {r.household.total_items} items, ${r.household.total_premium.toLocaleString()}</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Welcome Email Attachment */}
              {clientInfo.client_email ? (
                <div className="card bg-purple-50 border border-purple-200">
                  <h3 className="font-bold text-purple-900 mb-2">📧 Welcome Email</h3>
                  <p className="text-sm text-purple-700 mb-3">
                    A welcome email will be sent to <strong>{clientInfo.client_email}</strong> when you save.
                  </p>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer text-sm">
                      <input type="radio" name="welcomeAttach" value="none" checked={welcomeAttach === 'none'} onChange={() => { setWelcomeAttach('none'); setWelcomeFile(null); }} className="w-4 h-4" />
                      <span className="text-slate-700">No attachment</span>
                    </label>
                    {file && (
                      <label className="flex items-center gap-2 cursor-pointer text-sm">
                        <input type="radio" name="welcomeAttach" value="application" checked={welcomeAttach === 'application'} onChange={() => { setWelcomeAttach('application'); setWelcomeFile(null); }} className="w-4 h-4" />
                        <span className="text-slate-700">Attach uploaded application <span className="text-purple-600 font-medium">({file.name})</span></span>
                      </label>
                    )}
                    <label className="flex items-center gap-2 cursor-pointer text-sm">
                      <input type="radio" name="welcomeAttach" value="custom" checked={welcomeAttach === 'custom'} onChange={() => setWelcomeAttach('custom')} className="w-4 h-4" />
                      <span className="text-slate-700">Attach a different PDF</span>
                    </label>
                    {welcomeAttach === 'custom' && (
                      <div className="ml-6 mt-1">
                        <input
                          type="file"
                          accept=".pdf"
                          onChange={(e) => setWelcomeFile(e.target.files?.[0] || null)}
                          className="text-sm text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-purple-100 file:text-purple-700 hover:file:bg-purple-200"
                        />
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="card bg-amber-50 border border-amber-300">
                  <h3 className="font-bold text-amber-900 mb-2">⚠️ No Client Email</h3>
                  <p className="text-sm text-amber-700 mb-3">
                    Add a client email above to send a welcome email with their policy details, survey link, and carrier resources.
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      type="email"
                      placeholder="client@email.com"
                      value={clientInfo.client_email}
                      onChange={(e) => setClientInfo({ ...clientInfo, client_email: e.target.value })}
                      className="flex-1 border border-amber-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500 focus:border-amber-500 outline-none bg-white"
                    />
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
                <button onClick={() => setStep('upload')} className="btn-secondary">← Back</button>
                <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-2">
                  {saving ? <><Loader2 size={18} className="animate-spin" /> Saving...</> : <>Save {policies.filter(p => p.include).length} {policies.filter(p => p.include).length === 1 ? 'Policy' : 'Policies'}</>}
                </button>
              </div>
            </div>
          )}

          {/* MANUAL ENTRY FALLBACK */}
          {step === 'manual' && (
            <form onSubmit={handleManualSubmit} className="space-y-6">
              {extractError && (
                <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">{extractError}</div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Policy Number *</label>
                  <input value={manualData.policy_number} onChange={(e) => setManualData({ ...manualData, policy_number: e.target.value })} className="input-field" required />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Written Premium *</label>
                  <input type="number" step="0.01" value={manualData.written_premium} onChange={(e) => setManualData({ ...manualData, written_premium: e.target.value })} className="input-field" required />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Client Name *</label>
                  <input value={manualData.client_name} onChange={(e) => setManualData({ ...manualData, client_name: e.target.value })} className="input-field" required />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Lead Source *</label>
                  <select value={manualData.lead_source} onChange={(e) => setManualData({ ...manualData, lead_source: e.target.value })} className="input-field">
                    {(dropdownOptions?.lead_sources || []).map((s: any) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Policy Type</label>
                  <select value={manualData.policy_type} onChange={(e) => setManualData({ ...manualData, policy_type: e.target.value })} className="input-field">
                    <option value="">Select...</option>
                    {['auto','home','renters','condo','landlord','umbrella','motorcycle','boat','rv','life','health','bundled','commercial','other'].map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Carrier</label>
                  <select value={manualData.carrier} onChange={(e) => setManualData({ ...manualData, carrier: e.target.value })} className="input-field">
                    <option value="">Select carrier...</option>
                    {(dropdownOptions?.carriers || []).map((c: any) => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">State</label>
                  <input value={manualData.state} onChange={(e) => setManualData({ ...manualData, state: e.target.value.toUpperCase().slice(0, 2) })} className="input-field" maxLength={2} />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Items</label>
                  <input type="number" min="1" value={manualData.item_count} onChange={(e) => setManualData({ ...manualData, item_count: parseInt(e.target.value) || 1 })} className="input-field" />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Email</label>
                  <input type="email" value={manualData.client_email} onChange={(e) => setManualData({ ...manualData, client_email: e.target.value })} className="input-field" />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-2">Phone</label>
                  <input value={manualData.client_phone} onChange={(e) => setManualData({ ...manualData, client_phone: e.target.value })} className="input-field" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-2">Notes</label>
                <textarea value={manualData.notes} onChange={(e) => setManualData({ ...manualData, notes: e.target.value })} className="input-field" rows={2} />
              </div>
              <div className="flex items-center justify-between pt-4 border-t border-slate-200">
                <button type="button" onClick={() => setStep('upload')} className="text-brand-600 hover:text-brand-700 font-semibold text-sm">← Upload PDF instead</button>
                <div className="flex gap-3">
                  <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
                  <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Creating...' : 'Create Sale'}</button>
                </div>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
