import React, { useEffect, useState } from 'react';
import { analyticsAPI } from '../lib/api';
import { TrendingUp, Target, Calendar, ChevronDown, ChevronUp } from 'lucide-react';

interface TrendingData {
  mode: string;
  current_premium: number;
  ytd_premium: number;
  projected_premium: number;
  daily_pace: number;
  biz_days_elapsed: number;
  biz_days_remaining: number;
  total_biz_days: number;
  target_date: string;
  current_tier: { level: number; rate: number; description: string } | null;
  goals: {
    label: string;
    target: number;
    remaining: number;
    daily_needed: number;
    on_pace: boolean;
    progress: number;
  }[];
  period: string;
  total_sales?: number;
  monthly_breakdown?: { month: number; premium: number }[];
  year?: number;
}

interface Props {
  compact?: boolean;
  period?: string;
  showTrending?: boolean;
  showGoals?: boolean;
}

const TrendingGoals: React.FC<Props> = ({ compact = false, period: externalPeriod, showTrending = true, showGoals = true }) => {
  const [data, setData] = useState<TrendingData | null>(null);
  const [targetDate, setTargetDate] = useState('');
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [loading, setLoading] = useState(true);

  const effectivePeriod = externalPeriod || 'monthly';

  const loadData = async (customDate?: string) => {
    setLoading(true);
    try {
      const params: any = { period: effectivePeriod === 'all-time' ? 'annual' : effectivePeriod };
      if (customDate) params.target_date = customDate;
      const res = await analyticsAPI.trending(params);
      setData(res.data);
      if (!customDate) setTargetDate(res.data.target_date);
    } catch (e) {
      console.error('Failed to load trending data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setTargetDate('');
    loadData();
  }, [effectivePeriod]);

  const handleDateChange = (newDate: string) => {
    setTargetDate(newDate);
    loadData(newDate);
  };

  const fmt = (val: number) =>
    `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  if (loading || !data) {
    return (
      <div className="card animate-pulse">
        <div className="h-6 bg-slate-200 rounded w-48 mb-4" />
        <div className="h-20 bg-slate-100 rounded" />
      </div>
    );
  }

  const isLastYear = data.mode === 'last_year';

  const targetLabel = (() => {
    if (isLastYear) return `${data.year} Full Year`;
    const d = new Date(targetDate + 'T00:00:00');
    const now = new Date();
    if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) return 'End of Month';
    if (d.getMonth() === 11 && d.getDate() === 31) return 'End of Year';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  })();

  const periodLabel = effectivePeriod === 'annual' ? 'Year-to-Date' : effectivePeriod === 'last_year' ? `Last Year (${data.year})` : 'This Month';

  // Quick date buttons
  const now = new Date();
  const endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const endOfQ = new Date(now.getFullYear(), Math.ceil((now.getMonth() + 1) / 3) * 3, 0);
  const endOfYear = new Date(now.getFullYear(), 11, 31);

  const quickDates = [
    { label: 'End of Month', date: endOfMonth.toISOString().slice(0, 10) },
    { label: 'End of Quarter', date: endOfQ.toISOString().slice(0, 10) },
    { label: 'End of Year', date: endOfYear.toISOString().slice(0, 10) },
  ];

  return (
    <div className="space-y-6">
      {/* Trending Projection Card */}
      {showTrending && (
      <div className="card border-2 border-brand-100">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display text-xl font-bold text-slate-900 flex items-center gap-2">
            <TrendingUp className="text-brand-600" size={22} />
            {isLastYear ? `${data.year} Production` : 'Trending Data'}
          </h3>
          {!isLastYear && (
            <button
              onClick={() => setShowDatePicker(!showDatePicker)}
              className="flex items-center gap-1 text-sm font-medium text-brand-600 hover:text-brand-700 transition-colors"
            >
              <Calendar size={16} />
              {targetLabel}
              {showDatePicker ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
        </div>

        {/* Date Picker */}
        {showDatePicker && !isLastYear && (
          <div className="mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
            <div className="flex items-center gap-2 flex-wrap mb-2">
              {quickDates.map((qd) => (
                <button
                  key={qd.label}
                  onClick={() => { handleDateChange(qd.date); setShowDatePicker(false); }}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${
                    targetDate === qd.date
                      ? 'bg-brand-600 text-white'
                      : 'bg-white border border-slate-200 text-slate-600 hover:border-brand-300'
                  }`}
                >
                  {qd.label}
                </button>
              ))}
            </div>
            <input
              type="date"
              value={targetDate}
              min={new Date().toISOString().slice(0, 10)}
              max={`${now.getFullYear()}-12-31`}
              onChange={(e) => { handleDateChange(e.target.value); setShowDatePicker(false); }}
              className="px-3 py-1.5 rounded-lg text-sm border border-slate-200 bg-white text-slate-700 focus:border-brand-400 outline-none"
            />
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div className="p-3 bg-slate-50 rounded-lg">
            <div className="text-xs text-slate-500 font-medium mb-1">{periodLabel} Premium</div>
            <div className="text-xl font-bold text-slate-900">{fmt(data.current_premium)}</div>
          </div>
          {isLastYear ? (
            <div className="p-3 bg-slate-50 rounded-lg">
              <div className="text-xs text-slate-500 font-medium mb-1">Total Sales</div>
              <div className="text-xl font-bold text-slate-900">{data.total_sales || 0}</div>
            </div>
          ) : (
            <div className="p-3 bg-brand-50 rounded-lg border border-brand-100">
              <div className="text-xs text-brand-600 font-medium mb-1">Projected by {targetLabel}</div>
              <div className="text-xl font-bold text-brand-700">{fmt(data.projected_premium)}</div>
            </div>
          )}
        </div>

        {!isLastYear && (
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-lg font-bold text-slate-900">{fmt(data.daily_pace)}</div>
              <div className="text-xs text-slate-500">Daily Pace</div>
            </div>
            <div>
              <div className="text-lg font-bold text-slate-900">{data.biz_days_elapsed}</div>
              <div className="text-xs text-slate-500">Biz Days In</div>
            </div>
            <div>
              <div className="text-lg font-bold text-slate-900">{data.biz_days_remaining}</div>
              <div className="text-xs text-slate-500">Biz Days Left</div>
            </div>
          </div>
        )}

        {/* Last year monthly breakdown */}
        {isLastYear && data.monthly_breakdown && !compact && (
          <div className="mt-4 pt-3 border-t border-slate-100">
            <div className="text-xs font-semibold text-slate-500 mb-2">Monthly Breakdown</div>
            <div className="grid grid-cols-4 gap-2">
              {data.monthly_breakdown.map((m) => (
                <div key={m.month} className="text-center p-2 bg-slate-50 rounded">
                  <div className="text-xs text-slate-400">{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m.month - 1]}</div>
                  <div className="text-sm font-bold text-slate-700">{fmt(m.premium)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!compact && !isLastYear && data.ytd_premium > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-100">
            <div className="text-sm text-slate-600">
              Year-to-Date Premium: <span className="font-bold text-slate-900">{fmt(data.ytd_premium)}</span>
            </div>
          </div>
        )}
      </div>
      )}

      {/* Goals Card — hide for last year */}
      {showGoals && !isLastYear && data.goals.length > 0 && (
        <div className="card border-2 border-amber-100">
          <h3 className="font-display text-xl font-bold text-slate-900 flex items-center gap-2 mb-4">
            <Target className="text-amber-500" size={22} />
            Goals & Milestones
          </h3>
          <div className="space-y-4">
            {data.goals.map((goal, i) => (
              <GoalItem key={i} goal={goal} currentPremium={data.current_premium} dailyPace={data.daily_pace} bizDaysRemaining={data.biz_days_remaining} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const GoalItem: React.FC<{
  goal: any;
  currentPremium: number;
  dailyPace: number;
  bizDaysRemaining: number;
}> = ({ goal, currentPremium, dailyPace, bizDaysRemaining }) => {
  const fmt = (val: number) =>
    `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  const progressPct = Math.min(100, goal.progress);
  const isComplete = currentPremium >= goal.target;

  return (
    <div className={`p-4 rounded-lg border ${isComplete ? 'bg-green-50 border-green-200' : goal.on_pace ? 'bg-blue-50 border-blue-200' : 'bg-slate-50 border-slate-200'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold text-slate-900">{goal.label}</span>
        {isComplete ? (
          <span className="text-xs font-bold text-green-600 bg-green-100 px-2 py-0.5 rounded-full">✓ REACHED</span>
        ) : goal.on_pace ? (
          <span className="text-xs font-bold text-blue-600 bg-blue-100 px-2 py-0.5 rounded-full">ON PACE</span>
        ) : (
          <span className="text-xs font-bold text-amber-600 bg-amber-100 px-2 py-0.5 rounded-full">PUSH NEEDED</span>
        )}
      </div>

      <div className="w-full bg-slate-200 rounded-full h-2.5 mb-2">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${
            isComplete ? 'bg-green-500' : goal.on_pace ? 'bg-blue-500' : 'bg-amber-500'
          }`}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs text-slate-600">
        <span>{fmt(currentPremium)} / {fmt(goal.target)}</span>
        {!isComplete && <span>{fmt(goal.remaining)} remaining</span>}
      </div>

      {!isComplete && goal.daily_needed > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          Need <span className="font-semibold text-slate-700">{fmt(goal.daily_needed)}/day</span> over {bizDaysRemaining} business days
          {dailyPace > 0 && <span> (current pace: {fmt(dailyPace)}/day)</span>}
        </div>
      )}
    </div>
  );
};

export default TrendingGoals;
