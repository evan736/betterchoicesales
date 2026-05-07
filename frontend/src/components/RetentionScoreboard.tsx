/**
 * Retention Scoreboard — leaderboard at the top of the reshop pipeline.
 *
 * Renders one row per retention specialist with month-to-date metrics:
 * active pipeline, won / lost / win rate, past-due count, and rewritten
 * premium $.
 *
 * The current user's row is highlighted in cyan/branded styling — they
 * see how they compare to their peers, which is the core ask.
 *
 * Default sort is rewritten premium $ descending (the actual business
 * outcome) but the user can switch sort via the dropdown.
 *
 * Collapsible — the header bar always shows the user's own headline
 * stats; clicking expands the full leaderboard.
 */
import React, { useEffect, useState } from 'react';
import { reshopAPI } from '../lib/api';
import {
  Trophy, ChevronDown, ChevronUp, TrendingUp, AlertCircle,
  CheckCircle2, XCircle, DollarSign, Activity,
} from 'lucide-react';

type SortKey = 'rewritten_premium_mtd' | 'won' | 'win_rate' | 'active';

interface ScoreboardRow {
  user_id: number;
  name: string;
  username: string;
  active: number;
  won_mtd: number;
  lost_mtd: number;
  win_rate: number;
  past_due: number;
  rewritten_premium_mtd: number;
  premium_savings_mtd: number;
  is_me: boolean;
  rank: number;
}

interface ScoreboardData {
  as_of: string;
  month_start: string;
  sort_by: string;
  totals: {
    active: number;
    won_mtd: number;
    lost_mtd: number;
    rewritten_premium_mtd: number;
    past_due: number;
  };
  rows: ScoreboardRow[];
}

const formatMoney = (n: number) =>
  '$' + Math.round(n).toLocaleString();

// Win rate -> color. >=50 green, 30-49 amber, <30 red. Zero attempts
// (no wins or losses) renders neutral grey rather than red, since
// 0/0 isn't actually a bad performance — it's no data.
const winRateColor = (rate: number, won: number, lost: number) => {
  if (won + lost === 0) return 'text-slate-400';
  if (rate >= 50) return 'text-emerald-700';
  if (rate >= 30) return 'text-amber-700';
  return 'text-red-700';
};

export const RetentionScoreboard: React.FC = () => {
  const [data, setData] = useState<ScoreboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [sortBy, setSortBy] = useState<SortKey>('rewritten_premium_mtd');

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortBy]);

  const load = async () => {
    try {
      const res = await reshopAPI.scoreboard(sortBy);
      setData(res.data);
    } catch (err) {
      // Non-fatal; scoreboard hides itself if not loadable
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 mb-4 animate-pulse">
        <div className="h-5 bg-slate-100 rounded w-1/3 mb-2"></div>
        <div className="h-4 bg-slate-50 rounded w-2/3"></div>
      </div>
    );
  }

  if (!data || data.rows.length === 0) return null;

  const me = data.rows.find((r) => r.is_me);

  return (
    <div className="bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 border border-slate-700 rounded-xl mb-4 overflow-hidden">
      {/* Header / collapsed bar */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-3 flex items-center justify-between hover:bg-slate-800/50 transition"
      >
        <div className="flex items-center gap-3">
          <Trophy size={18} className="text-amber-400" />
          <span className="text-sm font-semibold text-white">Retention Scoreboard</span>
          <span className="text-xs text-slate-400 hidden sm:inline">
            · Month to date
          </span>
        </div>

        {/* Always-visible "your stats" preview when collapsed */}
        {me && !expanded && (
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Rank</span>
              <span className="font-bold text-white">#{me.rank}</span>
              <span className="text-slate-500">of {data.rows.length}</span>
            </div>
            <div className="hidden sm:flex items-center gap-1.5">
              <CheckCircle2 size={12} className="text-emerald-400" />
              <span className="font-semibold text-white">{me.won_mtd}</span>
              <span className="text-slate-400">won</span>
            </div>
            <div className="hidden md:flex items-center gap-1.5">
              <DollarSign size={12} className="text-cyan-400" />
              <span className="font-semibold text-white">{formatMoney(me.rewritten_premium_mtd)}</span>
            </div>
            {me.past_due > 0 && (
              <div className="flex items-center gap-1.5">
                <AlertCircle size={12} className="text-red-400" />
                <span className="font-semibold text-red-300">{me.past_due}</span>
                <span className="text-slate-400 hidden sm:inline">past due</span>
              </div>
            )}
          </div>
        )}

        {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
      </button>

      {/* Expanded leaderboard */}
      {expanded && (
        <div className="border-t border-slate-700/50">
          {/* Sort + agency totals */}
          <div className="px-5 py-2.5 flex items-center justify-between bg-slate-900/50 text-xs">
            <div className="flex items-center gap-3 text-slate-400">
              <span>Agency MTD:</span>
              <span><span className="text-white font-semibold">{data.totals.won_mtd}</span> won</span>
              <span><span className="text-white font-semibold">{data.totals.lost_mtd}</span> lost</span>
              <span><span className="text-cyan-300 font-semibold">{formatMoney(data.totals.rewritten_premium_mtd)}</span> rewritten</span>
              {data.totals.past_due > 0 && (
                <span><span className="text-red-300 font-semibold">{data.totals.past_due}</span> past due</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-500">Sort:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortKey)}
                className="bg-slate-800 text-white text-xs border border-slate-700 rounded px-2 py-1 focus:outline-none focus:border-cyan-500"
              >
                <option value="rewritten_premium_mtd">Rewritten Premium $</option>
                <option value="won">Won (count)</option>
                <option value="win_rate">Win Rate %</option>
                <option value="active">Active Pipeline</option>
              </select>
            </div>
          </div>

          {/* Leaderboard table */}
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 text-slate-400 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-5 py-2 text-left w-12">#</th>
                <th className="px-3 py-2 text-left">Specialist</th>
                <th className="px-3 py-2 text-right">Active</th>
                <th className="px-3 py-2 text-right">Won</th>
                <th className="px-3 py-2 text-right">Lost</th>
                <th className="px-3 py-2 text-right">Win %</th>
                <th className="px-3 py-2 text-right">Past Due</th>
                <th className="px-3 py-2 text-right">Rewritten $</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => {
                const isMe = row.is_me;
                return (
                  <tr
                    key={row.user_id}
                    className={
                      isMe
                        ? 'bg-cyan-900/30 border-l-2 border-cyan-400'
                        : 'border-l-2 border-transparent hover:bg-slate-800/30'
                    }
                  >
                    <td className="px-5 py-2.5 text-left">
                      <span className={`font-bold ${row.rank === 1 ? 'text-amber-400' : isMe ? 'text-cyan-300' : 'text-slate-400'}`}>
                        {row.rank === 1 ? '🥇' : row.rank === 2 ? '🥈' : row.rank === 3 ? '🥉' : `#${row.rank}`}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className={`font-semibold ${isMe ? 'text-cyan-100' : 'text-white'}`}>
                          {row.name}
                        </span>
                        {isMe && (
                          <span className="text-[10px] uppercase tracking-wider bg-cyan-500 text-white px-1.5 py-0.5 rounded font-bold">
                            YOU
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right text-white tabular-nums">{row.active}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className="text-emerald-300 font-semibold">{row.won_mtd}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className="text-slate-400">{row.lost_mtd}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className={`font-semibold ${winRateColor(row.win_rate, row.won_mtd, row.lost_mtd).replace('text-', 'text-').replace('-700', '-300')}`}>
                        {row.won_mtd + row.lost_mtd === 0 ? '—' : `${row.win_rate}%`}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className={row.past_due > 0 ? 'text-red-300 font-semibold' : 'text-slate-500'}>
                        {row.past_due}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className="text-cyan-300 font-semibold">
                        {formatMoney(row.rewritten_premium_mtd)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Footnote */}
          <div className="px-5 py-2 text-[11px] text-slate-500 bg-slate-900/30 border-t border-slate-800/50">
            Won = bound + renewed · Win % = won / (won + lost) · Past due = active reshops past expiration or stale by stage threshold · Rewritten $ = sum of bound_premium for bound reshops this month
          </div>
        </div>
      )}
    </div>
  );
};
