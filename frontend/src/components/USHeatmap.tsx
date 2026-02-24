import React, { useEffect, useState, useRef } from 'react';
import { customersAPI } from '../lib/api';
import { STATE_PATHS, STATE_CENTROIDS, STATE_NAMES } from '../data/us-states';

// Small states that need external labels with leader lines
const SMALL_STATES = new Set(['CT', 'DE', 'DC', 'MA', 'MD', 'NH', 'NJ', 'RI', 'VT']);

export default function USHeatmap() {
  const [stateData, setStateData] = useState<Record<string, number>>({});
  const [hoveredState, setHoveredState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; show: boolean }>({ x: 0, y: 0, show: false });

  useEffect(() => {
    customersAPI.stateDistribution()
      .then(r => setStateData(r.data || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const maxCount = Math.max(1, ...Object.values(stateData));

  // Color scale: dark navy (0) → deep blue → sky blue → cyan (max)
  const getColor = (count: number): string => {
    if (!count) return '#0f1729';
    const pct = count / maxCount;
    // Interpolate through color stops
    if (pct > 0.6) return `rgb(14, ${Math.round(145 + pct * 60)}, ${Math.round(200 + pct * 55)})`;
    if (pct > 0.3) return `rgb(3, ${Math.round(80 + pct * 120)}, ${Math.round(160 + pct * 40)})`;
    if (pct > 0.08) return `rgb(7, ${Math.round(50 + pct * 100)}, ${Math.round(100 + pct * 60)})`;
    return '#0c3550';
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    setTooltip({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      show: true,
    });
  };

  const totalCustomers = Object.values(stateData).reduce((a, b) => a + b, 0);
  const stateCount = Object.keys(stateData).filter(k => stateData[k] > 0).length;
  const topStates = Object.entries(stateData).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const hoveredCount = hoveredState ? (stateData[hoveredState] || 0) : 0;
  const hoveredPct = hoveredState ? ((hoveredCount / totalCustomers) * 100).toFixed(1) : '0';

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-cyan-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mt-2">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-lg font-bold text-slate-200">Customer Footprint</h3>
          <p className="text-sm text-slate-400">
            {totalCustomers.toLocaleString()} customers · {stateCount} states
          </p>
        </div>
        {/* Color legend */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-medium">FEWER</span>
          <div className="flex h-2 rounded-full overflow-hidden" style={{ width: 80 }}>
            {[0.05, 0.15, 0.3, 0.5, 0.75, 1].map((pct, i) => (
              <div key={i} className="flex-1" style={{ backgroundColor: getColor(maxCount * pct) }} />
            ))}
          </div>
          <span className="text-[10px] text-slate-500 font-medium">MORE</span>
        </div>
      </div>

      {/* Map container */}
      <div
        className="relative rounded-2xl border border-slate-700/40 overflow-hidden"
        style={{ background: 'linear-gradient(160deg, #080e1a 0%, #111827 50%, #0c1322 100%)' }}
      >
        <svg
          ref={svgRef}
          viewBox="0 0 980 640"
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => { setHoveredState(null); setTooltip(t => ({ ...t, show: false })); }}
        >
          {/* Subtle radial glow in center */}
          <defs>
            <radialGradient id="mapGlow" cx="50%" cy="45%" r="50%">
              <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.03" />
              <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0" />
            </radialGradient>
            <filter id="stateGlow">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>
          <rect x="0" y="0" width="980" height="640" fill="url(#mapGlow)" />

          {/* State shapes */}
          {Object.entries(STATE_PATHS).map(([abbr, pathD]) => {
            const count = stateData[abbr] || 0;
            const isHovered = hoveredState === abbr;
            const fill = getColor(count);

            return (
              <g key={abbr}>
                {/* Glow behind hovered state */}
                {isHovered && count > 0 && (
                  <path d={pathD} fill="#0ea5e9" opacity={0.3} filter="url(#stateGlow)" />
                )}
                <path
                  d={pathD}
                  fill={fill}
                  stroke={isHovered ? '#38bdf8' : count > 0 ? '#1e3a5f' : '#1a2744'}
                  strokeWidth={isHovered ? 1.8 : 0.5}
                  opacity={isHovered ? 1 : count ? 0.92 : 0.35}
                  onMouseEnter={() => setHoveredState(abbr)}
                  style={{ cursor: 'pointer', transition: 'opacity 0.15s, stroke-width 0.1s' }}
                />
              </g>
            );
          })}

          {/* State labels (skip small states on the map) */}
          {Object.entries(STATE_CENTROIDS).map(([abbr, [cx, cy]]) => {
            if (SMALL_STATES.has(abbr)) return null;
            const count = stateData[abbr] || 0;
            const isHovered = hoveredState === abbr;
            return (
              <text
                key={abbr}
                x={cx} y={cy}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={isHovered ? '#fff' : count ? '#cbd5e1' : '#334155'}
                fontSize={10}
                fontWeight={isHovered ? 700 : 500}
                fontFamily="system-ui, -apple-system, sans-serif"
                style={{ pointerEvents: 'none' }}
              >
                {abbr}
              </text>
            );
          })}
        </svg>

        {/* Floating tooltip */}
        {hoveredState && tooltip.show && (
          <div
            className="absolute z-20 pointer-events-none"
            style={{
              left: tooltip.x,
              top: tooltip.y - 16,
              transform: 'translate(-50%, -100%)',
            }}
          >
            <div className="bg-slate-900/95 backdrop-blur border border-slate-600/50 rounded-lg px-3.5 py-2 shadow-2xl shadow-black/50">
              <p className="text-white font-bold text-[13px]">{STATE_NAMES[hoveredState] || hoveredState}</p>
              <div className="flex items-baseline gap-1.5 mt-0.5">
                <span className="text-cyan-400 font-bold text-lg leading-none">
                  {hoveredCount.toLocaleString()}
                </span>
                <span className="text-slate-400 text-[11px]">customers</span>
                {hoveredCount > 0 && (
                  <span className="text-slate-500 text-[10px] ml-1">({hoveredPct}%)</span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Top states grid */}
      <div className="mt-3 grid grid-cols-4 gap-2">
        {topStates.map(([abbr, count]) => {
          const pct = ((count / totalCustomers) * 100).toFixed(1);
          return (
            <div
              key={abbr}
              className={`rounded-xl px-3 py-2 transition-all cursor-default border ${
                hoveredState === abbr
                  ? 'bg-cyan-500/15 border-cyan-500/40'
                  : 'bg-slate-800/40 border-slate-700/30 hover:bg-slate-800/60'
              }`}
              onMouseEnter={() => setHoveredState(abbr)}
              onMouseLeave={() => setHoveredState(null)}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] font-bold text-slate-300">{STATE_NAMES[abbr] || abbr}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-sm font-bold text-cyan-400">{count.toLocaleString()}</span>
                <span className="text-[10px] text-slate-500">{pct}%</span>
              </div>
              <div className="mt-1.5 h-1 rounded-full bg-slate-700/60 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${(count / topStates[0][1]) * 100}%`,
                    background: 'linear-gradient(90deg, #0369a1, #0ea5e9)',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
