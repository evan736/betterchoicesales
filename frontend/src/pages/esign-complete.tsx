import React, { useEffect } from 'react';

export default function EsignCompletePage() {
  useEffect(() => {
    // Try to auto-close the tab after 3 seconds
    const timer = setTimeout(() => {
      try { window.close(); } catch {}
    }, 3000);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #f8fafc 0%, #e8f4f8 100%)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <div style={{
        textAlign: 'center',
        maxWidth: '420px',
        padding: '48px 32px',
        background: 'white',
        borderRadius: '16px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
      }}>
        <div style={{ fontSize: '56px', marginBottom: '16px' }}>✅</div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#1e293b', marginBottom: '8px' }}>
          Document Sent!
        </h1>
        <p style={{ color: '#64748b', fontSize: '15px', lineHeight: 1.6, marginBottom: '24px' }}>
          The signature request has been sent to the customer.
          You can close this tab and return to ORBIT.
        </p>
        <button
          onClick={() => { try { window.close(); } catch {} }}
          style={{
            padding: '12px 32px',
            borderRadius: '10px',
            border: 'none',
            background: '#0ea5e9',
            color: 'white',
            fontWeight: 600,
            fontSize: '15px',
            cursor: 'pointer',
          }}
        >
          Close This Tab
        </button>
        <p style={{ color: '#94a3b8', fontSize: '12px', marginTop: '16px' }}>
          This tab will auto-close in a few seconds.
        </p>
      </div>
    </div>
  );
}
