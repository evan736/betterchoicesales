import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { reconciliationAPI } from '../lib/api';
import {
  Upload,
  FileText,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Search,
  DollarSign,
  Users,
  ArrowRight,
  RefreshCw,
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

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user && user.role !== 'admin') router.push('/dashboard');
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

    setUploading(true);
    try {
      const res = await reconciliationAPI.upload(carrier, period, file);
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

  const loadDetail = async (importId: number) => {
    setLoadingDetail(true);
    setAgentSummary(null);
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
      await reconciliationAPI.match(importId);
      await loadImports();
      await loadDetail(importId);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Matching failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCalculate = async (importId: number) => {
    setActionLoading('calculate');
    try {
      const res = await reconciliationAPI.calculate(importId);
      setAgentSummary(res.data);
      setActiveTab('agents');
      await loadDetail(importId);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Calculation failed');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading || !user || user.role !== 'admin') return null;

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
                {CARRIERS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
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
                        <StatusBadge status={imp.status} />
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
        <div className="flex space-x-3">
          {(imp.status === 'processed' || imp.status === 'uploaded') && (
            <button
              onClick={onMatch}
              disabled={actionLoading === 'match'}
              className="inline-flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              <Search size={16} />
              <span>{actionLoading === 'match' ? 'Matching...' : 'Run Auto-Match'}</span>
            </button>
          )}
          {(imp.status === 'reconciled' || imp.matched_rows > 0) && (
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
      <p className="text-sm text-slate-600 mb-4">
        Rates based on prior month ({summary.prior_period}) written premium
      </p>
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
                  ${agent.total_agent_commission.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
                <div className="text-xs text-slate-500">agent commission</div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <span className="text-slate-500">Prior Month Premium: </span>
                <span className="font-semibold">${agent.prior_month_premium.toLocaleString()}</span>
              </div>
              <div>
                <span className="text-slate-500">This Month Premium: </span>
                <span className="font-semibold">${agent.total_premium.toLocaleString()}</span>
              </div>
              <div>
                <span className="text-slate-500">Carrier Commission: </span>
                <span className="font-semibold">${agent.total_premium.toLocaleString()}</span>
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
