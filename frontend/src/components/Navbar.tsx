import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import { useTheme, THEMES } from '../contexts/ThemeContext';
import {
  LogOut, TrendingUp, FileText, Upload, BarChart2, Clock,
  Palette, Check, Menu, X, ChevronDown, Settings, Shield, Users,
} from 'lucide-react';

const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const [showMenu, setShowMenu] = useState(false);
  const [showThemePicker, setShowThemePicker] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  const isAdmin = user?.role?.toLowerCase() === 'admin';
  const isManager = user?.role?.toLowerCase() === 'manager' || isAdmin;

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

  const navItems = [
    { href: '/dashboard', label: 'Dashboard', icon: <TrendingUp size={16} />, show: true },
    { href: '/sales', label: 'Sales', icon: <FileText size={16} />, show: true },
    { href: '/quotes', label: 'Quotes', icon: <FileText size={16} />, show: true },
    { href: '/customers', label: 'Customers', icon: <Users size={16} />, show: true },
    { href: '/analytics', label: 'Analytics', icon: <BarChart2 size={16} />, show: true },
    { href: '/commissions', label: 'Commissions', icon: <TrendingUp size={16} />, show: true },
    { href: '/timeclock', label: 'Attendance', icon: <Clock size={16} />, show: true },
    { href: '/statements', label: 'Reconciliation', icon: <Upload size={16} />, show: isManager },
    { href: '/retention', label: 'Retention', icon: <BarChart2 size={16} />, show: isManager },
    { href: '/life-crosssell', label: 'Life Insurance', icon: <Shield size={16} />, show: isManager },
    { href: '/admin', label: 'Admin', icon: <Shield size={16} />, show: isAdmin },
  ].filter((i) => i.show);

  const currentPage = navItems.find((i) => router.asPath.startsWith(i.href))?.label || 'Menu';

  return (
    <nav className="glass sticky top-0 z-50 border-b border-white/20">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-14">
          {/* Left: Logo + Nav Dropdown */}
          <div className="flex items-center space-x-4">
            <Link href="/dashboard" className="flex items-center space-x-2.5 group flex-shrink-0">
              {/* AEGIS Logo Mark */}
              <div className="relative h-9 w-9 flex items-center justify-center">
                <svg viewBox="0 0 40 40" className="h-9 w-9" fill="none">
                  {/* Outer shield glow */}
                  <defs>
                    <linearGradient id="shieldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#06b6d4" />
                      <stop offset="50%" stopColor="#0ea5e9" />
                      <stop offset="100%" stopColor="#3b82f6" />
                    </linearGradient>
                    <filter id="logoGlow">
                      <feGaussianBlur stdDeviation="1.5" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                  </defs>
                  {/* Shield shape */}
                  <path
                    d="M20 3L5 10v10c0 10.5 6.4 20.3 15 23 8.6-2.7 15-12.5 15-23V10L20 3z"
                    fill="url(#shieldGrad)"
                    opacity="0.15"
                    filter="url(#logoGlow)"
                  />
                  <path
                    d="M20 3L5 10v10c0 10.5 6.4 20.3 15 23 8.6-2.7 15-12.5 15-23V10L20 3z"
                    fill="none"
                    stroke="url(#shieldGrad)"
                    strokeWidth="1.5"
                  />
                  {/* Inner A letterform */}
                  <path
                    d="M20 11L13 27h3l1.5-4h5l1.5 4h3L20 11zm0 5.5L22.5 22h-5L20 16.5z"
                    fill="url(#shieldGrad)"
                  />
                </svg>
              </div>
              <div className="hidden sm:flex flex-col leading-none">
                <span className="font-display font-extrabold text-[15px] tracking-wider aegis-title" style={{
                  background: 'linear-gradient(135deg, #06b6d4, #0ea5e9, #3b82f6)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  letterSpacing: '0.15em',
                }}>
                  AEGIS
                </span>
                <span className="text-[9px] font-semibold text-slate-400 tracking-widest mt-0.5">
                  COMMAND CENTER
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
                  <ChevronDown size={14} className={`transition-transform ${showMenu ? 'rotate-180' : ''}`} />
                </button>

                {showMenu && (
                  <div className="absolute left-0 top-full mt-1.5 w-52 rounded-xl shadow-xl border z-[100] overflow-hidden theme-picker-dropdown">
                    {navItems.map((item) => {
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
                          <span className="theme-picker-name">{item.label}</span>
                          {active && <Check size={14} className="ml-auto text-green-500" />}
                        </Link>
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
