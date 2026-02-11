import React from 'react';
import Link from 'next/link';
import { useAuth } from '../contexts/AuthContext';
import { LogOut, User, TrendingUp, FileText, Upload, BarChart2 } from 'lucide-react';

const Navbar: React.FC = () => {
  const { user, logout } = useAuth();

  return (
    <nav className="glass sticky top-0 z-50 border-b border-white/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <Link href="/dashboard" className="flex items-center space-x-3 group">
            <div className="w-10 h-10 bg-gradient-to-br from-brand-600 to-brand-700 rounded-lg flex items-center justify-center shadow-lg group-hover:shadow-xl transition-shadow">
              <span className="text-white font-bold text-xl">BC</span>
            </div>
            <div>
              <h1 className="font-display font-bold text-lg text-slate-900 tracking-tight">
                Better Choice
              </h1>
              <p className="text-xs text-brand-600 font-medium -mt-1">Insurance</p>
            </div>
          </Link>

          {/* Navigation Links */}
          {user && (
            <div className="hidden md:flex items-center space-x-1">
              <NavLink href="/dashboard" icon={<TrendingUp size={18} />}>
                Dashboard
              </NavLink>
              <NavLink href="/sales" icon={<FileText size={18} />}>
                Sales
              </NavLink>
              <NavLink href="/analytics" icon={<BarChart2 size={18} />}>
                Analytics
              </NavLink>
              <NavLink href="/commissions" icon={<TrendingUp size={18} />}>
                Commissions
              </NavLink>
              {(user.role?.toLowerCase() === 'admin' || user.role?.toLowerCase() === 'manager') && (
                <NavLink href="/statements" icon={<Upload size={18} />}>
                  Reconciliation
                </NavLink>
              )}
              {(user.role?.toLowerCase() === 'admin' || user.role?.toLowerCase() === 'manager') && (
                <NavLink href="/retention" icon={<BarChart2 size={18} />}>
                  Retention
                </NavLink>
              )}
              {user.role?.toLowerCase() === 'admin' && (
                <NavLink href="/admin" icon={<Upload size={18} />}>
                  Admin
                </NavLink>
              )}
            </div>
          )}

          {/* User Menu */}
          {user && (
            <div className="flex items-center space-x-3">
              <div className="hidden sm:block text-right">
                <p className="text-sm font-semibold text-slate-900">{user.full_name}</p>
                <p className="text-xs text-brand-600 capitalize">{user.role}</p>
              </div>
              <button
                onClick={logout}
                className="p-2 rounded-lg hover:bg-brand-50 text-slate-600 hover:text-brand-600 transition-colors"
                title="Logout"
              >
                <LogOut size={20} />
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

const NavLink: React.FC<{ href: string; icon: React.ReactNode; children: React.ReactNode }> = ({
  href,
  icon,
  children,
}) => {
  return (
    <Link
      href={href}
      className="flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium text-slate-700 hover:bg-brand-50 hover:text-brand-700 transition-colors"
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
};

export default Navbar;
