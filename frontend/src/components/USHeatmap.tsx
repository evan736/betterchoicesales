import React, { useEffect, useState, useRef } from 'react';
import { customersAPI } from '../lib/api';
import { STATE_PATHS, STATE_CENTROIDS, STATE_NAMES } from '../data/us-states';
import { useTheme } from '../contexts/ThemeContext';

// Small states that need external labels with leader lines
const SMALL_STATES = new Set(['CT', 'DE', 'DC', 'MA', 'MD', 'NH', 'NJ', 'RI', 'VT']);

export default function USHeatmap() {
  const { theme } = useTheme();
  const [stateData, setStateData] = useState<Record<string, number>>({});
  const [hoveredState, setHoveredState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; show: boolean }>({ x: 0, y: 0, show: false });

  const isDark = theme === 'mission-control' || theme === 'true-black';

  useEffect(() => {
    customersAPI.stateDistribution()
      .then(r => setStateData(r.data || {}))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const maxCount = Math.max(1, ...Object.values(stateData));

  // Color scale: adapts to theme
  const getColor = (count: number): string => {
    if (!count) {
      if (theme === 'sakura-pink') return '#fdf2f8';
      if (theme === 'apple-clean') return '#e5e7eb';
      if (theme === 'blue-white') return '#dbeafe';
      if (theme === 'true-black') return '#1c1c20';
      return '#0f1729'; // mission-control
    }
    const pct = count / maxCount;
    if (theme === 'sakura-pink') {
      if (pct > 0.6) return `rgb(${Math.round(236 - pct * 30)}, ${Math.round(72 + pct * 20)}, ${Math.round(153 + pct * 30)})`;
      if (pct > 0.3) return `rgb(${Math.round(244 - pct * 40)}, ${Math.round(114 + pct * 40)}, ${Math.round(182 - pct * 20)})`;
      if (pct > 0.08) return `rgb(${Math.round(251 - pct * 30)}, ${Math.round(168 + pct * 40)}, ${Math.round(211 - pct * 20)})`;
      return '#f9a8d4';
    }
    if (theme === 'apple-clean') {
      if (pct > 0.6) return `rgb(${Math.round(0 + pct * 10)}, ${Math.round(90 + pct * 30)}, ${Math.round(200 + pct * 27)})`;
      if (pct > 0.3) return `rgb(${Math.round(59 + pct * 30)}, ${Math.round(130 + pct * 40)}, ${Math.round(246 - pct * 10)})`;
      if (pct > 0.08) return `rgb(${Math.round(96 + pct * 50)}, ${Math.round(165 + pct * 30)}, ${Math.round(250 - pct * 5)})`;
      return '#93c5fd';
    }
    if (theme === 'blue-white') {
      if (pct > 0.6) return `rgb(${Math.round(30 - pct * 10)}, ${Math.round(64 + pct * 30)}, ${Math.round(175 + pct * 40)})`;
      if (pct > 0.3) return `rgb(${Math.round(59 + pct * 20)}, ${Math.round(130 + pct * 30)}, ${Math.round(246 - pct * 10)})`;
      if (pct > 0.08) return `rgb(${Math.round(96 + pct * 40)}, ${Math.round(165 + pct * 20)}, ${Math.round(250 - pct * 5)})`;
      return '#93c5fd';
    }
    if (theme === 'true-black') {
      if (pct > 0.6) return `rgb(${Math.round(pct * 30)}, ${Math.round(160 + pct * 50)}, ${Math.round(210 + pct * 45)})`;
      if (pct > 0.3) return `rgb(${Math.round(pct * 15)}, ${Math.round(90 + pct * 110)}, ${Math.round(170 + pct * 35)})`;
      if (pct > 0.08) return `rgb(${Math.round(pct * 10)}, ${Math.round(60 + pct * 90)}, ${Math.round(110 + pct * 50)})`;
      return '#1a3a4a';
    }
    // mission-control (default)
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
          <h3 className={`text-lg font-bold ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>Customer Footprint</h3>
          <p className={`text-sm ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
            {totalCustomers.toLocaleString()} customers · {stateCount} states
          </p>
        </div>
        {/* Color legend */}
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-medium ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>FEWER</span>
          <div className="flex h-2 rounded-full overflow-hidden" style={{ width: 80 }}>
            {[0.05, 0.15, 0.3, 0.5, 0.75, 1].map((pct, i) => (
              <div key={i} className="flex-1" style={{ backgroundColor: getColor(maxCount * pct) }} />
            ))}
          </div>
          <span className={`text-[10px] font-medium ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>MORE</span>
        </div>
      </div>

      {/* Map container */}
      <div
        className="relative rounded-2xl border border-slate-700/40 overflow-hidden map-container"
        style={{ background: 'var(--map-bg, linear-gradient(160deg, #080e1a 0%, #111827 50%, #0c1322 100%))' }}
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
            {/* Glow filters at different intensities */}
            <filter id="glow1" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glow2" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glow3" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="8" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glowMax" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="12" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>
          <rect x="0" y="0" width="980" height="640" fill="url(#mapGlow)" />

          {/* State shapes */}
          {Object.entries(STATE_PATHS).map(([abbr, pathD]) => {
            const count = stateData[abbr] || 0;
            const isHovered = hoveredState === abbr;
            const fill = getColor(count);
            const pct = count / maxCount;

            // Theme-aware glow/stroke colors
            const glowFilter = pct > 0.5 ? 'url(#glowMax)' : pct > 0.2 ? 'url(#glow3)' : pct > 0.08 ? 'url(#glow2)' : pct > 0 ? 'url(#glow1)' : undefined;
            const glowOpacity = isDark
              ? (isHovered ? Math.min(pct * 0.8 + 0.3, 0.7) : Math.min(pct * 0.5 + 0.05, 0.45))
              : (isHovered ? Math.min(pct * 0.3 + 0.1, 0.25) : Math.min(pct * 0.15 + 0.02, 0.15));

            const accentColor = theme === 'sakura-pink' ? '#ec4899'
              : theme === 'apple-clean' ? '#0071e3'
              : theme === 'blue-white' ? '#1e40af'
              : theme === 'true-black' ? '#22d3ee'
              : '#22d3ee';

            const glowColor = pct > 0.5 ? accentColor
              : pct > 0.2 ? (isDark ? '#0ea5e9' : accentColor)
              : (isDark ? '#0284c7' : accentColor);

            const strokeHover = theme === 'sakura-pink' ? '#ec4899'
              : theme === 'apple-clean' ? '#0071e3'
              : theme === 'blue-white' ? '#1e40af'
              : theme === 'true-black' ? '#67e8f9'
              : '#67e8f9';

            const strokeNormal = isDark
              ? (count > 0 ? '#1e3a5f' : '#1a2744')
              : (count > 0 ? 'rgba(0,0,0,0.12)' : 'rgba(0,0,0,0.06)');

            return (
              <g key={abbr}>
                {/* Always-on glow behind states with customers */}
                {count > 0 && isDark && (
                  <path d={pathD} fill={glowColor} opacity={glowOpacity} filter={glowFilter} />
                )}
                {/* Extra bright glow on hover (dark themes only) */}
                {isHovered && count > 0 && isDark && (
                  <path d={pathD} fill={accentColor} opacity={0.35} filter="url(#glow3)" />
                )}
                <path
                  d={pathD}
                  fill={fill}
                  stroke={isHovered ? strokeHover : strokeNormal}
                  strokeWidth={isHovered ? 2 : 0.5}
                  opacity={isHovered ? 1 : count ? 0.95 : (isDark ? 0.3 : 0.6)}
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
                fill={isHovered ? (isDark ? '#fff' : '#000') : count ? (isDark ? '#cbd5e1' : '#374151') : (isDark ? '#334155' : '#9ca3af')}
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
                  ? (isDark ? 'bg-cyan-500/15 border-cyan-500/40' : (
                    theme === 'sakura-pink' ? 'bg-pink-100 border-pink-300' :
                    theme === 'apple-clean' ? 'bg-blue-50 border-blue-300' :
                    'bg-blue-100 border-blue-300'
                  ))
                  : (isDark ? 'bg-slate-800/40 border-slate-700/30 hover:bg-slate-800/60' : (
                    theme === 'sakura-pink' ? 'bg-pink-50/60 border-pink-200/40 hover:bg-pink-50' :
                    theme === 'apple-clean' ? 'bg-gray-50 border-gray-200 hover:bg-gray-100' :
                    'bg-blue-50/60 border-blue-200/40 hover:bg-blue-50'
                  ))
              }`}
              onMouseEnter={() => setHoveredState(abbr)}
              onMouseLeave={() => setHoveredState(null)}
            >
              <div className="flex items-center justify-between mb-1">
                <span className={`text-[11px] font-bold ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{STATE_NAMES[abbr] || abbr}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className={`text-sm font-bold ${
                  theme === 'sakura-pink' ? 'text-pink-500' :
                  theme === 'apple-clean' ? 'text-blue-600' :
                  theme === 'blue-white' ? 'text-blue-700' :
                  'text-cyan-400'
                }`}>{count.toLocaleString()}</span>
                <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{pct}%</span>
              </div>
              <div className={`mt-1.5 h-1 rounded-full overflow-hidden ${isDark ? 'bg-slate-700/60' : 'bg-slate-200'}`}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${(count / topStates[0][1]) * 100}%`,
                    background: theme === 'sakura-pink' ? 'linear-gradient(90deg, #ec4899, #f472b6)'
                      : theme === 'apple-clean' ? 'linear-gradient(90deg, #0071e3, #5ac8fa)'
                      : theme === 'blue-white' ? 'linear-gradient(90deg, #1e40af, #3b82f6)'
                      : theme === 'true-black' ? 'linear-gradient(90deg, #0e7490, #22d3ee)'
                      : 'linear-gradient(90deg, #0369a1, #0ea5e9)',
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
