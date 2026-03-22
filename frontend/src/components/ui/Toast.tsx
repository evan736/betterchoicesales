/**
 * Toast notification system — replaces all alert() calls across ORBIT.
 * 
 * Usage:
 *   import { toast } from '@/components/ui/Toast';
 *   toast.success('Sale recorded!');
 *   toast.error('Failed to save');
 *   toast.info('Syncing...');
 *   toast.promise(apiCall(), { loading: 'Saving...', success: 'Done!', error: 'Failed' });
 */

import { Toaster, toast as sonnerToast } from 'sonner';
import React from 'react';

// Re-export sonner's toast with our defaults
export const toast = {
  success: (msg: string, opts?: any) => sonnerToast.success(msg, { duration: 3000, ...opts }),
  error: (msg: string, opts?: any) => sonnerToast.error(msg, { duration: 5000, ...opts }),
  info: (msg: string, opts?: any) => sonnerToast.info(msg, { duration: 3000, ...opts }),
  warning: (msg: string, opts?: any) => sonnerToast.warning(msg, { duration: 4000, ...opts }),
  promise: sonnerToast.promise,
  dismiss: sonnerToast.dismiss,
};

/**
 * Toast Provider — add to _app.tsx
 * <ToastProvider />
 */
export function ToastProvider() {
  return (
    <Toaster
      position="top-right"
      expand={false}
      richColors
      closeButton
      theme="dark"
      toastOptions={{
        style: {
          background: '#1e293b',
          border: '1px solid rgba(255,255,255,0.1)',
          color: '#f1f5f9',
          fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
          fontSize: '14px',
          backdropFilter: 'blur(12px)',
        },
      }}
    />
  );
}

export default ToastProvider;
