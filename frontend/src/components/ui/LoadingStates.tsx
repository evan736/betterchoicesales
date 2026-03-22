/**
 * Shared loading, empty, and error state components.
 * 
 * Usage:
 *   <PageLoader />                          // Full-page skeleton
 *   <CardLoader count={3} />                // Skeleton cards
 *   <TableLoader rows={5} cols={4} />       // Skeleton table
 *   <Spinner size="sm" />                   // Inline spinner
 *   <EmptyState icon={<Inbox />} title="No emails" description="..." />
 *   <ErrorState message="Failed to load" onRetry={refetch} />
 */

import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

// ─── Spinner ────────────────────────────────────────────────────
export function Spinner({ size = 'md', className = '' }: { size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const sizes = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-10 h-10' };
  return (
    <svg className={`animate-spin ${sizes[size]} ${className}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  );
}

// ─── Skeleton Pulse ─────────────────────────────────────────────
function Skeleton({ className = '', style = {} }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={className}
      style={{
        background: 'linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.5s ease-in-out infinite',
        borderRadius: '8px',
        ...style,
      }}
    />
  );
}

// ─── Page Loader (full page skeleton) ───────────────────────────
export function PageLoader() {
  return (
    <div style={{ padding: '32px', maxWidth: '1200px', margin: '0 auto' }}>
      <Skeleton style={{ width: '240px', height: '32px', marginBottom: '8px' }} />
      <Skeleton style={{ width: '360px', height: '16px', marginBottom: '32px' }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '32px' }}>
        {[1, 2, 3, 4].map(i => (
          <Skeleton key={i} style={{ height: '100px' }} />
        ))}
      </div>
      <Skeleton style={{ height: '400px' }} />
    </div>
  );
}

// ─── Card Loader ────────────────────────────────────────────────
export function CardLoader({ count = 3 }: { count?: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(count, 4)}, 1fr)`, gap: '16px' }}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} style={{ height: '120px' }} />
      ))}
    </div>
  );
}

// ─── Table Loader ───────────────────────────────────────────────
export function TableLoader({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div style={{ borderRadius: '12px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.06)' }}>
      {/* Header */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: '12px', padding: '14px 16px', background: 'rgba(255,255,255,0.03)' }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} style={{ height: '14px', width: `${60 + Math.random() * 40}%` }} />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: '12px', padding: '14px 16px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} style={{ height: '14px', width: `${50 + Math.random() * 50}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

// ─── Empty State ────────────────────────────────────────────────
export function EmptyState({ 
  icon, 
  title, 
  description, 
  action,
  actionLabel,
}: { 
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '64px 24px', textAlign: 'center',
      background: 'rgba(255,255,255,0.02)', borderRadius: '16px', border: '1px dashed rgba(255,255,255,0.08)',
    }}>
      {icon && <div style={{ color: '#475569', marginBottom: '16px', opacity: 0.5 }}>{icon}</div>}
      <h3 style={{ margin: '0 0 8px', fontSize: '17px', fontWeight: 600, color: '#94a3b8' }}>{title}</h3>
      {description && <p style={{ margin: '0 0 20px', fontSize: '14px', color: '#64748b', maxWidth: '360px', lineHeight: 1.5 }}>{description}</p>}
      {action && actionLabel && (
        <button
          onClick={action}
          style={{
            background: 'linear-gradient(135deg, #2563eb, #1d4ed8)', color: '#fff',
            padding: '10px 24px', borderRadius: '8px', border: 'none',
            fontSize: '14px', fontWeight: 600, cursor: 'pointer',
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

// ─── Error State ────────────────────────────────────────────────
export function ErrorState({ 
  message = 'Something went wrong', 
  onRetry,
}: { 
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '48px 24px', textAlign: 'center',
      background: 'rgba(239,68,68,0.05)', borderRadius: '16px', border: '1px solid rgba(239,68,68,0.15)',
    }}>
      <AlertTriangle size={36} style={{ color: '#ef4444', marginBottom: '16px', opacity: 0.7 }} />
      <h3 style={{ margin: '0 0 8px', fontSize: '16px', fontWeight: 600, color: '#fca5a5' }}>{message}</h3>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            background: 'rgba(239,68,68,0.15)', color: '#fca5a5',
            padding: '8px 20px', borderRadius: '8px', border: '1px solid rgba(239,68,68,0.2)',
            fontSize: '13px', fontWeight: 600, cursor: 'pointer', marginTop: '12px',
          }}
        >
          <RefreshCw size={14} /> Try Again
        </button>
      )}
    </div>
  );
}

// ─── Shimmer keyframe (inject once) ─────────────────────────────
if (typeof document !== 'undefined') {
  const styleId = 'orbit-shimmer-keyframes';
  if (!document.getElementById(styleId)) {
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`;
    document.head.appendChild(style);
  }
}
