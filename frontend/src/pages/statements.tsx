import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { reconciliationAPI, payrollAPI } from '../lib/api';
import {
  Upload,
  FileText,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Search,
  DollarSign,
  Users,
  ArrowRight,
  RefreshCw,
  Download,
  X,
  Trash2,
} from 'lucide-react';

// ── Types ───────────────────────────────────────────────────────────

interface ImportRecord {
  id: number;
  filename: string;
  carrier: string;
  period: string;
  status: string;
  total_rows: number;
  matched_rows: number;
  unmatched_rows: number;
  total_premium: number;
  total_commission: number;
  created_at: string;
}

interface StatementLine {
  id: number;
  policy_number: string;
  insured_name: string;
  transaction_type: string;
  transaction_type_raw: string;
  premium_amount: number;
  commission_amount: number;
  commission_rate: number;
  producer_name: string;
  state: string;
  term_months: number;
  is_matched: boolean;
  match_confidence: string;
  assigned_agent?: string;
  agent_commission?: number;
  agent_rate?: number;
}

interface ReconciliationData {
  import: ImportRecord;
  matched_lines: StatementLine[];
  unmatched_lines: StatementLine[];
  type_summary: Record<string, { count: number; premium: number; commission: number }>;
}

// ── Carriers ────────────────────────────────────────────────────────

const CARRIERS = [
  { value: 'national_general', label: 'National General' },
  { value: 'progressive', label: 'Progressive' },
  { value: 'grange', label: 'Grange' },
  { value: 'safeco', label: 'Safeco' },
  { value: 'travelers', label: 'Travelers' },
  { value: 'geico', label: 'Geico' },
  { value: 'first_connect', label: 'First Connect' },
  { value: 'universal', label: 'Universal' },
  { value: 'nbs', label: 'NBS / Bridge Specialty' },
  { value: 'hartford', label: 'Hartford' },
  { value: 'other', label: 'Other' },
];

// ── Main Page ───────────────────────────────────────────────────────

export default function Statements() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [selectedImport, setSelectedImport] = useState<number | null>(null);
  const [reconciliation, setReconciliation] = useState<ReconciliationData | null>(null);
  const [agentSummary, setAgentSummary] = useState<any>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Upload form state
  const [carrier, setCarrier] = useState('national_general');
  const [period, setPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const [uploading, setUploading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Tab state for detail view
  const [activeTab, setActiveTab] = useState<'matched' | 'unmatched' | 'summary' | 'agents'>('summary');

  // Monthly combined pay
  const [monthlyPay, setMonthlyPay] = useState<any>(null);
  const [monthlyPayPeriod, setMonthlyPayPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const [monthlyPayLoading, setMonthlyPayLoading] = useState(false);
  const [showMonthlyPay, setShowMonthlyPay] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user && user.role?.toLowerCase() !== 'admin') router.push('/dashboard');
    else if (user) loadImports();
  }, [user, loading]);

  const loadImports = async () => {
    try {
      const res = await reconciliationAPI.list();
      setImports(res.data);
    } catch (e) {
      console.error('Failed to load imports:', e);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Check for duplicate carrier+period
    const existing = imports.find(i => i.carrier === carrier && i.period === period);
    if (existing) {
      const carrierLabel = CARRIERS.find(c => c.value === carrier)?.label || carrier;
      if (!confirm(
        `${carrierLabel} has already been uploaded for ${period} (${existing.total_rows} rows, ${existing.matched_rows} matched).\n\nThis will create a second import. Continue?`
      )) {
        e.target.value = '';
        return;
      }
    }

    setUploading(true);
    try {
      const res = await reconciliationAPI.upload(carrier, period, file);
      if (res.data.carrier_overridden) {
        const detectedLabel = CARRIERS.find(c => c.value === res.data.carrier_detected)?.label || res.data.carrier_detected;
        const selectedLabel = CARRIERS.find(c => c.value === res.data.carrier_selected)?.label || res.data.carrier_selected;
        alert(`Auto-detected: File looks like ${detectedLabel} (you selected ${selectedLabel}). Used ${detectedLabel} parser.`);
      }
      await loadImports();
      // Auto-select the new import
      setSelectedImport(res.data.id);
      loadDetail(res.data.id);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const loadDetail = async (importId: number, preserveAgentSummary = false) => {
    setLoadingDetail(true);
    if (!preserveAgentSummary) setAgentSummary(null);
    try {
      const res = await reconciliationAPI.get(importId);
      setReconciliation(res.data);
    } catch (e) {
      console.error('Failed to load detail:', e);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleMatch = async (importId: number) => {
    setActionLoading('match');
    try {
      const res = await reconciliationAPI.match(importId);
      // Show match results
      const msg = `Matched: ${res.data.matched} total (${res.data.newly_matched || 0} new), Unmatched: ${res.data.unmatched}`;
      alert(msg);
      await loadImports();
      await loadDetail(importId);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Matching failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteImport = async (importId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this import and all its matched lines? This cannot be undone.')) return;
    try {
      await reconciliationAPI.delete(importId);
      if (selectedImport === importId) {
        setSelectedImport(null);
        setReconciliation(null);
        setAgentSummary(null);
      }
      await loadImports();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Delete failed');
    }
  };

  const handleCalculate = async (importId: number) => {
    setActionLoading('calculate');
    try {
      const res = await reconciliationAPI.calculate(importId);
      setAgentSummary(res.data);
      setActiveTab('agents');
      await loadDetail(importId, true);  // preserve agent summary
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Calculation failed');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading || !user || user.role?.toLowerCase() !== 'admin') return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">
            Commission Reconciliation
          </h1>
          <p className="text-slate-600">
            Upload carrier statements, match to policies, and calculate agent commissions
          </p>
        </div>

        {/* Upload Card */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
          <h2 className="font-display text-xl font-bold text-slate-900 mb-4">
            Upload Statement
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Carrier</label>
              <select
                value={carrier}
                onChange={(e) => setCarrier(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                {CARRIERS.map((c) => {
                  const existing = imports.find(i => i.carrier === c.value && i.period === period);
                  return (
                    <option key={c.value} value={c.value}>
                      {existing ? '✓  ' : '    '}{c.label}{existing ? ` (uploaded)` : ''}
                    </option>
                  );
                })}
              </select>
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Statement Period</label>
              <input
                type="month"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="inline-flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg cursor-pointer transition-colors">
                <Upload size={18} />
                <span>{uploading ? 'Uploading...' : 'Upload File'}</span>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.pdf"
                  onChange={handleUpload}
                  className="hidden"
                  disabled={uploading}
                />
              </label>
            </div>
          </div>

          {/* Duplicate warning */}
          {(() => {
            const existing = imports.find(i => i.carrier === carrier && i.period === period);
            if (!existing) return null;
            const carrierLabel = CARRIERS.find(c => c.value === carrier)?.label || carrier;
            return (
              <div className="mt-4 flex items-start space-x-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                <AlertCircle size={20} className="text-amber-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-amber-800">
                    {carrierLabel} already uploaded for {period}
                  </p>
                  <p className="text-sm text-amber-700 mt-0.5">
                    {existing.total_rows} rows · {existing.matched_rows} matched · {existing.status.replace('_', ' ')}
                  </p>
                  <p className="text-xs text-amber-600 mt-1">
                    Uploading again will create a second import. Delete the existing one first if you want to replace it.
                  </p>
                </div>
              </div>
            );
          })()}

          {/* Period carrier checklist */}
          {imports.filter(i => i.period === period).length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Uploaded for {period}
              </p>
              <div className="flex flex-wrap gap-2">
                {CARRIERS.filter(c => c.value !== 'other' && c.value !== 'hartford').map((c) => {
                  const existing = imports.find(i => i.carrier === c.value && i.period === period);
                  return (
                    <span
                      key={c.value}
                      className={`inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                        existing
                          ? 'bg-green-50 text-green-700 border border-green-200'
                          : 'bg-slate-50 text-slate-400 border border-slate-200'
                      }`}
                    >
                      {existing ? <CheckCircle size={13} /> : <span className="w-3.5 h-3.5 rounded-full border border-slate-300 inline-block" />}
                      <span>{c.label}</span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Monthly Combined Pay */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-display text-xl font-bold text-slate-900">Monthly Agent Pay</h2>
              <p className="text-sm text-slate-500">Combined commission across all carriers for the month</p>
            </div>
            <div className="flex items-center space-x-3">
              <input
                type="month"
                value={monthlyPayPeriod}
                onChange={(e) => setMonthlyPayPeriod(e.target.value)}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />
              <button
                onClick={async () => {
                  setMonthlyPayLoading(true);
                  setShowMonthlyPay(true);
                  try {
                    const res = await reconciliationAPI.monthlyPay(monthlyPayPeriod);
                    setMonthlyPay(res.data);
                  } catch (err: any) {
                    alert(err.response?.data?.detail || 'Failed to calculate');
                  } finally {
                    setMonthlyPayLoading(false);
                  }
                }}
                disabled={monthlyPayLoading}
                className="inline-flex items-center space-x-2 bg-green-600 hover:bg-green-700 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
              >
                <DollarSign size={16} />
                <span>{monthlyPayLoading ? 'Calculating...' : 'Calculate Monthly Pay'}</span>
              </button>
            </div>
          </div>

          {showMonthlyPay && monthlyPay && !monthlyPayLoading && (
            <MonthlyPayView data={monthlyPay} />
          )}
          {showMonthlyPay && monthlyPayLoading && (
            <div className="text-center py-8">
              <RefreshCw size={24} className="mx-auto animate-spin text-green-600 mb-2" />
              <p className="text-sm text-slate-500">Calculating combined pay...</p>
            </div>
          )}
        </div>

        {/* Two-column: Import List + Detail */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Import List */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
              <h3 className="font-semibold text-slate-900 mb-3">Imports</h3>
              {imports.length === 0 ? (
                <p className="text-sm text-slate-500 text-center py-8">No imports yet</p>
              ) : (
                <div className="space-y-2 max-h-[600px] overflow-y-auto">
                  {imports.map((imp) => (
                    <button
                      key={imp.id}
                      onClick={() => { setSelectedImport(imp.id); loadDetail(imp.id); }}
                      className={`w-full text-left p-3 rounded-lg border transition-all ${
                        selectedImport === imp.id
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-semibold text-slate-900 truncate">
                          {imp.carrier.replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                        </span>
                        <div className="flex items-center space-x-1.5">
                          <StatusBadge status={imp.status} />
                          <span
                            onClick={(e) => handleDeleteImport(imp.id, e)}
                            className="text-slate-400 hover:text-red-500 transition-colors p-0.5"
                            title="Delete import"
                          >
                            <Trash2 size={14} />
                          </span>
                        </div>
                      </div>
                      <div className="text-xs text-slate-500">{imp.period} · {imp.total_rows} rows</div>
                      <div className="text-xs text-slate-500 truncate">{imp.filename}</div>
                      {imp.matched_rows > 0 && (
                        <div className="flex space-x-3 mt-1 text-xs">
                          <span className="text-green-600">{imp.matched_rows} matched</span>
                          {imp.unmatched_rows > 0 && (
                            <span className="text-amber-600">{imp.unmatched_rows} unmatched</span>
                          )}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: Detail View */}
          <div className="lg:col-span-2">
            {!selectedImport ? (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-12 text-center text-slate-500">
                <FileText size={48} className="mx-auto mb-4 opacity-40" />
                <p>Select an import or upload a new statement to get started</p>
              </div>
            ) : loadingDetail ? (
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-12 text-center">
                <RefreshCw size={32} className="mx-auto mb-4 animate-spin text-blue-600" />
                <p className="text-slate-600">Loading...</p>
              </div>
            ) : reconciliation ? (
              <DetailView
                data={reconciliation}
                agentSummary={agentSummary}
                activeTab={activeTab}
                setActiveTab={setActiveTab}
                onMatch={() => handleMatch(selectedImport)}
                onCalculate={() => handleCalculate(selectedImport)}
                actionLoading={actionLoading}
              />
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}

// ── Detail View ─────────────────────────────────────────────────────

const DetailView: React.FC<{
  data: ReconciliationData;
  agentSummary: any;
  activeTab: string;
  setActiveTab: (t: any) => void;
  onMatch: () => void;
  onCalculate: () => void;
  actionLoading: string | null;
}> = ({ data, agentSummary, activeTab, setActiveTab, onMatch, onCalculate, actionLoading }) => {
  const imp = data.import;

  return (
    <div className="space-y-4">
      {/* Header with totals */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="font-bold text-slate-900">{imp.filename}</h3>
            <p className="text-sm text-slate-500">
              {imp.carrier.replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())} · {imp.period}
            </p>
          </div>
          <StatusBadge status={imp.status} />
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
          <MiniStat label="Total Rows" value={imp.total_rows} />
          <MiniStat label="Matched" value={imp.matched_rows} color="green" />
          <MiniStat label="Unmatched" value={imp.unmatched_rows} color={imp.unmatched_rows > 0 ? 'amber' : 'green'} />
          <MiniStat label="Total Premium" value={`$${imp.total_premium.toLocaleString()}`} />
          <MiniStat label="Total Commission" value={`$${imp.total_commission.toLocaleString()}`} />
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-3">
          <button
            onClick={onMatch}
            disabled={actionLoading === 'match'}
            className="inline-flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} />
            <span>{actionLoading === 'match' ? 'Matching...' : (imp.matched_rows > 0 ? 'Re-Match Policies' : 'Run Auto-Match')}</span>
          </button>
          {imp.matched_rows > 0 && (
            <button
              onClick={onCalculate}
              disabled={actionLoading === 'calculate'}
              className="inline-flex items-center space-x-2 bg-green-600 hover:bg-green-700 text-white font-semibold px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              <DollarSign size={16} />
              <span>{actionLoading === 'calculate' ? 'Calculating...' : 'Calculate Agent Pay'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="flex border-b border-slate-200">
          {[
            { key: 'summary', label: 'Summary', icon: FileText },
            { key: 'matched', label: `Matched (${data.matched_lines.length})`, icon: CheckCircle },
            { key: 'unmatched', label: `Unmatched (${data.unmatched_lines.length})`, icon: AlertCircle },
            { key: 'agents', label: 'Agent Pay', icon: Users },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center space-x-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === key
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon size={14} />
              <span>{label}</span>
            </button>
          ))}
        </div>

        <div className="p-4">
          {activeTab === 'summary' && <SummaryTab data={data} />}
          {activeTab === 'matched' && <LinesTable lines={data.matched_lines} showAgent />}
          {activeTab === 'unmatched' && <LinesTable lines={data.unmatched_lines} />}
          {activeTab === 'agents' && <AgentPayTab summary={agentSummary} />}
        </div>
      </div>
    </div>
  );
};

// ── Summary Tab ─────────────────────────────────────────────────────

const SummaryTab: React.FC<{ data: ReconciliationData }> = ({ data }) => (
  <div>
    <h4 className="font-semibold text-slate-900 mb-3">Transaction Type Breakdown</h4>
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="text-left py-2 px-3 font-semibold text-slate-700">Type</th>
            <th className="text-right py-2 px-3 font-semibold text-slate-700">Count</th>
            <th className="text-right py-2 px-3 font-semibold text-slate-700">Premium</th>
            <th className="text-right py-2 px-3 font-semibold text-slate-700">Commission</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.type_summary)
            .sort(([, a], [, b]) => Math.abs(b.premium) - Math.abs(a.premium))
            .map(([type, s]) => (
              <tr key={type} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2 px-3 font-medium">{type}</td>
                <td className="py-2 px-3 text-right">{s.count}</td>
                <td className={`py-2 px-3 text-right ${s.premium < 0 ? 'text-red-600' : ''}`}>
                  ${s.premium.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </td>
                <td className={`py-2 px-3 text-right ${s.commission < 0 ? 'text-red-600' : ''}`}>
                  ${s.commission.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  </div>
);

// ── Lines Table ─────────────────────────────────────────────────────

const LinesTable: React.FC<{ lines: StatementLine[]; showAgent?: boolean }> = ({ lines, showAgent }) => {
  const [search, setSearch] = useState('');
  const filtered = lines.filter(
    (l) =>
      l.policy_number?.toLowerCase().includes(search.toLowerCase()) ||
      l.insured_name?.toLowerCase().includes(search.toLowerCase()) ||
      l.producer_name?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <div className="mb-3">
        <input
          type="text"
          placeholder="Search by policy, name, or producer..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"
        />
      </div>
      {filtered.length === 0 ? (
        <p className="text-center text-slate-500 py-8">No records found</p>
      ) : (
        <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-slate-200">
                <th className="text-left py-2 px-2 font-semibold text-slate-700">Policy #</th>
                <th className="text-left py-2 px-2 font-semibold text-slate-700">Insured</th>
                <th className="text-left py-2 px-2 font-semibold text-slate-700">Type</th>
                <th className="text-right py-2 px-2 font-semibold text-slate-700">Premium</th>
                <th className="text-right py-2 px-2 font-semibold text-slate-700">Comm</th>
                <th className="text-right py-2 px-2 font-semibold text-slate-700">Rate</th>
                {lines[0]?.producer_name && (
                  <th className="text-left py-2 px-2 font-semibold text-slate-700">Producer</th>
                )}
                {showAgent && (
                  <>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Agent</th>
                    <th className="text-right py-2 px-2 font-semibold text-slate-700">Agent Pay</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((line) => (
                <tr key={line.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-1.5 px-2 font-mono text-xs">{line.policy_number}</td>
                  <td className="py-1.5 px-2 max-w-[160px] truncate">{line.insured_name}</td>
                  <td className="py-1.5 px-2">
                    <TransTypeBadge type={line.transaction_type_raw || line.transaction_type} />
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono ${line.premium_amount < 0 ? 'text-red-600' : ''}`}>
                    ${line.premium_amount?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono ${line.commission_amount < 0 ? 'text-red-600' : ''}`}>
                    ${line.commission_amount?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'}
                  </td>
                  <td className="py-1.5 px-2 text-right">
                    {line.commission_rate ? `${(line.commission_rate * 100).toFixed(0)}%` : '—'}
                  </td>
                  {lines[0]?.producer_name && (
                    <td className="py-1.5 px-2 text-xs">{line.producer_name}</td>
                  )}
                  {showAgent && (
                    <>
                      <td className="py-1.5 px-2 text-xs">{line.assigned_agent || '—'}</td>
                      <td className="py-1.5 px-2 text-right font-mono text-green-700">
                        {line.agent_commission != null ? `$${line.agent_commission.toFixed(2)}` : '—'}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ── Agent Pay Tab ───────────────────────────────────────────────────

const AgentPayTab: React.FC<{ summary: any }> = ({ summary }) => {
  if (!summary) {
    return (
      <div className="text-center text-slate-500 py-8">
        <DollarSign size={40} className="mx-auto mb-3 opacity-40" />
        <p>Click "Calculate Agent Pay" to see agent commission breakdown</p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-slate-600 mb-1">
        Rates based on <span className="font-semibold">{summary.tier_based_on || summary.prior_period}</span> written premium
      </p>
      {summary.note && (
        <p className="text-xs text-amber-600 mb-4">{summary.note}</p>
      )}
      <div className="space-y-4">
        {summary.agent_summaries.map((agent: any) => (
          <div
            key={agent.agent_id}
            className="border border-slate-200 rounded-lg p-4 hover:border-blue-300 transition-colors"
          >
            <div className="flex items-center justify-between mb-2">
              <div>
                <h4 className="font-bold text-slate-900">{agent.agent_name}</h4>
                <p className="text-sm text-slate-500">
                  Tier {agent.tier_level} · {(agent.commission_rate * 100).toFixed(1)}% rate ·{' '}
                  {agent.line_count} transactions
                </p>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-green-700">
                  ${(agent.total_agent_commission || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
                <div className="text-xs text-slate-500">agent commission</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-slate-500">Prior Month Premium: </span>
                <span className="font-semibold">${(agent.prior_month_premium || 0).toLocaleString()}</span>
              </div>
              <div>
                <span className="text-slate-500">This Month Premium: </span>
                <span className="font-semibold">${(agent.total_premium || 0).toLocaleString()}</span>
              </div>
            </div>
          </div>
        ))}
        {summary.agent_summaries.length === 0 && (
          <p className="text-center text-slate-500 py-4">
            No matched policies with assigned agents found. Run matching first.
          </p>
        )}
      </div>
    </div>
  );
};

// ── Small Components ────────────────────────────────────────────────

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const styles: Record<string, string> = {
    uploaded: 'bg-slate-100 text-slate-700',
    processing: 'bg-yellow-100 text-yellow-700',
    processed: 'bg-blue-100 text-blue-700',
    reconciled: 'bg-green-100 text-green-700',
    approved: 'bg-emerald-100 text-emerald-700',
    failed: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${styles[status] || styles.uploaded}`}>
      {status}
    </span>
  );
};

const MiniStat: React.FC<{ label: string; value: string | number; color?: string }> = ({
  label,
  value,
  color,
}) => {
  const textColor = color === 'green' ? 'text-green-700' : color === 'amber' ? 'text-amber-700' : 'text-slate-900';
  return (
    <div className="bg-slate-50 rounded-lg p-2 text-center">
      <div className={`text-lg font-bold ${textColor}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
};

const TransTypeBadge: React.FC<{ type: string }> = ({ type }) => {
  if (!type) return <span className="text-slate-400">—</span>;
  const t = type.toLowerCase();
  let color = 'bg-slate-100 text-slate-600';
  if (t.includes('new')) color = 'bg-green-100 text-green-700';
  else if (t.includes('renew')) color = 'bg-blue-100 text-blue-700';
  else if (t.includes('cancel')) color = 'bg-red-100 text-red-700';
  else if (t.includes('endors') || t.includes('revis')) color = 'bg-yellow-100 text-yellow-700';

  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${color}`}>
      {type.length > 15 ? type.slice(0, 15) + '…' : type}
    </span>
  );
};


const MonthlyPayView: React.FC<{ data: any }> = ({ data }) => {
  const fmt = (n: number) => (n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const [selectedAgent, setSelectedAgent] = useState<{ id: number; name: string } | null>(null);
  const [rateAdjustments, setRateAdjustments] = useState<Record<number, number>>({});
  const [bonuses, setBonuses] = useState<Record<number, number>>({});

  const getAdjustment = (agentId: number) => rateAdjustments[agentId] || 0;
  const setAdjustment = (agentId: number, adj: number) => {
    setRateAdjustments(prev => ({ ...prev, [agentId]: adj }));
  };
  const getBonus = (agentId: number) => bonuses[agentId] || 0;
  const setBonus = (agentId: number, val: number) => {
    setBonuses(prev => ({ ...prev, [agentId]: val }));
  };

  // Compute adjusted commission for display
  const getAdjustedCommission = (agent: any) => {
    const adj = getAdjustment(agent.agent_id);
    const bonus = getBonus(agent.agent_id);
    const basePay = agent.net_agent_commission || agent.total_agent_commission;
    if (adj === 0) return basePay + bonus;
    const baseRate = agent.commission_rate;
    if (!baseRate) return basePay + bonus;
    const commissionablePremium = basePay / baseRate;
    return commissionablePremium * (baseRate + adj) + bonus;
  };

  return (
    <div className="mt-4 space-y-4">
      {data.note && (
        <p className="text-xs text-amber-600 bg-amber-50 px-3 py-1.5 rounded-lg">{data.note}</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-slate-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-900">{data.totals.total_carriers}</div>
          <div className="text-xs text-slate-500">Carriers</div>
        </div>
        <div className="bg-slate-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-900">{data.totals.total_matched_lines}</div>
          <div className="text-xs text-slate-500">Matched Lines</div>
        </div>
        <div className="bg-slate-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-900">${fmt(data.totals.total_premium)}</div>
          <div className="text-xs text-slate-500">Total Premium</div>
        </div>
        <div className="bg-green-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-green-700">${fmt(data.totals.total_agent_pay)}</div>
          <div className="text-xs text-slate-500">Total Agent Pay</div>
        </div>
      </div>

      <div>
        <h4 className="font-semibold text-slate-700 text-sm mb-2">Carriers Included</h4>
        <div className="flex flex-wrap gap-2">
          {data.carriers.map((c: any) => (
            <span key={c.carrier} className="text-xs bg-slate-100 text-slate-700 px-2.5 py-1 rounded-full font-medium">
              {c.carrier.replace('_', ' ').replace(/\b\w/g, (ch: string) => ch.toUpperCase())}
              <span className="text-slate-400 ml-1">({c.matched_rows} matched)</span>
            </span>
          ))}
        </div>
      </div>

      <div>
        <h4 className="font-semibold text-slate-700 text-sm mb-2">Agent Commission Breakdown — <span className="text-blue-600 font-normal">click an agent for full detail &amp; PDF</span></h4>
        <div className="space-y-3">
          {data.agent_summaries.map((agent: any) => (
            <div
              key={agent.agent_id}
              className="border border-slate-200 rounded-lg p-4 hover:border-green-300 hover:shadow-sm transition-all"
            >
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h4 className="font-bold text-slate-900">{agent.agent_name}</h4>
                  <p className="text-xs text-slate-500">
                    {agent.agent_role === 'retention_specialist' ? 'Retention Specialist' : 'Producer'} · Tier {agent.tier_level} · {((agent.commission_rate + getAdjustment(agent.agent_id)) * 100).toFixed(1)}% · {agent.line_count} lines
                  </p>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-green-700">${fmt(getAdjustedCommission(agent))}</div>
                  <div className="text-xs text-slate-500">net agent pay</div>
                  {getAdjustment(agent.agent_id) !== 0 && (
                    <div className={`text-xs mt-0.5 ${getAdjustment(agent.agent_id) > 0 ? 'text-blue-600' : 'text-orange-600'}`}>
                      {getAdjustment(agent.agent_id) > 0 ? '+' : ''}{(getAdjustment(agent.agent_id) * 100).toFixed(1)}% manual adjustment
                    </div>
                  )}
                  {getBonus(agent.agent_id) > 0 && (
                    <div className="text-xs mt-0.5 text-purple-600">
                      +${fmt(getBonus(agent.agent_id))} bonus
                    </div>
                  )}
                  {agent.chargeback_count > 0 && (
                    <div className="text-xs text-red-600 mt-0.5">
                      incl. ${fmt(Math.abs(agent.chargeback_premium || agent.chargebacks))} premium in chargebacks ({agent.chargeback_count})
                    </div>
                  )}
                </div>
              </div>

              {/* Rate Override & Bonus */}
              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-slate-100 flex-wrap">
                <span className="text-xs text-slate-500 mr-1">Rate Override:</span>
                <button
                  onClick={(e) => { e.stopPropagation(); setAdjustment(agent.agent_id, -0.005); }}
                  className={`px-2.5 py-1 text-xs rounded font-medium transition-all ${
                    getAdjustment(agent.agent_id) === -0.005
                      ? 'bg-orange-100 text-orange-700 ring-1 ring-orange-300'
                      : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                  }`}
                >
                  −0.5%
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); setAdjustment(agent.agent_id, 0); }}
                  className={`px-2.5 py-1 text-xs rounded font-medium transition-all ${
                    getAdjustment(agent.agent_id) === 0
                      ? 'bg-green-100 text-green-700 ring-1 ring-green-300'
                      : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                  }`}
                >
                  Default
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); setAdjustment(agent.agent_id, 0.005); }}
                  className={`px-2.5 py-1 text-xs rounded font-medium transition-all ${
                    getAdjustment(agent.agent_id) === 0.005
                      ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
                      : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                  }`}
                >
                  +0.5%
                </button>

                <div className="ml-auto flex items-center gap-1.5">
                  <span className="text-xs text-slate-500">Bonus:</span>
                  <div className="relative">
                    <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-slate-400">$</span>
                    <input
                      type="number"
                      step="0.01"
                      value={getBonus(agent.agent_id) || ''}
                      placeholder="0.00"
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        e.stopPropagation();
                        setBonus(agent.agent_id, parseFloat(e.target.value) || 0);
                      }}
                      className="w-24 pl-5 pr-2 py-1 text-xs border border-slate-200 rounded focus:outline-none focus:ring-1 focus:ring-green-300 focus:border-green-300"
                    />
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto cursor-pointer" onClick={() => setSelectedAgent({ id: agent.agent_id, name: agent.agent_name })}>
                <table className="w-full text-xs mt-2">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="text-left py-1 pr-2 font-semibold text-slate-600">Carrier</th>
                      <th className="text-right py-1 px-2 font-semibold text-slate-600">Lines</th>
                      <th className="text-right py-1 px-2 font-semibold text-slate-600">Premium</th>
                      <th className="text-right py-1 px-2 font-semibold text-red-600">Chargebacks</th>
                      <th className="text-right py-1 pl-2 font-semibold text-green-700">Agent Pay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agent.carrier_breakdown.map((cb: any) => (
                      <tr key={cb.carrier} className="border-b border-slate-50">
                        <td className="py-1 pr-2 capitalize">{cb.carrier.replace('_', ' ')}</td>
                        <td className="py-1 px-2 text-right">{cb.line_count}</td>
                        <td className="py-1 px-2 text-right">${fmt(cb.premium)}</td>
                        <td className="py-1 px-2 text-right text-red-600">{cb.chargebacks && cb.chargebacks < 0 ? `-$${fmt(Math.abs(cb.chargebacks))}` : '—'}</td>
                        <td className="py-1 pl-2 text-right font-semibold text-green-700">${fmt(cb.agent_commission)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-between text-xs text-slate-500 mt-2 pt-2 border-t border-slate-100 cursor-pointer" onClick={() => setSelectedAgent({ id: agent.agent_id, name: agent.agent_name })}>
                <span>Tier based on: ${fmt(agent.tier_premium)} written premium</span>
                <span className="text-blue-600 font-medium">Click for full detail &amp; PDF →</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Payroll Actions */}
      <PayrollActions period={data.period} rateAdjustments={rateAdjustments} bonuses={bonuses} />

      {selectedAgent && (
        <AgentSheetModal
          period={data.period}
          agentId={selectedAgent.id}
          agentName={selectedAgent.name}
          rateAdjustment={getAdjustment(selectedAgent.id)}
          bonus={getBonus(selectedAgent.id)}
          onClose={() => setSelectedAgent(null)}
        />
      )}
    </div>
  );
};

const PayrollActions: React.FC<{
  period: string;
  rateAdjustments?: Record<number, number>;
  bonuses?: Record<number, number>;
}> = ({ period, rateAdjustments = {}, bonuses = {} }) => {
  const [payrollStatus, setPayrollStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    loadPayrollStatus();
  }, [period]);

  const loadPayrollStatus = async () => {
    try {
      const res = await payrollAPI.detail(period);
      setPayrollStatus(res.data);
    } catch {
      setPayrollStatus(null);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await payrollAPI.history();
      setHistory(res.data);
      setShowHistory(true);
    } catch (err: any) {
      alert('Failed to load history');
    }
  };

  const handleSubmit = async () => {
    if (!confirm('Submit payroll for this period? This will lock the calculations.')) return;
    setLoading(true);
    try {
      // Build agent overrides from adjustments and bonuses
      const agentOverrides: Record<string, { rate_adjustment: number; bonus: number }> = {};
      const allAgentIds = new Set([
        ...Object.keys(rateAdjustments).map(Number),
        ...Object.keys(bonuses).map(Number),
      ]);
      allAgentIds.forEach(id => {
        const adj = rateAdjustments[id] || 0;
        const bon = bonuses[id] || 0;
        if (adj !== 0 || bon !== 0) {
          agentOverrides[String(id)] = { rate_adjustment: adj, bonus: bon };
        }
      });
      await payrollAPI.submit(period, agentOverrides);
      alert('Payroll submitted and locked!');
      loadPayrollStatus();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit payroll');
    } finally {
      setLoading(false);
    }
  };

  const handleMarkPaid = async () => {
    if (!confirm('Mark all agent commissions as PAID for this period?')) return;
    setLoading(true);
    try {
      await payrollAPI.markPaid(period);
      alert('Payroll marked as paid! Sales updated to Commission Paid.');
      loadPayrollStatus();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to mark paid');
    } finally {
      setLoading(false);
    }
  };

  const handleUnlock = async () => {
    if (!confirm('Unlock this payroll for re-calculation? (Admin override)')) return;
    setLoading(true);
    try {
      await payrollAPI.unlock(period);
      alert('Payroll unlocked.');
      loadPayrollStatus();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to unlock');
    } finally {
      setLoading(false);
    }
  };

  const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="border-t border-slate-200 pt-4 mt-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          {payrollStatus ? (
            <span className={`text-sm font-semibold px-3 py-1 rounded-full ${
              payrollStatus.status === 'paid' ? 'bg-green-100 text-green-700' :
              payrollStatus.status === 'submitted' ? 'bg-blue-100 text-blue-700' :
              'bg-slate-100 text-slate-600'
            }`}>
              Payroll: {payrollStatus.status.charAt(0).toUpperCase() + payrollStatus.status.slice(1)}
              {payrollStatus.is_locked && ' 🔒'}
            </span>
          ) : (
            <span className="text-sm text-slate-500">Payroll not yet submitted</span>
          )}
          {payrollStatus?.submitted_at && (
            <span className="text-xs text-slate-400">
              Submitted {new Date(payrollStatus.submitted_at).toLocaleDateString()}
            </span>
          )}
          {payrollStatus?.paid_at && (
            <span className="text-xs text-green-600">
              Paid {new Date(payrollStatus.paid_at).toLocaleDateString()}
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={loadHistory}
            className="text-xs text-blue-600 hover:underline"
          >
            View Payroll History
          </button>

          {(!payrollStatus || !payrollStatus.is_locked) && (
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
            >
              {loading ? 'Processing...' : '📋 Submit Payroll'}
            </button>
          )}

          {payrollStatus?.status === 'submitted' && (
            <button
              onClick={handleMarkPaid}
              disabled={loading}
              className="bg-green-600 hover:bg-green-700 text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
            >
              {loading ? 'Processing...' : '💰 Mark as Paid'}
            </button>
          )}

          {payrollStatus?.is_locked && (
            <button
              onClick={handleUnlock}
              disabled={loading}
              className="bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold px-3 py-2 rounded-lg disabled:opacity-50"
              title="Admin override — unlock for re-calculation"
            >
              🔓 Unlock
            </button>
          )}
        </div>
      </div>

      {showHistory && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setShowHistory(false)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-slate-200">
              <h3 className="font-bold text-lg text-slate-900">Payroll History</h3>
              <button onClick={() => setShowHistory(false)} className="text-slate-400 hover:text-slate-600 text-xl">✕</button>
            </div>
            <div className="p-4 max-h-[60vh] overflow-y-auto">
              {history.length === 0 ? (
                <p className="text-center text-slate-500 py-8">No payroll records yet</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left py-2 px-3 font-semibold text-slate-600">Period</th>
                      <th className="text-center py-2 px-3 font-semibold text-slate-600">Status</th>
                      <th className="text-right py-2 px-3 font-semibold text-slate-600">Agents</th>
                      <th className="text-right py-2 px-3 font-semibold text-slate-600">Total Premium</th>
                      <th className="text-right py-2 px-3 font-semibold text-green-700">Agent Pay</th>
                      <th className="text-center py-2 px-3 font-semibold text-slate-600">Submitted</th>
                      <th className="text-center py-2 px-3 font-semibold text-slate-600">Paid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((r: any) => (
                      <tr key={r.id} className="border-t border-slate-100">
                        <td className="py-2 px-3 font-medium">{r.period_display || r.period}</td>
                        <td className="py-2 px-3 text-center">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                            r.status === 'paid' ? 'bg-green-100 text-green-700' :
                            r.status === 'submitted' ? 'bg-blue-100 text-blue-700' :
                            'bg-slate-100 text-slate-600'
                          }`}>{r.status}</span>
                        </td>
                        <td className="py-2 px-3 text-right">{r.total_agents}</td>
                        <td className="py-2 px-3 text-right">${fmt(r.total_premium)}</td>
                        <td className="py-2 px-3 text-right font-semibold text-green-700">${fmt(r.total_agent_pay)}</td>
                        <td className="py-2 px-3 text-center text-xs">{r.submitted_at ? new Date(r.submitted_at).toLocaleDateString() : '—'}</td>
                        <td className="py-2 px-3 text-center text-xs">{r.paid_at ? new Date(r.paid_at).toLocaleDateString() : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};



const AgentSheetModal: React.FC<{
  period: string; agentId: number; agentName: string; rateAdjustment?: number; bonus?: number; onClose: () => void;
}> = ({ period, agentId, agentName, rateAdjustment = 0, bonus = 0, onClose }) => {
  const [sheet, setSheet] = useState<any>(null);
  const [loadingSheet, setLoadingSheet] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingSheet(true);
      setError(null);
      try {
        const res = await reconciliationAPI.agentSheet(period, agentId, rateAdjustment, bonus);
        if (!cancelled) setSheet(res.data);
      } catch (err: any) {
        if (!cancelled) {
          const msg = err.response?.data?.detail || err.message || 'Failed to load agent sheet';
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoadingSheet(false);
      }
    })();
    return () => { cancelled = true; };
  }, [period, agentId]);

  const handleDownloadPdf = () => {
    const token = typeof window !== 'undefined' ? (localStorage.getItem('token') || '') : '';
    const apiBase = typeof window !== 'undefined'
      ? window.location.origin.replace('-web', '-api').replace('better-choice-web', 'better-choice-api')
      : '';
    let url = `${apiBase}${reconciliationAPI.agentSheetPdfUrl(period, agentId)}`;
    const params = new URLSearchParams();
    if (rateAdjustment !== 0) params.set('rate_adjustment', String(rateAdjustment));
    if (bonus !== 0) params.set('bonus', String(bonus));
    if (params.toString()) url += `?${params.toString()}`;

    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(res => res.blob())
      .then(blob => {
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `Commission_${agentName.replace(/ /g, '_')}_${period}.pdf`;
        link.click();
        URL.revokeObjectURL(link.href);
      })
      .catch(err => alert('PDF download failed: ' + err.message));
  };

  const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-start justify-center z-50 p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-6xl my-8" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-slate-50 rounded-t-xl">
          <div>
            <h2 className="font-display text-xl font-bold text-slate-900">Commission Sheet — {agentName}</h2>
            <p className="text-sm text-slate-500">{sheet?.period_display || period}</p>
          </div>
          <div className="flex items-center space-x-3">
            {sheet && (
              <button onClick={handleDownloadPdf} className="inline-flex items-center space-x-2 bg-green-600 hover:bg-green-700 text-white font-semibold px-4 py-2 rounded-lg text-sm">
                <Download size={16} />
                <span>Download PDF</span>
              </button>
            )}
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={24} /></button>
          </div>
        </div>

        {loadingSheet ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="mx-auto animate-spin text-green-600 mb-2" />
            <p className="text-sm text-slate-500">Loading commission sheet...</p>
          </div>
        ) : error ? (
          <div className="p-12 text-center">
            <AlertCircle size={32} className="mx-auto text-red-500 mb-3" />
            <p className="text-red-600 font-medium mb-2">Failed to load commission sheet</p>
            <p className="text-sm text-slate-500">{error}</p>
            <button onClick={onClose} className="mt-4 text-sm text-blue-600 hover:underline">Close</button>
          </div>
        ) : sheet ? (
          <div className="p-4 space-y-4 max-h-[75vh] overflow-y-auto">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div><span className="text-slate-500">Role:</span> <span className="font-medium capitalize">{(sheet.agent_role || '').replace('_', ' ')}</span></div>
              <div><span className="text-slate-500">Tier:</span> <span className="font-medium">Tier {sheet.tier_level} ({((sheet.commission_rate || 0) * 100).toFixed(1)}%)</span>
                {sheet.rate_adjustment && sheet.rate_adjustment !== 0 && (
                  <span className={`ml-1 text-xs font-semibold px-1.5 py-0.5 rounded ${sheet.rate_adjustment > 0 ? 'bg-blue-100 text-blue-700' : 'bg-orange-100 text-orange-700'}`}>
                    {sheet.rate_adjustment > 0 ? '+' : ''}{(sheet.rate_adjustment * 100).toFixed(1)}% adj
                  </span>
                )}
              </div>
              <div><span className="text-slate-500">Tier Premium:</span> <span className="font-medium">${fmt(sheet.tier_premium)}</span></div>
              <div><span className="text-slate-500">Email:</span> <span className="font-medium">{sheet.agent_email}</span></div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-blue-800">${fmt(sheet.summary?.new_business_premium)}</div>
                <div className="text-xs text-blue-600">New Business Premium</div>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-slate-800">${fmt(sheet.summary?.total_paid_premium)}</div>
                <div className="text-xs text-slate-600">Total Paid Premium</div>
              </div>
              {(sheet.summary?.chargeback_count || 0) > 0 && (
                <div className="bg-red-50 rounded-lg p-3 text-center">
                  <div className="text-lg font-bold text-red-700">${fmt(Math.abs(sheet.summary?.chargeback_premium || sheet.summary?.chargebacks || 0))}</div>
                  <div className="text-xs text-red-600">Chargebacks ({sheet.summary?.chargeback_count})</div>
                </div>
              )}
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-green-700">${fmt(sheet.summary?.total_agent_commission)}</div>
                <div className="text-xs text-green-600">Commission</div>
              </div>
              {(sheet.bonus || 0) > 0 && (
                <div className="bg-purple-50 rounded-lg p-3 text-center">
                  <div className="text-lg font-bold text-purple-700">${fmt(sheet.bonus)}</div>
                  <div className="text-xs text-purple-600">Bonus</div>
                </div>
              )}
              {(sheet.bonus || 0) > 0 && (
                <div className="bg-emerald-50 rounded-lg p-3 text-center ring-2 ring-emerald-200">
                  <div className="text-lg font-bold text-emerald-700">${fmt(sheet.summary?.grand_total)}</div>
                  <div className="text-xs text-emerald-600">Grand Total</div>
                </div>
              )}
            </div>

            <div>
              <h4 className="font-semibold text-slate-700 text-sm mb-2">Transaction Detail ({sheet.summary?.total_lines || 0} lines)</h4>
              <div className="overflow-x-auto border border-slate-200 rounded-lg">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left py-2 px-2 font-semibold text-slate-600">Policy #</th>
                      <th className="text-left py-2 px-2 font-semibold text-slate-600">Insured</th>
                      <th className="text-left py-2 px-2 font-semibold text-slate-600">Carrier</th>
                      <th className="text-left py-2 px-2 font-semibold text-slate-600">Trans Type</th>
                      <th className="text-right py-2 px-2 font-semibold text-slate-600">Premium</th>
                      <th className="text-right py-2 px-2 font-semibold text-green-700">Agent Comm</th>
                      <th className="text-left py-2 px-2 font-semibold text-slate-600">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(sheet.line_items || []).map((item: any, i: number) => (
                      <tr key={i} className={`border-t border-slate-100 ${item.is_chargeback ? 'bg-red-50' : i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}`}>
                        <td className="py-1.5 px-2 font-mono">{item.policy_number}</td>
                        <td className="py-1.5 px-2">{item.insured_name || '—'}</td>
                        <td className="py-1.5 px-2 capitalize">{(item.carrier || '').replace('_', ' ')}</td>
                        <td className="py-1.5 px-2">{item.transaction_type}</td>
                        <td className="py-1.5 px-2 text-right">${fmt(item.premium)}</td>
                        <td className={`py-1.5 px-2 text-right font-semibold ${item.is_chargeback ? 'text-red-600' : 'text-green-700'}`}>
                          ${fmt(item.agent_commission)}
                        </td>
                        <td className="py-1.5 px-2 text-red-600">
                          {item.is_chargeback ? `CHARGEBACK (${item.term_months || '?'}mo term)` : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-slate-100 border-t-2 border-slate-300">
                    <tr>
                      <td colSpan={4} className="py-2 px-2 font-bold text-slate-700">TOTALS</td>
                      <td className="py-2 px-2 text-right font-bold">${fmt(sheet.summary?.new_business_premium)}</td>
                      <td className="py-2 px-2 text-right font-bold text-green-700">${fmt(sheet.summary?.total_agent_commission)}</td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};
