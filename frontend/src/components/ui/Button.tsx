/**
 * Button — consistent button component for ORBIT.
 * 
 * Usage:
 *   <Button variant="primary" icon={<Plus size={16} />}>Add New</Button>
 *   <Button variant="ghost" size="sm" onClick={cancel}>Cancel</Button>
 *   <Button variant="danger" loading>Deleting...</Button>
 */

import React from 'react';
import { Spinner } from './LoadingStates';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'outline';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
}

const variantStyles: Record<Variant, React.CSSProperties> = {
  primary: {
    background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
    color: '#fff',
    border: 'none',
    boxShadow: '0 2px 8px rgba(37,99,235,0.3)',
  },
  secondary: {
    background: 'rgba(255,255,255,0.06)',
    color: '#e2e8f0',
    border: '1px solid rgba(255,255,255,0.1)',
  },
  ghost: {
    background: 'transparent',
    color: '#94a3b8',
    border: '1px solid transparent',
  },
  danger: {
    background: 'rgba(239,68,68,0.15)',
    color: '#f87171',
    border: '1px solid rgba(239,68,68,0.2)',
  },
  success: {
    background: 'rgba(16,185,129,0.15)',
    color: '#34d399',
    border: '1px solid rgba(16,185,129,0.2)',
  },
  outline: {
    background: 'transparent',
    color: '#60a5fa',
    border: '1px solid rgba(96,165,250,0.3)',
  },
};

const sizeStyles: Record<Size, React.CSSProperties> = {
  sm: { padding: '6px 14px', fontSize: '12px', borderRadius: '6px' },
  md: { padding: '10px 20px', fontSize: '14px', borderRadius: '8px' },
  lg: { padding: '14px 28px', fontSize: '16px', borderRadius: '10px' },
};

export default function Button({
  variant = 'primary',
  size = 'md',
  icon,
  loading,
  fullWidth,
  children,
  disabled,
  style,
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      {...props}
      disabled={isDisabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        fontWeight: 600,
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        opacity: isDisabled ? 0.6 : 1,
        transition: 'all 0.2s ease',
        width: fullWidth ? '100%' : undefined,
        ...variantStyles[variant],
        ...sizeStyles[size],
        ...style,
      }}
    >
      {loading ? <Spinner size="sm" /> : icon}
      {children}
    </button>
  );
}
