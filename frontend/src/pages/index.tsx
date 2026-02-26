import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import { LogIn, Shield, TrendingUp, Users } from 'lucide-react';
import axios from 'axios';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotStatus, setForgotStatus] = useState('');
  const { login } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
      // Route based on username
      if (username.toLowerCase() === 'evan.larson') {
        router.push('/customers');
      } else {
        router.push('/dashboard');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left side - Branding */}
      <div className="hidden lg:flex lg:w-1/2 gradient-bg relative overflow-hidden">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiNmZmZmZmYiIGZpbGwtb3BhY2l0eT0iMC4xIj48cGF0aCBkPSJNMzYgMzRjMC0yLjIxLTEuNzktNC00LTRzLTQgMS43OS00IDQgMS43OSA0IDQgNCA0LTEuNzkgNC00em0wLTEwYzAtMi4yMS0xLjc5LTQtNC00cy00IDEuNzktNCA0IDEuNzkgNCA0IDQgNC0xLjc5IDQtNHptMC0xMGMwLTIuMjEtMS43OS00LTQtNHMtNCAxLjc5LTQgNCAxLjc5IDQgNCA0IDQtMS43OSA0LTR6Ii8+PC9nPjwvZz48L3N2Zz4=')] opacity-20"></div>
        
        <div className="relative z-10 flex flex-col justify-center px-16 text-white">
          <div className="mb-8">
            {/* ORBIT Logo */}
            <svg viewBox="0 0 40 40" className="h-16 w-16 mb-6" fill="none">
              <defs>
                <linearGradient id="orbitGradLogin" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#06b6d4" />
                  <stop offset="60%" stopColor="#0ea5e9" />
                  <stop offset="100%" stopColor="#6366f1" />
                </linearGradient>
              </defs>
              <ellipse cx="20" cy="20" rx="17" ry="10" stroke="url(#orbitGradLogin)" strokeWidth="1.2" opacity="0.5" transform="rotate(-25 20 20)" />
              <ellipse cx="20" cy="20" rx="14" ry="7" stroke="url(#orbitGradLogin)" strokeWidth="0.8" opacity="0.3" transform="rotate(30 20 20)" />
              <circle cx="20" cy="20" r="7" fill="url(#orbitGradLogin)" opacity="0.15" />
              <circle cx="20" cy="20" r="7" stroke="url(#orbitGradLogin)" strokeWidth="1.5" fill="none" />
              <circle cx="35" cy="14" r="2.5" fill="#06b6d4" />
              <circle cx="35" cy="14" r="1.5" fill="#fff" />
              <circle cx="20" cy="20" r="2" fill="url(#orbitGradLogin)" />
            </svg>
            <h1 className="font-display font-bold text-5xl mb-4">
              <span className="tracking-[0.2em]">ORBIT</span>
            </h1>
            <p className="text-xl text-blue-100 font-light">
              Better Choice Insurance Group
            </p>
          </div>

          <div className="space-y-6 mt-12">
            <Feature icon={<Shield size={24} />} title="Secure & Reliable">
              Enterprise-grade security for your sensitive data
            </Feature>
            <Feature icon={<TrendingUp size={24} />} title="Track Performance">
              Real-time commission tracking and analytics
            </Feature>
            <Feature icon={<Users size={24} />} title="Team Collaboration">
              Seamless coordination across your entire agency
            </Feature>
          </div>
        </div>
      </div>

      {/* Right side - Login Form */}
      <div className="flex-1 flex items-center justify-center px-4 sm:px-6 lg:px-20 xl:px-24 pattern-bg">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="lg:hidden mb-8 text-center">
            {/* ORBIT Logo - Mobile */}
            <svg viewBox="0 0 40 40" className="h-12 w-12 mx-auto mb-3" fill="none">
              <defs>
                <linearGradient id="orbitGradMobile" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#06b6d4" />
                  <stop offset="60%" stopColor="#0ea5e9" />
                  <stop offset="100%" stopColor="#6366f1" />
                </linearGradient>
              </defs>
              <ellipse cx="20" cy="20" rx="17" ry="10" stroke="url(#orbitGradMobile)" strokeWidth="1.2" opacity="0.5" transform="rotate(-25 20 20)" />
              <ellipse cx="20" cy="20" rx="14" ry="7" stroke="url(#orbitGradMobile)" strokeWidth="0.8" opacity="0.3" transform="rotate(30 20 20)" />
              <circle cx="20" cy="20" r="7" fill="url(#orbitGradMobile)" opacity="0.15" />
              <circle cx="20" cy="20" r="7" stroke="url(#orbitGradMobile)" strokeWidth="1.5" fill="none" />
              <circle cx="35" cy="14" r="2.5" fill="#06b6d4" />
              <circle cx="35" cy="14" r="1.5" fill="#fff" />
              <circle cx="20" cy="20" r="2" fill="url(#orbitGradMobile)" />
            </svg>
            <h1 className="font-display font-bold text-3xl tracking-[0.2em] text-white mb-1">ORBIT</h1>
            <img src="/logo-bci.png" alt="Better Choice Insurance Group" className="h-12 w-auto mx-auto mb-3 mt-4" />
            <h2 className="font-display font-bold text-2xl text-white">Better Choice</h2>
            <p className="text-cyan-400 font-medium">Insurance Group</p>
          </div>

          <div className="card animate-fade-in">
            <div className="mb-8">
              <h2 className="font-display text-3xl font-bold text-slate-900 mb-2">
                Welcome Back
              </h2>
              <p className="text-slate-600">Sign in to access your dashboard</p>
            </div>

            {error && (
              <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-red-800 text-sm">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-2">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-field"
                  placeholder="Enter your username"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-slate-700 mb-2">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-field"
                  placeholder="Enter your password"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full btn-primary flex items-center justify-center space-x-2"
              >
                <LogIn size={20} />
                <span>{loading ? 'Signing in...' : 'Sign In'}</span>
              </button>
            </form>

            <div className="mt-6 text-center">
              <button
                type="button"
                onClick={() => setShowForgotPassword(true)}
                className="text-sm text-blue-600 hover:text-blue-800 hover:underline transition-colors"
              >
                Forgot your password?
              </button>
            </div>

            {/* Forgot Password Modal */}
            {showForgotPassword && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => { setShowForgotPassword(false); setForgotEmail(''); setForgotStatus(''); }}>
                <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl" onClick={(e) => e.stopPropagation()}>
                  <h3 className="text-lg font-bold text-slate-900 mb-2">Reset Password</h3>
                  <p className="text-sm text-slate-600 mb-4">Enter your email address and we'll send you a password reset link.</p>
                  <input
                    type="email"
                    value={forgotEmail}
                    onChange={(e) => setForgotEmail(e.target.value)}
                    className="input-field mb-4"
                    placeholder="Enter your email"
                  />
                  {forgotStatus && (
                    <div className={`mb-4 p-3 rounded-lg text-sm ${forgotStatus.includes('error') ? 'bg-red-50 text-red-800' : 'bg-green-50 text-green-800'}`}>
                      {forgotStatus}
                    </div>
                  )}
                  <div className="flex gap-3">
                    <button
                      onClick={async () => {
                        if (!forgotEmail) return;
                        setForgotStatus('');
                        try {
                          await axios.post(`${process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com'}/api/auth/forgot-password`, { email: forgotEmail });
                          setForgotStatus('If an account with that email exists, a password reset link has been sent.');
                        } catch {
                          setForgotStatus('If an account with that email exists, a password reset link has been sent.');
                        }
                      }}
                      className="flex-1 btn-primary text-sm py-2"
                    >
                      Send Reset Link
                    </button>
                    <button
                      onClick={() => { setShowForgotPassword(false); setForgotEmail(''); setForgotStatus(''); }}
                      className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 border border-slate-300 rounded-lg"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const Feature: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({
  icon,
  title,
  children,
}) => (
  <div className="flex items-start space-x-4">
    <div className="flex-shrink-0 w-12 h-12 bg-white/10 backdrop-blur-sm rounded-lg flex items-center justify-center">
      {icon}
    </div>
    <div>
      <h3 className="font-semibold text-lg mb-1">{title}</h3>
      <p className="text-blue-100 text-sm">{children}</p>
    </div>
  </div>
);
