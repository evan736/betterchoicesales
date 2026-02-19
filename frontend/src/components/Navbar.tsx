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
    { href: '/customers', label: 'Customers', icon: <Users size={16} />, show: true },
    { href: '/analytics', label: 'Analytics', icon: <BarChart2 size={16} />, show: true },
    { href: '/commissions', label: 'Commissions', icon: <TrendingUp size={16} />, show: true },
    { href: '/timeclock', label: 'Attendance', icon: <Clock size={16} />, show: true },
    { href: '/statements', label: 'Reconciliation', icon: <Upload size={16} />, show: isManager },
    { href: '/retention', label: 'Retention', icon: <BarChart2 size={16} />, show: isManager },
    { href: '/admin', label: 'Admin', icon: <Shield size={16} />, show: isAdmin },
  ].filter((i) => i.show);

  const currentPage = navItems.find((i) => router.asPath.startsWith(i.href))?.label || 'Menu';

  return (
    <nav className="glass sticky top-0 z-50 border-b border-white/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-14">
          {/* Left: Logo + Nav Dropdown */}
          <div className="flex items-center space-x-4">
            <Link href="/dashboard" className="flex items-center space-x-2.5 group flex-shrink-0">
              <img src="/logo-bci.png" alt="BCI" className="h-8 w-auto" />
              <span className="font-display font-bold text-base text-brand-900 tracking-tight hidden sm:inline">
                Better Choice
              </span>
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
