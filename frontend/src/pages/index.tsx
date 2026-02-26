import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import { LogIn, Shield, TrendingUp, Users } from 'lucide-react';
import axios from 'axios';

/* ── Animated ORBIT Logo ──────────────────────────────────────────────── */
const OrbitLogo: React.FC<{ size?: 'lg' | 'md' }> = ({ size = 'lg' }) => {
  const dim = size === 'lg' ? 120 : 88;
  const cx = 50, cy = 50; // viewBox center
  const id = size === 'lg' ? 'desk' : 'mob';

  return (
    <div className="orbit-logo-wrap" style={{ width: dim, height: dim }}>
      <svg viewBox="0 0 100 100" width={dim} height={dim} fill="none" className="orbit-logo-svg">
        <defs>
          <linearGradient id={`og-${id}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#06b6d4" />
            <stop offset="50%" stopColor="#0ea5e9" />
            <stop offset="100%" stopColor="#6366f1" />
          </linearGradient>
          <radialGradient id={`core-${id}`} cx="45%" cy="40%">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.05" />
          </radialGradient>
          <filter id={`glow-${id}`}>
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Core sphere */}
        <circle cx={cx} cy={cy} r="14" fill={`url(#core-${id})`} />
        <circle cx={cx} cy={cy} r="14" stroke={`url(#og-${id})`} strokeWidth="1.8" fill="none" opacity="0.9" />
        <circle cx={cx} cy={cy} r="4" fill={`url(#og-${id})`} opacity="0.9" />

        {/* Orbit ring 1 — tilted, slow */}
        <g className="orbit-ring-1">
          <ellipse cx={cx} cy={cy} rx="38" ry="14"
            stroke={`url(#og-${id})`} strokeWidth="0.8" opacity="0.3"
            strokeDasharray="4 3" />
        </g>

        {/* Orbit ring 2 — opposite tilt */}
        <g className="orbit-ring-2">
          <ellipse cx={cx} cy={cy} rx="32" ry="11"
            stroke={`url(#og-${id})`} strokeWidth="0.6" opacity="0.2"
            strokeDasharray="3 4" />
        </g>

        {/* Satellite 1 — main, bright */}
        <g className="orbit-sat-1" filter={`url(#glow-${id})`}>
          <circle r="4" fill="#06b6d4" />
          <circle r="2.2" fill="#fff" />
        </g>

        {/* Satellite 2 — smaller, dimmer */}
        <g className="orbit-sat-2" filter={`url(#glow-${id})`}>
          <circle r="2.5" fill="#6366f1" opacity="0.7" />
          <circle r="1.2" fill="#fff" opacity="0.8" />
        </g>

        {/* Satellite 3 — tiny accent */}
        <g className="orbit-sat-3">
          <circle r="1.8" fill="#0ea5e9" opacity="0.5" />
          <circle r="0.8" fill="#fff" opacity="0.6" />
        </g>
      </svg>

      {/* Inline CSS for keyframe animations */}
      <style>{`
        .orbit-logo-wrap { position: relative; }

        /* Ring rotations */
        .orbit-ring-1 {
          transform-origin: 50px 50px;
          animation: ring1Spin 20s linear infinite;
        }
        .orbit-ring-2 {
          transform-origin: 50px 50px;
          animation: ring2Spin 28s linear infinite reverse;
        }
        @keyframes ring1Spin {
          from { transform: rotate(-25deg); }
          to   { transform: rotate(335deg); }
        }
        @keyframes ring2Spin {
          from { transform: rotate(30deg); }
          to   { transform: rotate(390deg); }
        }

        /* Satellite 1 — main orbit, ~5s period */
        .orbit-sat-1 {
          transform-origin: 50px 50px;
          animation: sat1Orbit 5s linear infinite;
        }
        @keyframes sat1Orbit {
          0%   { transform: rotate(-25deg)  translate(38px, 0) rotate(25deg); }
          25%  { transform: rotate(65deg)   translate(38px, 0) rotate(-65deg); }
          50%  { transform: rotate(155deg)  translate(38px, 0) rotate(-155deg); }
          75%  { transform: rotate(245deg)  translate(38px, 0) rotate(-245deg); }
          100% { transform: rotate(335deg)  translate(38px, 0) rotate(-335deg); }
        }

        /* Satellite 2 — inner orbit, ~7s, reverse */
        .orbit-sat-2 {
          transform-origin: 50px 50px;
          animation: sat2Orbit 7s linear infinite;
        }
        @keyframes sat2Orbit {
          0%   { transform: rotate(30deg)   translate(32px, 0) rotate(-30deg); }
          25%  { transform: rotate(120deg)  translate(32px, 0) rotate(-120deg); }
          50%  { transform: rotate(210deg)  translate(32px, 0) rotate(-210deg); }
          75%  { transform: rotate(300deg)  translate(32px, 0) rotate(-300deg); }
          100% { transform: rotate(390deg)  translate(32px, 0) rotate(-390deg); }
        }

        /* Satellite 3 — tight orbit, fast */
        .orbit-sat-3 {
          transform-origin: 50px 50px;
          animation: sat3Orbit 3.5s linear infinite;
        }
        @keyframes sat3Orbit {
          0%   { transform: rotate(0deg)    translate(20px, 0) rotate(0deg); }
          100% { transform: rotate(360deg)  translate(20px, 0) rotate(-360deg); }
        }

        /* Gentle pulse on the core */
        .orbit-logo-svg circle:nth-child(3) {
          animation: corePulse 3s ease-in-out infinite;
        }
        @keyframes corePulse {
          0%, 100% { opacity: 0.9; }
          50%      { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
};

/* ── Login Page ───────────────────────────────────────────────────────── */
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
      {/* Left side - Branding (desktop) */}
      <div className="hidden lg:flex lg:w-1/2 gradient-bg relative overflow-hidden">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiNmZmZmZmYiIGZpbGwtb3BhY2l0eT0iMC4xIj48cGF0aCBkPSJNMzYgMzRjMC0yLjIxLTEuNzktNC00LTRzLTQgMS43OS00IDQgMS43OSA0IDQgNCA0LTEuNzkgNC00em0wLTEwYzAtMi4yMS0xLjc5LTQtNC00cy00IDEuNzktNCA0IDEuNzkgNCA0IDQgNC0xLjc5IDQtNHptMC0xMGMwLTIuMjEtMS43OS00LTQtNHMtNCAxLjc5LTQgNCAxLjc5IDQgNCA0IDQtMS43OSA0LTR6Ii8+PC9nPjwvZz48L3N2Zz4=')] opacity-20"></div>
        
        <div className="relative z-10 flex flex-col justify-center px-16 text-white">
          <div className="mb-8">
            <OrbitLogo size="lg" />
            <h1 className="font-display font-bold text-5xl mb-4 mt-4">
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
          <div className="lg:hidden mb-8 text-center flex flex-col items-center">
            <OrbitLogo size="md" />
            <h1 className="font-display font-bold text-3xl tracking-[0.2em] text-white mb-1 mt-3">ORBIT</h1>
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
                  <p className="text-sm text-slate-600 mb-4">Enter your email address and we&apos;ll send you a password reset link.</p>
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
