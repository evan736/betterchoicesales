/**
 * StatCard — consistent metric/stat card for dashboards.
 * 
 * Usage:
 *   <StatCard 
 *     label="Total Sales" 
 *     value="$17,449" 
 *     icon={<DollarSign />}
 *     trend={{ value: '+12%', positive: true }}
 *     color="blue"
 *   />
 */

import React from 'react';

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  trend?: { value: string; positive: boolean };
  color?: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'cyan';
  subtitle?: string;
  onClick?: () => void;
}

const colorMap: Record<string, { icon: string; glow: string }> = {
  blue:   { icon: '#3b82f6', glow: 'rgba(59,130,246,0.1)' },
  green:  { icon: '#10b981', glow: 'rgba(16,185,129,0.1)' },
  amber:  { icon: '#f59e0b', glow: 'rgba(245,158,11,0.1)' },
  red:    { icon: '#ef4444', glow: 'rgba(239,68,68,0.1)' },
  purple: { icon: '#8b5cf6', glow: 'rgba(139,92,246,0.1)' },
  cyan:   { icon: '#06b6d4', glow: 'rgba(6,182,212,0.1)' },
};

export default function StatCard({ label, value, icon, trend, color = 'blue', subtitle, onClick }: StatCardProps) {
  const colors = colorMap[color];

  return (
    <div
      onClick={onClick}
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: '12px',
        padding: '20px',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all 0.2s ease',
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        if (onClick) {
          e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)';
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
      }}
    >
      {/* Subtle glow */}
      <div style={{
        position: 'absolute', top: '-20px', right: '-20px', width: '80px', height: '80px',
        background: `radial-gradient(circle, ${colors.glow} 0%, transparent 70%)`,
        borderRadius: '50%',
      }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px', position: 'relative' }}>
        <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          {label}
        </p>
        {icon && (
          <div style={{ color: colors.icon, opacity: 0.8 }}>
            {icon}
          </div>
        )}
      </div>

      <div style={{ position: 'relative' }}>
        <p style={{ margin: 0, fontSize: '28px', fontWeight: 800, color: '#f1f5f9', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
          {value}
        </p>
        {trend && (
          <p style={{
            margin: '6px 0 0', fontSize: '12px', fontWeight: 600,
            color: trend.positive ? '#34d399' : '#f87171',
          }}>
            {trend.value}
          </p>
        )}
        {subtitle && (
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#64748b' }}>
            {subtitle}
          </p>
        )}
      </div>
    </div>
  );
}
