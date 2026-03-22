/**
 * PageHeader — consistent header for all ORBIT pages.
 * 
 * Usage:
 *   <PageHeader 
 *     title="Reshop Pipeline"
 *     subtitle="Track customer reshop requests from intake to resolution"
 *     badge={{ label: '45 Active', color: 'blue' }}
 *     actions={<button>+ New Reshop</button>}
 *   />
 */

import React from 'react';

interface Badge {
  label: string;
  color?: 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'gray';
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  badge?: Badge;
  actions?: React.ReactNode;
  breadcrumb?: string;
}

const badgeColors: Record<string, { bg: string; text: string; border: string }> = {
  blue:   { bg: 'rgba(59,130,246,0.1)',  text: '#60a5fa', border: 'rgba(59,130,246,0.2)' },
  green:  { bg: 'rgba(16,185,129,0.1)',  text: '#34d399', border: 'rgba(16,185,129,0.2)' },
  amber:  { bg: 'rgba(245,158,11,0.1)',  text: '#fbbf24', border: 'rgba(245,158,11,0.2)' },
  red:    { bg: 'rgba(239,68,68,0.1)',   text: '#f87171', border: 'rgba(239,68,68,0.2)' },
  purple: { bg: 'rgba(139,92,246,0.1)',  text: '#a78bfa', border: 'rgba(139,92,246,0.2)' },
  gray:   { bg: 'rgba(148,163,184,0.1)', text: '#94a3b8', border: 'rgba(148,163,184,0.2)' },
};

export default function PageHeader({ title, subtitle, badge, actions, breadcrumb }: PageHeaderProps) {
  const colors = badge ? badgeColors[badge.color || 'blue'] : null;

  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
      marginBottom: '24px', flexWrap: 'wrap', gap: '12px',
    }}>
      <div>
        {breadcrumb && (
          <p style={{ margin: '0 0 4px', fontSize: '12px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 600 }}>
            {breadcrumb}
          </p>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <h1 style={{
            margin: 0, fontSize: '24px', fontWeight: 700, color: '#f1f5f9',
            letterSpacing: '-0.02em',
          }}>
            {title}
          </h1>
          {badge && colors && (
            <span style={{
              padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 600,
              background: colors.bg, color: colors.text, border: `1px solid ${colors.border}`,
            }}>
              {badge.label}
            </span>
          )}
        </div>
        {subtitle && (
          <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#64748b' }}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          {actions}
        </div>
      )}
    </div>
  );
}
