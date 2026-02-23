import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { nonpayAPI } from '../lib/api';
import {
  Upload,
  Play,
  CheckCircle,
  XCircle,
  AlertTriangle,
  SkipForward,
  Mail,
  ClipboardList,
  Loader,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';

const api = nonpayAPI as any; // We'll call the endpoint directly

const SECTION_ICONS: Record<string, any> = {
  outstanding_todos: { icon: ClipboardList, color: 'text-amber-600', bg: 'bg-amber-50' },
  pending_non_renewals: { icon: AlertTriangle, color: 'text-purple-600', bg: 'bg-purple-50' },
  pending_cancellations: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50' },
  undeliverable_mail: { icon: Mail, color: 'text-violet-600', bg: 'bg-violet-50' },
};

const SECTION_LABELS: Record<string, string> = {
  outstanding_todos: 'Outstanding To Dos',
  pending_non_renewals: 'Pending Non-Renewals',
  pending_cancellations: 'Pending Cancellations',
  undeliverable_mail: 'Undeliverable Mail',
};

export default function NatGenTest() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [html, setHtml] = useState('');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [testing, setTesting] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    outstanding_todos: true,
    pending_non_renewals: true,
    pending_cancellations: true,
    undeliverable_mail: true,
  });

  if (loading) return null;
  if (!user) { router.push('/'); return null; }

  const runTest = async () => {
    if (!html.trim()) { setError('Paste the email HTML first'); return; }
    setTesting(true);
    setError('');
    setResult(null);

    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const token = localStorage.getItem('token');
      const resp = await fetch(`${API_URL}/api/nonpay/test-natgen-parser`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ html }),
      });
      const data = await resp.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (e: any) {
      setError(e.message || 'Request failed');
    }
    setTesting(false);
  };

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const getActionStyle = (action: string) => {
    if (action.startsWith('skip')) return 'text-slate-400 bg-slate-50';
    if (action.includes('URGENT')) return 'text-red-700 bg-red-50 font-semibold';
    if (action.includes('→')) return 'text-green-700 bg-green-50';
    return 'text-slate-600 bg-slate-50';
  };

  const totalRows = result ? Object.values(result.sections || {}).reduce((sum: number, s: any) => sum + (s.count || 0), 0) : 0;
  const actionRows = result ? Object.values(result.sections || {}).reduce((sum: number, s: any) => {
    return sum + ((s.rows || []).filter((r: any) => r.action?.includes('→')).length);
  }, 0) : 0;

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">NatGen Parser Test</h1>
          <p className="text-sm text-slate-500 mt-1">
            Paste a National General Policy Activity email HTML below to see how the system would parse and route each row.
            <strong className="text-amber-600"> DRY RUN — no emails will be sent.</strong>
          </p>
        </div>

        {/* Input area */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-semibold text-slate-700">Email HTML Source</label>
            <span className="text-xs text-slate-400">
              Right-click the email → View Source or Inspect → copy the HTML
            </span>
          </div>
          <textarea
            value={html}
            onChange={(e) => setHtml(e.target.value)}
            placeholder="Paste the full HTML of the National General Policy Activity email here..."
            className="w-full h-48 p-4 rounded-xl border border-slate-200 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 font-mono text-xs text-slate-700 resize-y"
          />
        </div>

        <div className="flex items-center space-x-3 mb-6">
          <button
            onClick={runTest}
            disabled={testing || !html.trim()}
            className="flex items-center space-x-2 px-5 py-2.5 rounded-xl bg-brand-600 text-white font-semibold hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {testing ? <Loader size={16} className="animate-spin" /> : <Play size={16} />}
            <span>{testing ? 'Parsing...' : 'Test Parse'}</span>
          </button>
          {html.trim() && (
            <button
              onClick={() => { setHtml(''); setResult(null); setError(''); }}
              className="px-4 py-2.5 rounded-xl border border-slate-200 text-slate-600 font-medium hover:bg-slate-50 transition-all text-sm"
            >
              Clear
            </button>
          )}
        </div>

        {error && (
          <div className="mb-6 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div>
            {/* Summary bar */}
            <div className="flex items-center space-x-4 mb-4 px-4 py-3 rounded-xl bg-slate-50 border border-slate-200">
              <div className="flex items-center space-x-1.5">
                <CheckCircle size={16} className="text-green-500" />
                <span className="text-sm font-semibold text-slate-700">Parse complete</span>
              </div>
              <span className="text-sm text-slate-500">
                {totalRows} total rows · {actionRows} actionable · {(totalRows as number) - (actionRows as number)} skipped
              </span>
              <span className="ml-auto px-2.5 py-1 rounded-lg bg-amber-100 text-amber-700 text-xs font-bold">
                DRY RUN
              </span>
            </div>

            {/* Sections */}
            {['outstanding_todos', 'pending_non_renewals', 'pending_cancellations', 'undeliverable_mail'].map((sectionKey) => {
              const section = result.sections?.[sectionKey];
              if (!section || section.count === 0) return null;

              const config = SECTION_ICONS[sectionKey];
              const Icon = config.icon;
              const expanded = expandedSections[sectionKey];

              return (
                <div key={sectionKey} className="mb-4">
                  <button
                    onClick={() => toggleSection(sectionKey)}
                    className="w-full flex items-center justify-between px-4 py-3 rounded-xl border border-slate-200 hover:border-slate-300 transition-all bg-white"
                  >
                    <div className="flex items-center space-x-3">
                      <div className={`p-1.5 rounded-lg ${config.bg}`}>
                        <Icon size={16} className={config.color} />
                      </div>
                      <span className="font-semibold text-slate-800">{SECTION_LABELS[sectionKey]}</span>
                      <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-xs font-bold">
                        {section.count}
                      </span>
                    </div>
                    {expanded ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                  </button>

                  {expanded && (
                    <div className="mt-2 space-y-2">
                      {(section.rows || []).map((row: any, idx: number) => (
                        <div key={idx} className="px-4 py-3 rounded-xl border border-slate-100 bg-white">
                          <div className="flex items-start justify-between">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center space-x-2 mb-1">
                                <span className="font-semibold text-slate-800 text-sm">{row.insured}</span>
                                <span className="text-xs text-slate-400">•</span>
                                <span className="text-xs font-mono text-slate-500">{row.policy}</span>
                              </div>
                              <div className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getActionStyle(row.action)}`}>
                                {row.action}
                              </div>
                              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-slate-500">
                                {row.type && <span>Type: <strong>{row.type}</strong></span>}
                                {row.cancel_type && <span>Cancel: <strong>{row.cancel_type}</strong></span>}
                                {row.reason && <span>Reason: {row.reason}</span>}
                                {row.effective_date && <span>Effective: <strong>{row.effective_date}</strong></span>}
                                {row.days_remaining != null && (
                                  <span className={row.days_remaining <= 14 ? 'text-red-600 font-semibold' : ''}>
                                    {row.days_remaining}d remaining
                                  </span>
                                )}
                                {row.cancel_date && <span>Cancel: {row.cancel_date}</span>}
                                {row.amount_due && <span>Amount: {row.amount_due}</span>}
                                {row.premium && <span>Premium: ${row.premium.toLocaleString()}</span>}
                                {row.producer && <span>Producer: {row.producer}</span>}
                                {row.phone && <span>Phone: {row.phone}</span>}
                                {row.mail_description && <span>Mail: {row.mail_description}</span>}
                                {row.due_date && <span>Due: {row.due_date}</span>}
                              </div>
                              <div className="mt-1.5 text-xs">
                                <span className="text-slate-400">Customer email: </span>
                                <span className={row.customer_email_found === 'NOT FOUND' ? 'text-red-500 font-semibold' : 'text-green-600 font-medium'}>
                                  {row.customer_email_found}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
