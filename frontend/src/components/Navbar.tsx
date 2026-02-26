import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import { useTheme, THEMES } from '../contexts/ThemeContext';
import { reshopAPI } from '../lib/api';
import axios from 'axios';
import {
  LogOut, TrendingUp, FileText, Upload, BarChart2, Clock,
  Palette, Check, Menu, X, ChevronDown, Settings, Shield, Users, Mail, Target,
  Inbox, MessageCircle, Zap, BookOpen,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';

const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const [showMenu, setShowMenu] = useState(false);
  const [showThemePicker, setShowThemePicker] = useState(false);
  const [reshopBadge, setReshopBadge] = useState(0);
  const [inboxBadge, setInboxBadge] = useState(0);
  const [chatBadge, setChatBadge] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  const isAdmin = user?.role?.toLowerCase() === 'admin';
  const isManager = user?.role?.toLowerCase() === 'manager' || isAdmin;

  // Poll reshop + smart inbox + chat badge counts
  useEffect(() => {
    if (!user) return;
    const load = async () => {
      try {
        const r = await reshopAPI.badgeCount();
        setReshopBadge(r.data.new || 0);
      } catch {}
      if (isManager) {
        try {
          const token = localStorage.getItem('token');
          const r = await axios.get(
            `${API_BASE}/api/smart-inbox/queue`,
            { headers: { Authorization: `Bearer ${token}` } }
          );
          setInboxBadge(Array.isArray(r.data) ? r.data.length : r.data?.items?.length || 0);
        } catch {}
      }
      // Chat unread count
      try {
        const token = localStorage.getItem('token');
        const r = await axios.get(
          `${API_BASE}/api/chat/unread`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setChatBadge(r.data.total_unread || 0);
      } catch {}
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [user, isManager]);

  // SSE for live badge updates
  useEffect(() => {
    if (!user) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/api/events/stream`);
      es.addEventListener('chat:message', () => {
        // Only increment if not on chat page
        if (!window.location.pathname.startsWith('/chat')) {
          setChatBadge(prev => prev + 1);
        }
      });
      es.addEventListener('smart_inbox:new', () => {
        if (isManager) setInboxBadge(prev => prev + 1);
      });
      es.addEventListener('smart_inbox:updated', () => {
        if (isManager) setInboxBadge(prev => Math.max(0, prev - 1));
      });
      es.addEventListener('reshop:new', () => {
        setReshopBadge(prev => prev + 1);
      });
      es.onerror = () => {
        es?.close();
        // Reconnect after 10s
        setTimeout(() => {
          if (user) {
            // Will reconnect on next poll cycle
          }
        }, 10000);
      };
    } catch {}
    return () => es?.close();
  }, [user, isManager]);

  // Close dropdowns on outside click
  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setShowMenu(false);
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setShowThemePicker(false);
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  // Close menu on route change
  useEffect(() => { setShowMenu(false); }, [router.asPath]);

  // Nav items grouped into sections
  const navSections = [
    {
      label: 'Core',
      items: [
        { href: '/dashboard', label: 'Dashboard', icon: <TrendingUp size={16} />, show: true },
        { href: '/customers', label: 'Customers', icon: <Users size={16} />, show: true },
      ],
    },
    {
      label: 'Sales',
      items: [
        { href: '/sales', label: 'Sales', icon: <FileText size={16} />, show: true },
        { href: '/quotes', label: 'Quotes', icon: <FileText size={16} />, show: true },
        { href: '/reshop', label: 'Reshop Pipeline', icon: <Target size={16} />, show: true, badge: reshopBadge },
        { href: '/leads', label: 'Lead Control', icon: <Zap size={16} />, show: isManager },
        { href: '/life-crosssell', label: 'Life Insurance', icon: <Shield size={16} />, show: isManager },
      ],
    },
    {
      label: 'Operations',
      items: [
        { href: '/smart-inbox', label: 'Smart Inbox', icon: <Mail size={16} />, show: isManager, badge: inboxBadge },
        { href: '/beacon-kb', label: 'BEACON Knowledge', icon: <BookOpen size={16} />, show: true },
        { href: '/chat', label: 'Team Chat', icon: <MessageCircle size={16} />, show: true, badge: chatBadge },
        { href: '/commissions', label: 'Commissions', icon: <TrendingUp size={16} />, show: true },
        { href: '/analytics', label: 'Analytics', icon: <BarChart2 size={16} />, show: true },
        { href: '/retention', label: 'Retention', icon: <BarChart2 size={16} />, show: isManager },
        { href: '/statements', label: 'Reconciliation', icon: <Upload size={16} />, show: isManager },
        { href: '/timeclock', label: 'Attendance', icon: <Clock size={16} />, show: true },
      ],
    },
    {
      label: 'System',
      items: [
        { href: '/admin', label: 'Admin', icon: <Shield size={16} />, show: isAdmin },
      ],
    },
  ];

  // Flat list for currentPage lookup
  const allNavItems = navSections.flatMap(s => s.items).filter(i => i.show);
  const currentPage = allNavItems.find((i) => router.asPath.startsWith(i.href))?.label || 'Menu';

  // Total badge count for mobile indicator
  const totalBadges = reshopBadge + inboxBadge + chatBadge;

  return (
    <nav className="glass sticky top-0 z-50 border-b border-white/20">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-14">
          {/* Left: Logo + Nav Dropdown */}
          <div className="flex items-center space-x-4">
            <Link href="/dashboard" className="flex items-center space-x-2.5 group flex-shrink-0">
              {/* ORBIT Logo Mark */}
              <div className="relative h-9 w-9 flex items-center justify-center">
                <svg viewBox="0 0 40 40" className="h-9 w-9" fill="none">
                  <defs>
                    <linearGradient id="orbitGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#06b6d4" />
                      <stop offset="60%" stopColor="#0ea5e9" />
                      <stop offset="100%" stopColor="#6366f1" />
                    </linearGradient>
                    <filter id="orbitGlow">
                      <feGaussianBlur stdDeviation="1.2" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                  </defs>
                  {/* Outer orbital ring */}
                  <ellipse cx="20" cy="20" rx="17" ry="10" stroke="url(#orbitGrad)" strokeWidth="1.2" opacity="0.5" transform="rotate(-25 20 20)" />
                  {/* Inner orbital ring */}
                  <ellipse cx="20" cy="20" rx="14" ry="7" stroke="url(#orbitGrad)" strokeWidth="0.8" opacity="0.3" transform="rotate(30 20 20)" />
                  {/* Core circle */}
                  <circle cx="20" cy="20" r="7" fill="url(#orbitGrad)" opacity="0.15" filter="url(#orbitGlow)" />
                  <circle cx="20" cy="20" r="7" stroke="url(#orbitGrad)" strokeWidth="1.5" fill="none" />
                  {/* Satellite dot */}
                  <circle cx="35" cy="14" r="2.5" fill="#06b6d4" filter="url(#orbitGlow)" />
                  <circle cx="35" cy="14" r="1.5" fill="#fff" />
                  {/* Center dot */}
                  <circle cx="20" cy="20" r="2" fill="url(#orbitGrad)" />
                </svg>
              </div>
              <div className="hidden sm:flex flex-col leading-none">
                <span className="font-display font-extrabold text-[16px]" style={{
                  background: 'linear-gradient(135deg, #06b6d4, #0ea5e9, #6366f1)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  letterSpacing: '0.05em',
                }}>
                  Better Choice <span style={{ letterSpacing: '0.15em' }}>ORBIT</span>
                </span>
                <span className="text-[8px] font-medium text-slate-400 tracking-[0.08em] mt-0.5">
                  Operations · Renewals · Binding · Intelligence · Tracking
                </span>
              </div>
            </Link>

            {/* Nav Dropdown */}
            {user && (
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowMenu(!showMenu)}
                  className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold nav-menu-trigger transition-colors"
                >
                  <Menu size={16} />
                  <span>{currentPage}</span>
                  {totalBadges > 0 && (
                    <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-red-500 text-white leading-none">
                      {totalBadges > 9 ? '9+' : totalBadges}
                    </span>
                  )}
                  <ChevronDown size={14} className={`transition-transform ${showMenu ? 'rotate-180' : ''}`} />
                </button>

                {showMenu && (
                  <div className="absolute left-0 top-full mt-1.5 w-56 rounded-xl shadow-xl border z-[100] overflow-hidden theme-picker-dropdown max-h-[70vh] overflow-y-auto">
                    {navSections.map((section) => {
                      const visibleItems = section.items.filter(i => i.show);
                      if (visibleItems.length === 0) return null;
                      return (
                        <div key={section.label}>
                          <div className="px-3 py-1.5 border-b theme-picker-header">
                            <p className="text-[10px] font-bold uppercase tracking-wider theme-picker-label opacity-50">{section.label}</p>
                          </div>
                          {visibleItems.map((item) => {
                            const active = router.asPath.startsWith(item.href);
                            return (
                              <Link
                                key={item.href}
                                href={item.href}
                                className={`flex items-center space-x-2.5 px-3 py-2.5 text-sm font-medium transition-colors theme-picker-item ${
                                  active ? 'nav-menu-active' : ''
                                }`}
                              >
                                <span className="nav-menu-icon">{item.icon}</span>
                                <span className="theme-picker-name flex-1">{item.label}</span>
                                {item.badge && item.badge > 0 ? (
                                  <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-red-500 text-white leading-none">
                                    {item.badge > 9 ? '9+' : item.badge}
                                  </span>
                                ) : null}
                                {active && <Check size={14} className="text-green-500" />}
                              </Link>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right: Theme + User + Logout */}
          {user && (
            <div className="flex items-center space-x-1.5">
              {/* Theme Picker */}
              <div className="relative" ref={pickerRef}>
                <button
                  onClick={() => setShowThemePicker(!showThemePicker)}
                  className="p-2 rounded-lg hover:bg-brand-50 text-slate-500 hover:text-brand-600 transition-colors"
                  title="Change theme"
                >
                  <Palette size={18} />
                </button>

                {showThemePicker && (
                  <div className="absolute right-0 top-full mt-1.5 w-52 rounded-xl shadow-xl border z-[100] overflow-hidden theme-picker-dropdown">
                    <div className="px-3 py-2 border-b theme-picker-header">
                      <p className="text-xs font-semibold uppercase tracking-wide theme-picker-label">Theme</p>
                    </div>
                    {THEMES.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => { setTheme(t.id); setShowThemePicker(false); }}
                        className="w-full flex items-center space-x-2.5 px-3 py-2.5 text-left transition-colors theme-picker-item"
                      >
                        <span
                          className="w-4 h-4 rounded-full border-2 flex-shrink-0"
                          style={{
                            backgroundColor: t.preview,
                            borderColor: theme === t.id ? 'var(--mc-accent, #3b82f6)' : 'rgba(128,128,128,0.3)',
                          }}
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium theme-picker-name">{t.name}</p>
                        </div>
                        {theme === t.id && <Check size={14} className="text-green-500 flex-shrink-0" />}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* User */}
              <div className="hidden sm:flex items-center space-x-1.5 pl-1.5 border-l nav-divider ml-1">
                <div className="text-right">
                  <p className="text-sm font-semibold text-slate-900 leading-tight">{user.full_name}</p>
                  <p className="text-xs text-brand-600 capitalize leading-tight">{user.role}</p>
                </div>
                <button
                  onClick={logout}
                  className="p-1.5 rounded-lg hover:bg-brand-50 text-slate-500 hover:text-red-500 transition-colors"
                  title="Logout"
                >
                  <LogOut size={18} />
                </button>
              </div>

              {/* Mobile logout only */}
              <button
                onClick={logout}
                className="sm:hidden p-2 rounded-lg hover:bg-brand-50 text-slate-500 hover:text-red-500 transition-colors"
                title="Logout"
              >
                <LogOut size={18} />
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
