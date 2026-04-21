import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import axios from 'axios';
import { KeyRound, Check, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { toast } from '../components/ui/Toast';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ChangePassword() {
  const router = useRouter();
  const { user, loading, refreshUser, logout } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // If user isn't logged in, boot them to login
  useEffect(() => {
    if (!loading && !user) {
      router.replace('/');
    }
  }, [loading, user, router]);

  const forced = !!user?.must_change_password;

  // Password strength check (mirrors backend min_length=8)
  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const sameAsCurrent =
    newPassword.length > 0 &&
    currentPassword.length > 0 &&
    newPassword === currentPassword;

  const canSubmit =
    !submitting &&
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    confirmPassword.length > 0 &&
    !mismatch &&
    !sameAsCurrent;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!canSubmit) return;

    setSubmitting(true);
    try {
      await axios.post(`${API_URL}/api/auth/change-password`, {
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success('Password updated');
      // Refresh user so must_change_password flips to false everywhere
      await refreshUser();
      // Route by role, matching index.tsx post-login behavior
      if (user?.username?.toLowerCase() === 'evan.larson') {
        router.push('/customers');
      } else {
        router.push('/dashboard');
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d: any) => d.msg || JSON.stringify(d)).join('; '));
      } else {
        setError(detail || 'Failed to update password');
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-slate-500 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-gradient-to-br from-slate-50 via-blue-50 to-slate-100">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-2xl shadow-xl border border-slate-200 p-8">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center">
              <KeyRound className="text-blue-700" size={22} />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">
                {forced ? 'Set Your Password' : 'Change Password'}
              </h1>
              <p className="text-slate-500 text-sm">
                {forced
                  ? 'First-time setup — please choose a new password'
                  : 'Update your ORBIT password'}
              </p>
            </div>
          </div>

          {forced && (
            <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg flex gap-3">
              <AlertCircle className="text-amber-600 shrink-0" size={18} />
              <div className="text-sm text-amber-900">
                Welcome to ORBIT! For security, you need to replace the temporary
                password that was emailed to you before continuing.
              </div>
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-800 text-sm">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Current */}
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                {forced ? 'Temporary password (from your welcome email)' : 'Current password'}
              </label>
              <div className="relative">
                <input
                  type={showCurrent ? 'text' : 'password'}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Enter current password"
                  autoFocus
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowCurrent(!showCurrent)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* New */}
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                New password <span className="text-slate-400 font-normal">(8+ characters)</span>
              </label>
              <div className="relative">
                <input
                  type={showNew ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className={`w-full border rounded-lg px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    tooShort || sameAsCurrent ? 'border-red-300' : 'border-slate-300'
                  }`}
                  placeholder="Enter new password"
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  onClick={() => setShowNew(!showNew)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {tooShort && (
                <p className="text-red-600 text-xs mt-1">Must be at least 8 characters</p>
              )}
              {sameAsCurrent && (
                <p className="text-red-600 text-xs mt-1">New password must differ from current</p>
              )}
            </div>

            {/* Confirm */}
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Confirm new password
              </label>
              <input
                type={showNew ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  mismatch ? 'border-red-300' : 'border-slate-300'
                }`}
                placeholder="Re-enter new password"
                autoComplete="new-password"
              />
              {mismatch && (
                <p className="text-red-600 text-xs mt-1">Passwords don't match</p>
              )}
              {confirmPassword.length > 0 && !mismatch && newPassword.length >= 8 && (
                <p className="text-green-600 text-xs mt-1 flex items-center gap-1">
                  <Check size={12} /> Passwords match
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={!canSubmit}
              className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-colors ${
                canSubmit
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              }`}
            >
              {submitting ? 'Updating...' : forced ? 'Set Password & Continue' : 'Update Password'}
            </button>

            {!forced && (
              <button
                type="button"
                onClick={() => router.back()}
                className="w-full py-2 text-sm text-slate-600 hover:text-slate-900"
              >
                Cancel
              </button>
            )}

            {forced && (
              <button
                type="button"
                onClick={() => {
                  logout();
                  router.push('/');
                }}
                className="w-full py-2 text-xs text-slate-500 hover:text-slate-700"
              >
                Log out instead
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
