import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { timeclockAPI } from '../lib/api';
import {
  Clock,
  LogIn,
  LogOut,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Shield,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  TrendingDown,
  Minus,
  Users,
  MapPin,
} from 'lucide-react';

// ── Main Page ───────────────────────────────────────────────────────

export default function TimeClock() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [clockStatus, setClockStatus] = useState<any>(null);
  const [history, setHistory] = useState<any>(null);
  const [adminSummary, setAdminSummary] = useState<any>(null);
  const [selectedEmployee, setSelectedEmployee] = useState<any>(null);
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });

  const isAdmin = user?.role?.toLowerCase() === 'admin' || user?.role?.toLowerCase() === 'manager';

  const loadHistory = useCallback(async () => {
    try {
      const res = await timeclockAPI.myHistory(month);
      setHistory(res.data);
    } catch (e) {
      console.error('Failed to load history:', e);
    }
  }, [month]);

  const loadAdminSummary = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const res = await timeclockAPI.adminSummary(month);
      setAdminSummary(res.data);
    } catch (e) {
      console.error('Failed to load admin summary:', e);
    }
  }, [isAdmin, month]);

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) {
      loadHistory();
      if (isAdmin) loadAdminSummary();
    }
  }, [user, loading, month]);

  const handleExcuse = async (entryId: number) => {
    const note = prompt('Reason for excusing this late entry (optional):');
    try {
      await timeclockAPI.excuse(entryId, note || undefined);
      await loadHistory();
      if (isAdmin) await loadAdminSummary();
      if (selectedEmployee) {
        const res = await timeclockAPI.adminEmployeeDetail(selectedEmployee.user_id, month);
        setSelectedEmployee(res.data);
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to excuse');
    }
  };

  const handleUnexcuse = async (entryId: number) => {
    try {
      await timeclockAPI.unexcuse(entryId);
      await loadHistory();
      if (isAdmin) await loadAdminSummary();
      if (selectedEmployee) {
        const res = await timeclockAPI.adminEmployeeDetail(selectedEmployee.user_id, month);
        setSelectedEmployee(res.data);
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed');
    }
  };

  const loadEmployeeDetail = async (userId: number) => {
    try {
      const res = await timeclockAPI.adminEmployeeDetail(userId, month);
      setSelectedEmployee(res.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to load');
    }
  };

  const formatTime = (iso: string) => {
    if (!iso) return '—';
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  };

  if (loading || !user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">
            Attendance
          </h1>
          <p className="text-slate-600">
            Your attendance history and commission impact — clock in/out from the <a href="/dashboard" className="text-blue-600 hover:underline font-semibold">Dashboard</a>
          </p>
        </div>

        {/* Month Selector */}
        <div className="flex items-center space-x-3 mb-6">
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* My Attendance Summary */}
        {history?.summary && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <h3 className="font-display text-lg font-bold text-slate-900 mb-4">My Attendance</h3>
            <AttendanceSummaryRow summary={history.summary} />
          </div>
        )}

        {/* My History */}
        {history?.entries && history.entries.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <h3 className="font-display text-lg font-bold text-slate-900 mb-4">My Clock History</h3>
            <EntryTable entries={history.entries} isAdmin={isAdmin} onExcuse={handleExcuse} onUnexcuse={handleUnexcuse} />
          </div>
        )}

        {/* Admin: Team Attendance */}
        {isAdmin && adminSummary && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <div className="flex items-center space-x-2 mb-4">
              <Users size={20} className="text-slate-400" />
              <h3 className="font-display text-lg font-bold text-slate-900">Team Attendance — {month}</h3>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left">
                    <th className="py-2 pr-4 font-semibold text-slate-600">Employee</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Days</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">On Time</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Late</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Excused</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Unexcused</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Hours</th>
                    <th className="py-2 px-3 font-semibold text-slate-600 text-center">Commission Impact</th>
                    <th className="py-2 px-1"></th>
                  </tr>
                </thead>
                <tbody>
                  {adminSummary.employees.map((emp: any) => (
                    <tr key={emp.user_id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-2.5 pr-4 font-medium text-slate-900">{emp.name}</td>
                      <td className="py-2.5 px-3 text-center text-slate-700">{emp.total_days}</td>
                      <td className="py-2.5 px-3 text-center text-green-600 font-semibold">{emp.on_time_days}</td>
                      <td className="py-2.5 px-3 text-center text-slate-700">{emp.late_days}</td>
                      <td className="py-2.5 px-3 text-center text-blue-600">{emp.excused_days}</td>
                      <td className="py-2.5 px-3 text-center font-bold">
                        <span className={
                          emp.late_days_unexcused >= 4 ? 'text-red-600' :
                          emp.late_days_unexcused >= 2 ? 'text-amber-600' :
                          'text-green-600'
                        }>
                          {emp.late_days_unexcused}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-center text-slate-700">{emp.total_hours}h</td>
                      <td className="py-2.5 px-3 text-center">
                        <ImpactBadge label={emp.impact_label} text={emp.commission_impact} />
                      </td>
                      <td className="py-2.5 px-1">
                        <button
                          onClick={() => loadEmployeeDetail(emp.user_id)}
                          className="text-blue-600 hover:text-blue-800 text-xs font-semibold"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Admin: Employee Detail */}
        {isAdmin && selectedEmployee && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-lg font-bold text-slate-900">
                {selectedEmployee.name} — {selectedEmployee.period}
              </h3>
              <button
                onClick={() => setSelectedEmployee(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <XCircle size={20} />
              </button>
            </div>
            <AttendanceSummaryRow summary={selectedEmployee.summary} />
            <div className="mt-4">
              <EntryTable
                entries={selectedEmployee.entries}
                isAdmin={true}
                onExcuse={handleExcuse}
                onUnexcuse={handleUnexcuse}
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}


// ── Components ──────────────────────────────────────────────────────

const AttendanceSummaryRow: React.FC<{ summary: any }> = ({ summary }) => (
  <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
    <div className="bg-slate-50 rounded-lg p-3 text-center">
      <p className="text-2xl font-bold text-slate-900">{summary.total_days}</p>
      <p className="text-xs text-slate-500 font-medium">Days Worked</p>
    </div>
    <div className="bg-green-50 rounded-lg p-3 text-center">
      <p className="text-2xl font-bold text-green-700">{summary.on_time_days}</p>
      <p className="text-xs text-green-600 font-medium">On Time</p>
    </div>
    <div className="bg-amber-50 rounded-lg p-3 text-center">
      <p className="text-2xl font-bold text-amber-700">{summary.late_days_unexcused}</p>
      <p className="text-xs text-amber-600 font-medium">Late (Unexcused)</p>
    </div>
    <div className="bg-slate-50 rounded-lg p-3 text-center">
      <p className="text-2xl font-bold text-slate-700">{summary.total_hours}h</p>
      <p className="text-xs text-slate-500 font-medium">Total Hours</p>
    </div>
    <div className={`rounded-lg p-3 text-center ${
      summary.impact_label === 'bonus' ? 'bg-green-50' :
      summary.impact_label === 'penalty' ? 'bg-red-50' :
      'bg-slate-50'
    }`}>
      <ImpactBadge label={summary.impact_label} text={summary.commission_impact} size="lg" />
      <p className="text-xs text-slate-500 font-medium mt-1">Commission Impact</p>
    </div>
  </div>
);

const ImpactBadge: React.FC<{ label: string; text: string; size?: string }> = ({ label, text, size }) => {
  const isLg = size === 'lg';
  if (label === 'bonus') {
    return (
      <span className={`inline-flex items-center space-x-1 ${isLg ? 'text-xl font-bold' : 'text-xs font-semibold'} text-green-700`}>
        <TrendingUp size={isLg ? 20 : 14} />
        <span>{text}</span>
      </span>
    );
  }
  if (label === 'penalty') {
    return (
      <span className={`inline-flex items-center space-x-1 ${isLg ? 'text-xl font-bold' : 'text-xs font-semibold'} text-red-600`}>
        <TrendingDown size={isLg ? 20 : 14} />
        <span>{text}</span>
      </span>
    );
  }
  return (
    <span className={`inline-flex items-center space-x-1 ${isLg ? 'text-xl font-bold' : 'text-xs font-semibold'} text-slate-500`}>
      <Minus size={isLg ? 20 : 14} />
      <span>{text}</span>
    </span>
  );
};

const EntryTable: React.FC<{
  entries: any[];
  isAdmin: boolean;
  onExcuse: (id: number) => void;
  onUnexcuse: (id: number) => void;
}> = ({ entries, isAdmin, onExcuse, onUnexcuse }) => {
  const formatTime = (iso: string) => {
    if (!iso) return '—';
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left">
            <th className="py-2 pr-4 font-semibold text-slate-600">Date</th>
            <th className="py-2 px-3 font-semibold text-slate-600">Clock In</th>
            <th className="py-2 px-3 font-semibold text-slate-600">Clock Out</th>
            <th className="py-2 px-3 font-semibold text-slate-600 text-center">Hours</th>
            <th className="py-2 px-3 font-semibold text-slate-600 text-center">Location</th>
            <th className="py-2 px-3 font-semibold text-slate-600 text-center">Status</th>
            {isAdmin && <th className="py-2 px-3 font-semibold text-slate-600 text-center">Action</th>}
          </tr>
        </thead>
        <tbody>
          {entries.map((e: any) => (
            <tr key={e.id} className={`border-b border-slate-100 ${
              e.is_late && !e.excused ? 'bg-red-50/50' : ''
            }`}>
              <td className="py-2.5 pr-4 font-medium text-slate-900">{formatDate(e.work_date)}</td>
              <td className="py-2.5 px-3 text-slate-700">{formatTime(e.clock_in)}</td>
              <td className="py-2.5 px-3 text-slate-700">{e.clock_out ? formatTime(e.clock_out) : '—'}</td>
              <td className="py-2.5 px-3 text-center text-slate-700">
                {e.hours_worked != null ? `${e.hours_worked}h` : '—'}
              </td>
              <td className="py-2.5 px-3 text-center">
                {e.is_at_office === true ? (
                  <span className="inline-flex items-center space-x-1 text-green-600 text-xs font-semibold">
                    <MapPin size={13} />
                    <span>At Office</span>
                  </span>
                ) : e.is_at_office === false ? (
                  <span className="inline-flex items-center space-x-1 text-amber-600 text-xs font-semibold">
                    <MapPin size={13} />
                    <span>Remote</span>
                  </span>
                ) : (
                  <span className="text-slate-400 text-xs">—</span>
                )}
              </td>
              <td className="py-2.5 px-3 text-center">
                {!e.is_late ? (
                  <span className="inline-flex items-center space-x-1 text-green-600 text-xs font-semibold">
                    <CheckCircle size={14} />
                    <span>On Time</span>
                  </span>
                ) : e.excused ? (
                  <span className="inline-flex items-center space-x-1 text-blue-600 text-xs font-semibold">
                    <Shield size={14} />
                    <span>Excused</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center space-x-1 text-red-600 text-xs font-semibold">
                    <AlertTriangle size={14} />
                    <span>{e.minutes_late}m late</span>
                  </span>
                )}
              </td>
              {isAdmin && (
                <td className="py-2.5 px-3 text-center">
                  {e.is_late && !e.excused && (
                    <button
                      onClick={() => onExcuse(e.id)}
                      className="text-blue-600 hover:text-blue-800 text-xs font-semibold"
                    >
                      Excuse
                    </button>
                  )}
                  {e.is_late && e.excused && (
                    <button
                      onClick={() => onUnexcuse(e.id)}
                      className="text-slate-400 hover:text-red-500 text-xs font-semibold"
                    >
                      Unexcuse
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
