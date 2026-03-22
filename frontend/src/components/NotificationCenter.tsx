/**
 * NotificationCenter — in-app notification bell for the navbar.
 * 
 * Shows a bell icon with unread count badge. Clicking opens a dropdown
 * with recent activity: new sales, reshop updates, emails, etc.
 * 
 * Listens to SSE events for real-time updates.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Bell, X, DollarSign, RefreshCw, Mail, AlertTriangle, CheckCircle, Users, Zap } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

interface Notification {
  id: string;
  type: 'sale' | 'reshop' | 'email' | 'alert' | 'system';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  link?: string;
}

const ICON_MAP: Record<string, React.ReactNode> = {
  sale: <DollarSign size={16} />,
  reshop: <RefreshCw size={16} />,
  email: <Mail size={16} />,
  alert: <AlertTriangle size={16} />,
  system: <Zap size={16} />,
};

const COLOR_MAP: Record<string, string> = {
  sale: '#10b981',
  reshop: '#3b82f6',
  email: '#8b5cf6',
  alert: '#f59e0b',
  system: '#06b6d4',
};

export default function NotificationCenter() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  // Add a notification
  const addNotification = useCallback((notif: Omit<Notification, 'id' | 'timestamp' | 'read'>) => {
    const newNotif: Notification = {
      ...notif,
      id: Date.now().toString() + Math.random().toString(36).slice(2),
      timestamp: new Date(),
      read: false,
    };
    setNotifications(prev => [newNotif, ...prev].slice(0, 50)); // Keep last 50
    setUnreadCount(prev => prev + 1);
  }, []);

  // SSE listener
  useEffect(() => {
    try {
      const es = new EventSource(`${API_BASE}/api/events/stream`);
      esRef.current = es;

      es.addEventListener('sales:new', (e: any) => {
        try {
          const data = JSON.parse(e.data);
          addNotification({
            type: 'sale',
            title: 'New Sale',
            message: data.customer_name ? `${data.customer_name}` : 'A new policy was sold',
            link: '/sales',
          });
        } catch {}
      });

      es.addEventListener('reshop:new', (e: any) => {
        try {
          const data = JSON.parse(e.data);
          addNotification({
            type: 'reshop',
            title: 'New Reshops Detected',
            message: `${data.created || 0} new renewal reshops added to the pipeline`,
            link: '/reshop',
          });
        } catch {}
      });

      es.addEventListener('reshop:updated', (e: any) => {
        try {
          const data = JSON.parse(e.data);
          const msg = data.new_stage
            ? `${data.customer_name} moved to ${data.new_stage} by ${data.user}`
            : `${data.customer_name} updated by ${data.user}`;
          addNotification({
            type: 'reshop',
            title: 'Reshop Updated',
            message: msg,
            link: '/reshop',
          });
        } catch {}
      });

      es.addEventListener('smart_inbox:new', (e: any) => {
        try {
          const data = JSON.parse(e.data);
          addNotification({
            type: 'email',
            title: 'New Inbound Email',
            message: data.subject || 'New email received in Smart Inbox',
            link: '/smart-inbox',
          });
        } catch {}
      });

      es.addEventListener('dashboard:refresh', () => {
        // Silent refresh — no notification needed
      });

      es.onerror = () => {
        es.close();
        // Reconnect after 5 seconds
        setTimeout(() => {
          if (esRef.current === es) {
            esRef.current = null;
          }
        }, 5000);
      };
    } catch {}

    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, [addNotification]);

  // Close on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const markAllRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setUnreadCount(0);
  };

  const handleOpen = () => {
    setIsOpen(!isOpen);
    if (!isOpen) {
      // Mark as read after a short delay
      setTimeout(() => {
        markAllRead();
      }, 2000);
    }
  };

  const timeAgo = (date: Date) => {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  return (
    <div ref={dropdownRef} style={{ position: 'relative' }}>
      {/* Bell Button */}
      <button
        onClick={handleOpen}
        style={{
          position: 'relative',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: '36px', height: '36px', borderRadius: '8px',
          background: isOpen ? 'rgba(255,255,255,0.1)' : 'transparent',
          border: 'none', cursor: 'pointer', color: '#94a3b8',
          transition: 'all 0.2s ease',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#e2e8f0'; }}
        onMouseLeave={(e) => { if (!isOpen) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#94a3b8'; }}}
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span style={{
            position: 'absolute', top: '2px', right: '2px',
            width: '18px', height: '18px', borderRadius: '50%',
            background: '#ef4444', color: '#fff', fontSize: '10px', fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '2px solid var(--mc-bg-primary, #0a0e1a)',
            animation: unreadCount > 0 ? 'pulse 2s infinite' : 'none',
          }}>
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div style={{
          position: 'absolute', top: '44px', right: 0,
          width: '380px', maxHeight: '480px',
          background: 'rgba(15,23,42,0.98)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '12px',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
          overflow: 'hidden',
          zIndex: 9999,
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '14px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#f1f5f9' }}>
              Notifications
            </h3>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {unreadCount > 0 && (
                <button
                  onClick={markAllRead}
                  style={{
                    fontSize: '11px', color: '#60a5fa', background: 'none', border: 'none',
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >
                  Mark all read
                </button>
              )}
              <button
                onClick={() => setIsOpen(false)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: '24px', height: '24px', borderRadius: '6px',
                  background: 'rgba(255,255,255,0.05)', border: 'none',
                  color: '#64748b', cursor: 'pointer',
                }}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Notification List */}
          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
            {notifications.length === 0 ? (
              <div style={{ padding: '40px 16px', textAlign: 'center' }}>
                <Bell size={24} style={{ color: '#475569', marginBottom: '8px', opacity: 0.5 }} />
                <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>No notifications yet</p>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#475569' }}>Activity will appear here in real-time</p>
              </div>
            ) : (
              notifications.map((notif) => (
                <div
                  key={notif.id}
                  onClick={() => {
                    if (notif.link) window.location.href = notif.link;
                    setIsOpen(false);
                  }}
                  style={{
                    display: 'flex', gap: '12px', padding: '12px 16px',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    cursor: notif.link ? 'pointer' : 'default',
                    background: notif.read ? 'transparent' : 'rgba(59,130,246,0.04)',
                    transition: 'background 0.15s ease',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = notif.read ? 'transparent' : 'rgba(59,130,246,0.04)'; }}
                >
                  {/* Icon */}
                  <div style={{
                    width: '32px', height: '32px', borderRadius: '8px',
                    background: `${COLOR_MAP[notif.type]}15`,
                    color: COLOR_MAP[notif.type],
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    {ICON_MAP[notif.type]}
                  </div>

                  {/* Content */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '8px' }}>
                      <p style={{
                        margin: 0, fontSize: '13px', fontWeight: 600,
                        color: notif.read ? '#94a3b8' : '#f1f5f9',
                      }}>
                        {notif.title}
                      </p>
                      <span style={{ fontSize: '11px', color: '#475569', whiteSpace: 'nowrap', flexShrink: 0 }}>
                        {timeAgo(notif.timestamp)}
                      </span>
                    </div>
                    <p style={{
                      margin: '2px 0 0', fontSize: '12px',
                      color: notif.read ? '#64748b' : '#94a3b8',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {notif.message}
                    </p>
                  </div>

                  {/* Unread dot */}
                  {!notif.read && (
                    <div style={{
                      width: '8px', height: '8px', borderRadius: '50%',
                      background: '#3b82f6', flexShrink: 0, marginTop: '6px',
                    }} />
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
