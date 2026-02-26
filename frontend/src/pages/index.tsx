import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import { LogIn, Shield, TrendingUp, Users } from 'lucide-react';
import axios from 'axios';

/* ── Animated ORBIT Text with orbiting satellites ─────────────────────── */
const OrbitHero: React.FC<{ size?: 'lg' | 'sm' }> = ({ size = 'lg' }) => {
  const isLg = size === 'lg';
  return (
    <div className="orbit-hero" style={{ position: 'relative', display: 'inline-block' }}>
      {/* The ORBIT text — this IS the logo */}
      <h1
        className="font-display font-bold tracking-[0.25em] select-none"
        style={{
          fontSize: isLg ? '4.5rem' : '2.8rem',
          background: 'linear-gradient(135deg, #06b6d4 0%, #0ea5e9 40%, #6366f1 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          position: 'relative',
          zIndex: 2,
          lineHeight: 1.1,
        }}
      >
        ORBIT
      </h1>

      {/* Orbit ring — visible ellipse around text */}
      <div
        className="orbit-ring"
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: isLg ? '340px' : '220px',
          height: isLg ? '100px' : '70px',
          marginTop: isLg ? '-50px' : '-35px',
          marginLeft: isLg ? '-170px' : '-110px',
          border: '1px solid rgba(6, 182, 212, 0.2)',
          borderRadius: '50%',
          transform: 'rotateX(60deg)',
          zIndex: 1,
        }}
      />

      {/* Satellite 1 — big bright cyan, outer orbit */}
      <div className="orbit-sat orbit-sat-a" style={{
        position: 'absolute',
        top: '50%', left: '50%',
        width: isLg ? '340px' : '220px',
        height: isLg ? '100px' : '70px',
        marginTop: isLg ? '-50px' : '-35px',
        marginLeft: isLg ? '-170px' : '-110px',
        zIndex: 3,
        pointerEvents: 'none',
      }}>
        <div style={{
          position: 'absolute',
          top: '-6px', left: '50%', marginLeft: '-6px',
          width: isLg ? '14px' : '10px', height: isLg ? '14px' : '10px',
          borderRadius: '50%',
          background: '#06b6d4',
          boxShadow: '0 0 16px 6px rgba(6, 182, 212, 0.6), 0 0 40px 12px rgba(6, 182, 212, 0.3)',
        }}>
          <div style={{
            position: 'absolute', top: '25%', left: '25%',
            width: '50%', height: '50%', borderRadius: '50%',
            background: '#fff',
          }} />
        </div>
      </div>

      {/* Satellite 2 — indigo, slightly smaller orbit, opposite direction */}
      <div className="orbit-sat orbit-sat-b" style={{
        position: 'absolute',
        top: '50%', left: '50%',
        width: isLg ? '280px' : '180px',
        height: isLg ? '80px' : '56px',
        marginTop: isLg ? '-40px' : '-28px',
        marginLeft: isLg ? '-140px' : '-90px',
        zIndex: 3,
        pointerEvents: 'none',
      }}>
        <div style={{
          position: 'absolute',
          top: '-5px', left: '50%', marginLeft: '-5px',
          width: isLg ? '10px' : '8px', height: isLg ? '10px' : '8px',
          borderRadius: '50%',
          background: '#818cf8',
          boxShadow: '0 0 12px 4px rgba(129, 140, 248, 0.5), 0 0 30px 10px rgba(129, 140, 248, 0.2)',
        }}>
          <div style={{
            position: 'absolute', top: '30%', left: '30%',
            width: '40%', height: '40%', borderRadius: '50%',
            background: '#fff', opacity: 0.8,
          }} />
        </div>
      </div>

      {/* Satellite 3 — small fast accent */}
      <div className="orbit-sat orbit-sat-c" style={{
        position: 'absolute',
        top: '50%', left: '50%',
        width: isLg ? '200px' : '140px',
        height: isLg ? '60px' : '44px',
        marginTop: isLg ? '-30px' : '-22px',
        marginLeft: isLg ? '-100px' : '-70px',
        zIndex: 3,
        pointerEvents: 'none',
      }}>
        <div style={{
          position: 'absolute',
          top: '-3px', left: '50%', marginLeft: '-3px',
          width: isLg ? '7px' : '6px', height: isLg ? '7px' : '6px',
          borderRadius: '50%',
          background: '#22d3ee',
          boxShadow: '0 0 8px 3px rgba(34, 211, 238, 0.5)',
        }} />
      </div>

      <style>{`
        /* Satellite A — outer orbit, 4s */
        .orbit-sat-a {
          border-radius: 50%;
          animation: orbitA 4s linear infinite;
          transform-style: preserve-3d;
        }
        @keyframes orbitA {
          0%   { transform: rotateX(60deg) rotateZ(0deg); }
          100% { transform: rotateX(60deg) rotateZ(360deg); }
        }

        /* Satellite B — inner orbit, 6s, reverse */
        .orbit-sat-b {
          border-radius: 50%;
          animation: orbitB 6s linear infinite reverse;
          transform-style: preserve-3d;
        }
        @keyframes orbitB {
          0%   { transform: rotateX(60deg) rotateZ(0deg); }
          100% { transform: rotateX(60deg) rotateZ(360deg); }
        }

        /* Satellite C — tight orbit, 2.5s */
        .orbit-sat-c {
          border-radius: 50%;
          animation: orbitC 2.5s linear infinite;
          transform-style: preserve-3d;
        }
        @keyframes orbitC {
          0%   { transform: rotateX(60deg) rotateZ(0deg); }
          100% { transform: rotateX(60deg) rotateZ(360deg); }
        }

        /* Orbit ring subtle pulse */
        .orbit-ring {
          animation: ringPulse 4s ease-in-out infinite;
        }
        @keyframes ringPulse {
          0%, 100% { border-color: rgba(6, 182, 212, 0.15); }
          50%      { border-color: rgba(6, 182, 212, 0.35); }
        }

        /* Subtle glow behind text */
        .orbit-hero::before {
          content: '';
          position: absolute;
          top: 50%; left: 50%;
          width: 120px; height: 120px;
          margin-top: -60px; margin-left: -60px;
          background: radial-gradient(circle, rgba(6, 182, 212, 0.15) 0%, transparent 70%);
          border-radius: 50%;
          z-index: 0;
          animation: coreGlow 3s ease-in-out infinite;
        }
        @keyframes coreGlow {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50%      { opacity: 1; transform: scale(1.15); }
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
          <div className="mb-12">
            <OrbitHero size="lg" />
            <p className="text-xl text-blue-100 font-light mt-6">
              Operations, Renewals, Binding,<br />Intelligence &amp; Tracking
            </p>
            <p className="text-sm text-blue-200/60 mt-2">
              Better Choice Insurance Group
            </p>
          </div>

          <div className="space-y-6 mt-8">
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
          {/* Mobile Branding */}
          <div className="lg:hidden mb-10 text-center flex flex-col items-center">
            <OrbitHero size="sm" />
            <p className="text-cyan-400/70 text-sm font-medium mt-4">Better Choice Insurance Group</p>
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
