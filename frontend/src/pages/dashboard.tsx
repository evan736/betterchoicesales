import React, { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import TrendingGoals from '../components/TrendingGoals';
import { salesAPI, commissionsAPI, timeclockAPI, tasksAPI, adminAPI, inspectionAPI } from '../lib/api';
import {
  DollarSign,
  TrendingUp,
  FileText,
  Award,
  Clock,
  LogIn,
  LogOut,
  CheckCircle,
  AlertTriangle,
  MapPin,
  Loader,
  Plus,
  BarChart2,
  Upload,
  ExternalLink,
  ChevronDown,
  AlertCircle,
  ClipboardList,
  UserCheck,
  Search,
  Eye,
  Edit3,
  Mail,
  Send,
  XCircle,
  Shield,
  Inbox,
} from 'lucide-react';
import axios from 'axios';
import { toast } from '../components/ui/Toast';

export default function Dashboard() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [recentSales, setRecentSales] = useState<any[]>([]);
  const [tierInfo, setTierInfo] = useState<any>(null);

  // Time clock state
  const [clockStatus, setClockStatus] = useState<any>(null);
  const [clockLoading, setClockLoading] = useState(false);
  const [elapsedTime, setElapsedTime] = useState('');
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'acquiring' | 'acquired' | 'denied' | 'error'>('idle');

  // Smart Inbox state
  const [inboxStats, setInboxStats] = useState<any>(null);

  // Daily Checklist state
  const [checklist, setChecklist] = useState<any>(null);

  const isManager = user?.role?.toLowerCase() === 'manager' || user?.role?.toLowerCase() === 'admin';

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) { loadDashboardData(); loadClockStatus(); if (isManager) { loadInboxStats(); loadChecklist(); } }
  }, [user, loading]);

  // SSE live refresh — auto-reload data when events arrive
  useEffect(() => {
    if (!user) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${baseUrl}/api/events/stream`);
      const refresh = () => {
        loadDashboardData();
        if (isManager) loadInboxStats();
      };
      es.addEventListener('dashboard:refresh', refresh);
      es.addEventListener('sales:new', refresh);
      es.addEventListener('smart_inbox:new', () => { if (isManager) loadInboxStats(); });
      es.addEventListener('smart_inbox:updated', () => { if (isManager) loadInboxStats(); });
      es.onerror = () => { es?.close(); };
    } catch {}
    return () => es?.close();
  }, [user, isManager]);

  const loadInboxStats = async () => {
    try {
      const token = localStorage.getItem('token');
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      const [statsRes, queueRes] = await Promise.all([
        axios.get(`${baseUrl}/api/smart-inbox/stats`, { headers: { Authorization: `Bearer ${token}` } }),
        axios.get(`${baseUrl}/api/smart-inbox/queue`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setInboxStats({
        ...statsRes.data,
        pending_approvals: Array.isArray(queueRes.data) ? queueRes.data.length : queueRes.data?.items?.length || 0,
      });
    } catch {}
  };

  const loadChecklist = async () => {
    try {
      const token = localStorage.getItem('token');
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      const res = await axios.get(`${baseUrl}/api/checklist/today`, { headers: { Authorization: `Bearer ${token}` } });
      setChecklist(res.data);
    } catch {}
  };

  const toggleChecklistItem = async (key: string) => {
    try {
      const token = localStorage.getItem('token');
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'https://better-choice-api.onrender.com';
      await axios.post(`${baseUrl}/api/checklist/toggle/${key}?username=${user?.name || user?.username || ''}`, {}, { headers: { Authorization: `Bearer ${token}` } });
      loadChecklist();
    } catch {}
  };

  const loadDashboardData = async () => {
    // Load independently so one failure doesn't kill the others
    try {
      // Get MTD date range
      const now = new Date();
      const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      const date_from = firstOfMonth.toISOString().split('T')[0]; // "2026-02-01"
      const date_to = now.toISOString().split('T')[0]; // "2026-02-20"

      const salesRes = await salesAPI.list({ date_from, date_to });
      const sales = salesRes.data || [];
      setRecentSales(sales.slice(0, 15));
      const totalPremium = sales.reduce((sum: number, s: any) => sum + parseFloat(s.written_premium || 0), 0);
      setStats({
        totalSales: sales.length,
        totalPremium,
        totalCommission: 0,
        activePolicies: sales.filter((s: any) => s.status === 'active').length,
      });
    } catch (e) { console.error('Sales load failed:', e); }

    try {
      const tierRes = await commissionsAPI.myTier();
      setTierInfo(tierRes.data);
    } catch (e) { console.error('Tier load failed:', e); }

    try {
      const commissionsRes = await commissionsAPI.myCommissions();
      const totalCommission = (commissionsRes.data || []).reduce((sum: number, c: any) => sum + parseFloat(c.commission_amount || 0), 0);
      setStats((prev: any) => prev ? { ...prev, totalCommission } : prev);
    } catch (e) { console.error('Commissions load failed:', e); }
  };

  const loadClockStatus = async () => {
    try { const res = await timeclockAPI.status(); setClockStatus(res.data); }
    catch (e) { console.error('Clock status failed:', e); }
  };

  // Live elapsed timer
  useEffect(() => {
    if (clockStatus?.status !== 'clocked_in') { setElapsedTime(''); return; }
    const clockIn = new Date(clockStatus.clock_in);
    const update = () => {
      const diff = Date.now() - clockIn.getTime();
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setElapsedTime(`${h}h ${m}m ${s}s`);
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [clockStatus]);

  const acquireGPS = (): Promise<{ lat: number; lng: number; accuracy: number } | null> => {
    return new Promise((resolve) => {
      if (!navigator.geolocation) { setGpsStatus('error'); resolve(null); return; }
      setGpsStatus('acquiring');
      navigator.geolocation.getCurrentPosition(
        (pos) => { setGpsStatus('acquired'); resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }); },
        (err) => { setGpsStatus(err.code === 1 ? 'denied' : 'error'); resolve(null); },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
      );
    });
  };

  const handleClockIn = async () => {
    setClockLoading(true);
    try {
      // Clock in first (don't wait for GPS)
      await timeclockAPI.clockIn();
      await loadClockStatus();
      // Try GPS in background for next time
      acquireGPS().catch(() => {});
    } catch (err: any) {
      console.error('Clock in error:', err);
      const msg = err.response?.data?.detail || err.response?.statusText || err.message || 'Unknown error';
      toast.error(`Clock in failed: ${msg}`);
    }
    finally { setClockLoading(false); }
  };

  const handleClockOut = async () => {
    setClockLoading(true);
    try {
      await timeclockAPI.clockOut();
      await loadClockStatus();
    } catch (err: any) {
      console.error('Clock out error:', err);
      const msg = err.response?.data?.detail || err.response?.statusText || err.message || 'Unknown error';
      toast.error(`Clock out failed: ${msg}`);
    }
    finally { setClockLoading(false); }
  };

  const fmtTime = (iso: string) => {
    if (!iso) return '—';
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

  if (loading) return (
    <div className="min-h-screen">
      <div className="glass sticky top-0 z-50 border-b border-white/20 h-14" />
      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Skeleton greeting */}
        <div className="h-8 w-48 rounded-lg bg-slate-200 animate-pulse mb-6" />
        {/* Skeleton stat cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
          {[1,2,3,4].map(i => (
            <div key={i} className="stat-card animate-pulse">
              <div className="h-5 w-5 rounded bg-slate-200 mb-3" />
              <div className="h-8 w-20 rounded bg-slate-200 mb-2" />
              <div className="h-3 w-24 rounded bg-slate-200" />
            </div>
          ))}
        </div>
        {/* Skeleton content area */}
        <div className="flex flex-col xl:flex-row gap-6">
          <div className="flex-1 space-y-4">
            {[1,2,3].map(i => <div key={i} className="h-16 rounded-xl bg-slate-200 animate-pulse" />)}
          </div>
          <div className="xl:w-[420px] h-64 rounded-xl bg-slate-200 animate-pulse" />
        </div>
      </main>
    </div>
  );
  if (!user) return null;

  const currentRate = tierInfo ? `${(tierInfo.commission_rate * 100).toFixed(0)}%` : '—';
  const currentTier = tierInfo?.current_tier || '—';
  const premiumToNext = tierInfo?.premium_to_next_tier;
  const nextRate = tierInfo?.next_tier ? `${(tierInfo.next_tier.commission_rate * 100).toFixed(0)}%` : null;
  const isAdmin = user.role?.toLowerCase() === 'admin';
  const isFlatRate = tierInfo?.is_flat_rate === true;

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* ── Row 1: Welcome + Clock Widget ── */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-6">
          <div>
            <h1 className="font-display text-3xl font-bold text-slate-900">
              Welcome back, {user.full_name}!
            </h1>
            <p className="text-slate-600">Here's your performance snapshot.</p>
          </div>
          {user.role === 'admin' && (
            <ClockWidget
              status={clockStatus} elapsedTime={elapsedTime} clockLoading={clockLoading}
              gpsStatus={gpsStatus} onClockIn={handleClockIn} onClockOut={handleClockOut} fmtTime={fmtTime}
            />
          )}
        </div>

        {/* ── Row 2: Links & Start a Quote ── */}
        <div className="flex flex-col lg:flex-row gap-3 items-start mb-6">
          {/* Left: Link Dropdowns */}
          <div className="flex flex-wrap gap-2 flex-1">
            <LinkDropdown label="Agency Management" links={[
              { name: 'NowCerts AMS', url: 'https://identity.nowcerts.com/Account/Login?ReturnUrl=%2FAccount%2FLoginRedirectUrl' },
            ]} />
            <LinkDropdown label="Carrier Links" links={[
              { name: 'National General', url: 'https://natgenagency.com/Login.aspx?Menu=Login' },
              { name: 'Progressive', url: 'https://www.foragentsonlylogin.progressive.com/Login/?flowId=dU5FfBvVR0' },
              { name: 'Grange', url: 'https://agentware.grangeagent.com/default.aspx?ReturnUrl=https%3a%2f%2fgainwebpl.grangeagent.com%2fGainweb%2f' },
              { name: 'Travelers', url: 'https://foragents.travelers.com/Personal' },
              { name: 'Safeco', url: 'https://lmidp.libertymutual.com/as/authorization.oauth2?client_id=uscm_oidcsitecoreplprd_1&response_type=code&scope=openid%20profile&code_challenge=STUZEMgIVIs9i18uMUR7UuJnnr8PFI1htDl42cDGcgE&code_challenge_method=S256&state=OpenIdConnect.AuthenticationProperties%3Dxh8KJAfM3kh6NEM11pnHfWNlx4KK_9_IXO8DH3_CH4qM1Um4yK4buJe0octy7QkSde8HOo4rH9ZXdS_t9VOT7Gc6we4KsDtmEukehPfqxYQgFoYAUBvuYqNKNem-GnoPTAvYIoC7iH1g8R5SmBQMAzMP6fYQDEqLInOYpYeBbolpU_rXVVJcwanxhOeI_znW7bJa-1WdFQULHaxOJd8enCLpCwRCMchoyOKfG0uyngDhKdzWcXfJge-atEPDtT3EhqXCAfELrnroaCeX8HvBdlhHsx1r1d_m0RkAj4pN9Rs&response_mode=form_post&nonce=639069622593192597.MDgyZWU5MjAtOTI5MC00NTc2LWJlMWUtMGMzMzM5N2FiYWQxYjU2MjljMTktZWI4ZS00ZTAxLTljNjktYTFjNzg3NGQwMzcw&audience=uscm_oidcsitecoreplprd_1&redirect_uri=https%3A%2F%2Fnow.agent.safeco.com%2Fidentity%2Fexternallogincallback%3FReturnUrl%3D%2Fstart&x-client-SKU=ID_NET461&x-client-ver=5.7.0.0' },
              { name: 'Geico', url: 'https://geicoextendprod.b2clogin.com/geicoextendprod.onmicrosoft.com/B2C_1A_signup_signin/oauth2/v2.0/authorize?response_type=code&client_id=f77f88b1-9ad4-43e9-b813-02ce523bbbb1&redirect_uri=https://ecams.geico.com/federation/oidc/iagent&scope=f77f88b1-9ad4-43e9-b813-02ce523bbbb1&code_challenge=Y4aCCtbcW0HRkpHk-xClVavcZ8hoIV2oWKih4U_nsyI&code_challenge_method=S256&state=qx5cjs5lb05ovglw8x6ioiehca9kls5&relayState=https%3A%2F%2Fgateway.geico.com%2FDashboard' },
              { name: 'Openly', url: 'https://auth.openly.com/u/login/identifier?state=hKFo2SBtVjNwREdYUmlSR2x0dDdzclNHVzVUdTVXVnQ5QmltaaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIDRRemFRemZxV25WdWctS1lfVmtxeldmWnp6VTBWWUh3o2NpZNkgRVFsQU0xTlZoUzVwSWxmOGxsaXloaENMbW1TVDJnU3M' },
              { name: 'Universal', url: 'https://atlasbridge.com/' },
              { name: 'Branch', url: 'https://staff.ourbranch.com/signin' },
              { name: 'American Modern', url: 'https://login.amig.com/byoid.onmicrosoft.com/b2c_1a_prd_amigaggwsignin/oauth2/v2.0/authorize?client_id=263304b5-b180-4605-b4ff-dd98478d4a6e&scope=openid%20profile%20offline_access&redirect_uri=https%3A%2F%2Famsuiteplus.amig.com&client-request-id=7758d9ca-66f0-40fa-b304-35ff7c013baa&response_mode=fragment&response_type=code&x-client-SKU=msal.js.browser&x-client-VER=3.6.0&client_info=1&code_challenge=mnwvErqoGZ5jioFlpswrI6otorWFHwWCJfPO3vRPfUY&code_challenge_method=S256&nonce=2007027b-82cb-4bdc-bc75-7150927efa86&state=eyJpZCI6IjBlNTE2OTY5LWNlMTMtNGZhYi04MDljLTcwMjA2M2E2MDgyYSIsIm1ldGEiOnsiaW50ZXJhY3Rpb25UeXBlIjoicmVkaXJlY3QifX0%3D' },
              { name: 'Homeowners of America', url: 'https://portal.hoaic.com/agent/landing' },
              { name: 'Clearcover', url: 'https://auth.clearcover.com/u/login/identifier?state=hKFo2SBKeHVIM2tmVGExQ1JmXzkxRGlUQ2hRbnBzVG5QczR6caFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIE90WWRJR3V0UkZ0eHpmM1FuUGpVcW05ck50dERMeHNXo2NpZNkgN3RUT3poWG9DSjREZnN0TDZuWmFxTGpGWFBXWTRQbGM' },
              { name: 'Bristol West', url: 'https://bwlogin.iaproducers.com/oauth2/aus8pd5v02vExnL19697/v1/authorize?client_id=0oa8plkp8jLrucllj697&response_type=code&scope=offline_access%20openid&redirect_uri=https://www.iaproducers.com/Producers/FMLogIn.aspx&state=AuthCodeRedirectUrl' },
              { name: 'Next Insurance', url: 'https://agents.nextinsurance.com/authentication' },
              { name: 'Foremost', url: 'https://www.foremoststar.com/nssWeb/pages/login/nssPreLogin.jsp' },
              { name: 'Gainsco', url: 'https://sso.gainsco.com/login?state=hKFo2SA4YlhzMDBwWG5jcXFnM3o0WXppQkNzRkZfYmZrZm0wbaFupWxvZ2luo3RpZNkgcFBfTzh2YVppZWk5bHFMaVZJYzA0b2hRMTBoNk14ZEejY2lk2SBNOWt4ZkU4NnBaeFJpNTRmSTdqckwzNldoS1ZkbmdHVw&client=M9kxfE86pZxRi54fI7jrL36WhKVdngGW&protocol=oauth2&redirect_uri=https%3A%2F%2Fportal.gainscoconnect.com%2Fcallback&response_mode=form_post&response_type=code%20id_token&scope=openid%20profile%20email&nonce=637955886586256628.MTMwNzgzM2ItZGQxYy00OWVlLWEzMzYtZjZmMWYzZDFiMDMyMDVjZDZmNDgtOGEyMS00NTUyLWI2ZWUtYmU5NjY0NzYwYTY1&x-client-SKU=ID_NET461&x-client-ver=5.3.0.0' },
              { name: 'Lemonade', url: 'https://www.lemonade.com/agents-login#email' },
              { name: 'Texas Fair Plan', url: 'https://producer.twia.org/producer/tfpa' },
              { name: 'Illinois Fair Plan', url: 'https://ifpa.onaipso.com/' },
            ]} />
            <LinkDropdown label="Lead Sources" links={[
              { name: 'Insurance AI', url: 'https://www.portal.insuranceagents.ai/login' },
              { name: 'QuoteWizard', url: 'https://qwexternalidp.b2clogin.com/qwexternalidp.onmicrosoft.com/b2c_1_everest_sign_in_v2/oauth2/v2.0/authorize?response_type=id_token&scope=https%3A%2F%2Fqwexternalidp.onmicrosoft.com%2Fclient-prod%2Fuser_impersonation%20https%3A%2F%2Fqwexternalidp.onmicrosoft.com%2Fclient-prod%2Foffline_access%20openid%20profile&client_id=6025511d-4d41-4e09-9957-48907e15645c&redirect_uri=https%3A%2F%2Fadmin.quotewizard.com%2Fcallback.html&state=eyJpZCI6ImVkNGVlODE3LWEyNzMtNDU2YS04YmQ5LTM3ZDQwOTYwMGY4OSIsInRzIjoxNzcxMzY1OTEzLCJtZXRob2QiOiJyZWRpcmVjdEludGVyYWN0aW9uIn0%3D&nonce=80404bd1-5303-4990-8df7-c0aaae709bd1&client_info=1&x-client-SKU=MSAL.JS&x-client-Ver=1.4.11&client-request-id=405e6889-a00e-4a1e-8681-416f3b52df8f&response_mode=fragment' },
            ]} />
            <LinkDropdown label="Useful Sites" links={[
              { name: 'Zillow', url: 'https://www.zillow.com' },
            ]} />
          </div>

          {/* Right: Start a Quote — prominent */}
          <a
            href="https://app.quotamation.com/login"
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 inline-flex items-center space-x-2 bg-green-600 hover:bg-green-700 text-white font-bold px-6 py-3 rounded-xl text-base transition-all shadow-lg hover:shadow-xl start-quote-btn"
          >
            <FileText size={20} />
            <span>Start a Quote</span>
            <ExternalLink size={14} className="opacity-70" />
          </a>
        </div>

        {/* ── Row 3: Stats + Tier Card ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
          <StatCard title="Sales MTD" value={stats?.totalSales || 0} icon={<FileText className="text-brand-600" size={20} />} />
          <StatCard title="Written Premium MTD" value={`$${(stats?.totalPremium || 0).toLocaleString()}`} icon={<DollarSign className="text-green-600" size={20} />} />
          <StatCard title="Active Policies" value={stats?.activePolicies || 0} icon={<TrendingUp className="text-blue-600" size={20} />} />
          {/* Commission Tier inline as 4th stat */}
          <div className="stat-card bg-gradient-to-br from-brand-600 to-brand-700 text-white relative overflow-hidden">
            <div className="flex items-start justify-between mb-2">
              <div className="p-2 rounded-lg bg-white/10"><Award size={20} /></div>
            </div>
            <div className="text-3xl font-bold mb-0.5">{isFlatRate ? '3%' : `Tier ${currentTier}`}</div>
            <div className="text-sm font-semibold text-blue-100">{isFlatRate ? 'Flat Rate' : currentRate === '0%' ? 'No commission yet' : `${currentRate} commission`}</div>
            {!isFlatRate && premiumToNext && premiumToNext > 0 && nextRate && (
              <p className="text-xs text-blue-200 mt-1">${Number(premiumToNext).toLocaleString()} to {nextRate}</p>
            )}
            {!isFlatRate && !premiumToNext && tierInfo?.current_tier === 7 && (
              <p className="text-xs text-blue-200 mt-1">Top tier!</p>
            )}
          </div>
        </div>

        {/* ── Smart Inbox Quick View (Manager/Admin only) ── */}
        {isManager && inboxStats && (
          <div className="mb-6">
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-cyan-50"><Inbox size={18} className="text-cyan-600" /></div>
                  <h3 className="text-sm font-semibold text-slate-700">Smart Inbox</h3>
                  {inboxStats.pending_approvals > 0 && (
                    <span className="px-2 py-0.5 text-[11px] font-bold rounded-full bg-red-500 text-white animate-pulse">
                      {inboxStats.pending_approvals} awaiting approval
                    </span>
                  )}
                </div>
                <button onClick={() => router.push('/smart-inbox')} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                  Open Inbox →
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="text-center p-2 rounded-lg bg-slate-50">
                  <div className="text-lg font-bold text-slate-900">{inboxStats.today_count || 0}</div>
                  <div className="text-[10px] text-slate-500 font-medium">Today</div>
                </div>
                <div className="text-center p-2 rounded-lg bg-slate-50">
                  <div className="text-lg font-bold text-green-600">{inboxStats.auto_sent || 0}</div>
                  <div className="text-[10px] text-slate-500 font-medium">Auto-Sent</div>
                </div>
                <div className="text-center p-2 rounded-lg bg-slate-50">
                  <div className="text-lg font-bold text-blue-600">{inboxStats.customer_match_rate ? `${Math.round(inboxStats.customer_match_rate)}%` : '—'}</div>
                  <div className="text-[10px] text-slate-500 font-medium">Match Rate</div>
                </div>
                <div className="text-center p-2 rounded-lg bg-slate-50">
                  <div className="text-lg font-bold text-slate-900">{inboxStats.week_count || 0}</div>
                  <div className="text-[10px] text-slate-500 font-medium">This Week</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Daily Non-Pay Checklist (Manager/Admin only) ── */}
        {isManager && checklist && (
          <div className="mb-6">
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-amber-50"><ClipboardList size={18} className="text-amber-600" /></div>
                  <h3 className="text-sm font-semibold text-slate-700">Daily Non-Pay Lists</h3>
                  {checklist.all_done ? (
                    <span className="px-2 py-0.5 text-[11px] font-bold rounded-full bg-green-100 text-green-700">
                      ✓ All Done
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 text-[11px] font-bold rounded-full bg-amber-100 text-amber-700">
                      {checklist.completed}/{checklist.total} complete
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => router.push('/customers?tab=nonpay')}
                    className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-brand-50 text-brand-600 hover:bg-brand-100 transition-all"
                  >
                    Upload & Send
                  </button>
                  <div className="text-[11px] text-slate-400 font-medium">
                    {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                  </div>
                </div>
              </div>
              <div className="space-y-1.5">
                {checklist.items.map((item: any) => (
                  <button
                    key={item.key}
                    onClick={() => toggleChecklistItem(item.key)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                      item.completed
                        ? 'bg-green-50 border border-green-200'
                        : 'bg-slate-50 border border-slate-200 hover:bg-slate-100'
                    }`}
                  >
                    <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-all ${
                      item.completed
                        ? 'border-green-500 bg-green-500'
                        : 'border-slate-300'
                    }`}>
                      {item.completed && <CheckCircle size={14} className="text-white" />}
                    </div>
                    <span className={`text-sm font-medium flex-1 ${
                      item.completed ? 'text-green-700 line-through' : 'text-slate-700'
                    }`}>
                      {item.label}
                    </span>
                    {item.completed && item.completed_at && (
                      <span className="text-[10px] text-green-500 font-medium">
                        {new Date(item.completed_at + (item.completed_at.endsWith('Z') ? '' : 'Z')).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' })}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Two-Column Layout: Main Content + Compliance Center ── */}
        <div className="flex flex-col xl:flex-row gap-6">
          {/* Left: Main Dashboard Content */}
          <div className="flex-1 min-w-0">
            {/* ── Trending & Goals ── */}
            <div className="mb-6">
              <TrendingGoals compact />
            </div>

            {/* ── Recent Sales Ticker ── */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wide">Recent Sales</h3>
                <button onClick={() => router.push('/sales')} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                  View All →
                </button>
              </div>
              <SalesTicker sales={recentSales} />
            </div>
          </div>

          {/* Right: Compliance Center */}
          <div className="xl:w-[420px] flex-shrink-0">
            <ComplianceCenter />
          </div>
        </div>

      </main>
    </div>
  );
}


// ── Clock Widget (compact) ──────────────────────────────────────────

const ClockWidget: React.FC<{
  status: any; elapsedTime: string; clockLoading: boolean;
  gpsStatus: string; onClockIn: () => void; onClockOut: () => void; fmtTime: (s: string) => string;
}> = ({ status, elapsedTime, clockLoading, gpsStatus, onClockIn, onClockOut, fmtTime }) => (
  <div className={`flex-shrink-0 rounded-xl border-2 px-4 py-3 transition-all ${
    status?.status === 'clocked_in' ? 'bg-green-50 border-green-200'
      : status?.status === 'clocked_out' ? 'bg-slate-50 border-slate-200'
      : 'bg-white border-blue-200 shadow-md'
  }`}>
    <div className="flex items-center space-x-3">
      <div className={`p-2 rounded-full ${
        status?.status === 'clocked_in' ? 'bg-green-100' : status?.status === 'clocked_out' ? 'bg-slate-100' : 'bg-blue-100'
      }`}>
        <Clock size={18} className={
          status?.status === 'clocked_in' ? 'text-green-600' : status?.status === 'clocked_out' ? 'text-slate-400' : 'text-blue-600'
        } />
      </div>

      <div className="min-w-0">
        {status?.status === 'clocked_in' ? (
          <>
            <p className="font-bold text-green-800 text-xs leading-tight">Clocked In</p>
            <p className="text-green-700 text-xs">
              {fmtTime(status.clock_in)}
              {status.is_late && <span className="text-amber-600 font-semibold"> · {status.minutes_late}m late</span>}
            </p>
            {elapsedTime && <p className="font-mono font-bold text-green-900 text-sm">{elapsedTime}</p>}
            {status.is_at_office === true && <p className="text-green-600 text-xs flex items-center"><MapPin size={10} className="mr-0.5" />Office</p>}
            {status.is_at_office === false && <p className="text-amber-600 text-xs flex items-center"><MapPin size={10} className="mr-0.5" />Remote</p>}
          </>
        ) : status?.status === 'clocked_out' ? (
          <>
            <p className="font-bold text-slate-600 text-xs">Done</p>
            <p className="text-slate-500 text-xs">{fmtTime(status.clock_in)}–{fmtTime(status.clock_out)} · {status.hours_worked}h</p>
          </>
        ) : (
          <p className="font-bold text-blue-800 text-xs">Not clocked in</p>
        )}
      </div>

      <div className="flex-shrink-0">
        {status?.status === 'clocked_in' ? (
          <button onClick={onClockOut} disabled={clockLoading}
            className="inline-flex items-center space-x-1.5 bg-red-600 hover:bg-red-700 text-white font-bold px-3 py-2 rounded-lg text-sm disabled:opacity-50">
            {clockLoading ? <Loader size={14} className="animate-spin" /> : <LogOut size={14} />}
            <span>Out</span>
          </button>
        ) : status?.status === 'clocked_out' ? (
          <CheckCircle size={24} className="text-green-400" />
        ) : (
          <button onClick={onClockIn} disabled={clockLoading}
            className="inline-flex items-center space-x-1.5 bg-green-600 hover:bg-green-700 text-white font-bold px-3 py-2 rounded-lg text-sm disabled:opacity-50">
            {clockLoading ? <Loader size={14} className="animate-spin" /> : <LogIn size={14} />}
            <span>In</span>
          </button>
        )}
      </div>
    </div>

    {gpsStatus === 'acquiring' && <p className="text-xs text-blue-500 mt-1 flex items-center"><Loader size={10} className="animate-spin mr-1" />GPS...</p>}
    {gpsStatus === 'denied' && <p className="text-xs text-amber-500 mt-1"><AlertTriangle size={10} className="inline mr-1" />No GPS</p>}
  </div>
);


// ── Sales Ticker ────────────────────────────────────────────────────

const SalesTicker: React.FC<{ sales: any[] }> = ({ sales }) => {
  const trackRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [animDuration, setAnimDuration] = useState('60s');

  // Duplicate for seamless loop
  const items = sales.length > 0 ? [...sales, ...sales] : [];

  useEffect(() => {
    // Wait one frame for DOM to measure
    const raf = requestAnimationFrame(() => {
      if (trackRef.current && sales.length > 0) {
        const halfWidth = trackRef.current.scrollWidth / 2;
        const pxPerSec = 55;
        setAnimDuration(`${Math.max(halfWidth / pxPerSec, 12)}s`);
      }
      setReady(true);
    });
    return () => cancelAnimationFrame(raf);
  }, [sales]);

  return (
    <div className="ticker-container relative overflow-hidden rounded-lg border border-slate-200"
      style={{ minHeight: '48px' }}>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes tickerSlide {
          from { transform: translateX(0); }
          to   { transform: translateX(-50%); }
        }
        .ticker-animate {
          display: flex;
          white-space: nowrap;
          will-change: transform;
          animation: tickerSlide var(--ticker-duration, 60s) linear infinite;
        }
        .ticker-animate:hover {
          animation-play-state: paused;
        }
      `}} />

      {sales.length === 0 ? (
        <div className="flex items-center justify-center h-12 text-sm text-slate-500">
          No recent sales yet
        </div>
      ) : (
        <div
          ref={trackRef}
          className="ticker-animate items-center"
          style={{
            '--ticker-duration': animDuration,
            visibility: ready ? 'visible' : 'hidden',
          } as React.CSSProperties}
        >
          {items.map((sale, i) => (
            <div key={`${sale.id}-${i}`}
              className="inline-flex items-center space-x-2 px-4 flex-shrink-0"
              style={{ height: '48px' }}>
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                sale.status === 'active' ? 'bg-green-500' : sale.status === 'pending' ? 'bg-amber-500' : 'bg-red-400'
              }`} />
              <span className="text-sm font-semibold ticker-name">{sale.client_name}</span>
              <span className="text-xs ticker-sep">·</span>
              <span className="text-sm font-bold ticker-amount">${parseFloat(sale.written_premium).toLocaleString()}</span>
              <span className="text-xs ticker-source">{sale.lead_source}</span>
              <span className="text-slate-300 mx-2">|</span>
            </div>
          ))}
        </div>
      )}

      {/* Fade edges */}
      {sales.length > 0 && (
        <>
          <div className="absolute inset-y-0 left-0 w-10 z-10 pointer-events-none ticker-fade-left" />
          <div className="absolute inset-y-0 right-0 w-10 z-10 pointer-events-none ticker-fade-right" />
        </>
      )}
    </div>
  );
};


// ── Stat Card ───────────────────────────────────────────────────────

const StatCard: React.FC<{ title: string; value: string | number; icon: React.ReactNode }> = ({ title, value, icon }) => (
  <div className="stat-card">
    <div className="flex items-start justify-between mb-2">
      <div className="p-1.5 sm:p-2 rounded-lg bg-gradient-to-br from-slate-50 to-slate-100">{icon}</div>
    </div>
    <div className="text-xl sm:text-2xl font-bold text-slate-900 mb-0.5 truncate">{value}</div>
    <div className="text-[11px] sm:text-xs text-slate-600 font-medium">{title}</div>
  </div>
);


// ── Link Dropdown ───────────────────────────────────────────────────

const LinkDropdown: React.FC<{ label: string; links: { name: string; url: string }[] }> = ({ label, links }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center space-x-1.5 px-3 py-2 rounded-lg border border-slate-200 hover:border-brand-400 hover:bg-brand-50 transition-all text-sm link-dropdown-trigger"
      >
        <span className="font-medium text-slate-700 link-dropdown-label">{label}</span>
        <ChevronDown size={14} className={`text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 w-56 rounded-xl shadow-xl border z-[100] overflow-hidden theme-picker-dropdown"
          style={{ maxHeight: '320px', overflowY: 'auto' }}>
          {links.map((link) => (
            <a
              key={link.name}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between px-3 py-2 text-sm transition-colors theme-picker-item"
              onClick={() => setOpen(false)}
            >
              <span className="font-medium theme-picker-name">{link.name}</span>
              <ExternalLink size={12} className="text-slate-400 flex-shrink-0" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
};


// ── Compliance Center ────────────────────────────────────────────────

const CARRIER_DISPLAY_NAMES: Record<string, string> = {
  'integon natl': 'National General',
  'integon natl ins': 'National General',
  'integon national': 'National General',
  'integon': 'National General',
  'ngic': 'National General',
  'nat gen': 'National General',
  'bristol west': 'Bristol West',
};

function normalizeCarrierName(carrier: string | null): string {
  if (!carrier) return '';
  const key = carrier.toLowerCase().trim();
  return CARRIER_DISPLAY_NAMES[key] || carrier;
}

const CARRIER_PORTALS: Record<string, string> = {
  'national_general': 'https://natgenagency.com',
  'nat gen': 'https://natgenagency.com',
  'natgen': 'https://natgenagency.com',
  'ngic': 'https://natgenagency.com',
  'grange': 'https://agentware.grangeagent.com/default.aspx?ReturnUrl=https%3a%2f%2fgainwebpl.grangeagent.com%2fGainweb%2f',
  'grange insurance': 'https://agentware.grangeagent.com/default.aspx?ReturnUrl=https%3a%2f%2fgainwebpl.grangeagent.com%2fGainweb%2f',
  'progressive': 'https://www.foragentsonly.com',
  'safeco': 'https://www.safeco.com/agent',
  'travelers': 'https://foragents.travelers.com/Personal',
  'branch': 'https://www.ourbranch.com',
  'openly': 'https://www.openly.com',
  'hippo': 'https://www.hippo.com',
  'universal_property': 'https://www.universalproperty.com',
  'geico': 'https://www.geico.com',
  'bristol_west': 'https://www.bristolwest.com',
};

function getCarrierPortalUrl(carrier: string | null): string | null {
  if (!carrier) return null;
  const key = carrier.toLowerCase().trim();
  return CARRIER_PORTALS[key] || null;
}

const PRIORITY_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  urgent: { bg: 'bg-red-100', text: 'text-red-700', label: 'URGENT' },
  high:   { bg: 'bg-orange-100', text: 'text-orange-700', label: 'HIGH' },
  medium: { bg: 'bg-blue-100', text: 'text-blue-700', label: 'MEDIUM' },
  low:    { bg: 'bg-slate-100', text: 'text-slate-600', label: 'LOW' },
};

const TYPE_CONFIG: Record<string, { bg: string; text: string; label: string; icon: string }> = {
  uw_requirement: { bg: 'bg-amber-100', text: 'text-amber-700', label: 'UW REQUIREMENT', icon: '📋' },
  non_renewal:    { bg: 'bg-purple-100', text: 'text-purple-700', label: 'NON-RENEWAL', icon: '🔄' },
  undeliverable:  { bg: 'bg-violet-100', text: 'text-violet-700', label: 'UNDELIVERABLE', icon: '📭' },
  inspection:     { bg: 'bg-cyan-100', text: 'text-cyan-700', label: 'INSPECTION', icon: '🔍' },
};

const ComplianceCenter: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role?.toLowerCase() === 'admin';
  const [tasks, setTasks] = useState<any[]>([]);
  const [counts, setCounts] = useState<any>({ open: 0, urgent: 0, my_tasks: 0 });
  const [filter, setFilter] = useState<'all' | 'non_renewal' | 'uw_requirement' | 'undeliverable' | 'inspection'>('all');
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [reassigningId, setReassigningId] = useState<number | null>(null);
  const [sendingTaskId, setSendingTaskId] = useState<number | null>(null);

  // Inspection drafts state
  const [inspectionDrafts, setInspectionDrafts] = useState<any[]>([]);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [expandedDraftId, setExpandedDraftId] = useState<number | null>(null);
  const [editingDraftId, setEditingDraftId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<any>({});
  const [previewDraftId, setPreviewDraftId] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  const loadTasks = async () => {
    try {
      const params: any = { limit: 30 };
      if (filter !== 'all' && filter !== 'inspection') params.task_type = filter;
      const [tasksRes, countsRes] = await Promise.all([
        tasksAPI.list(params),
        tasksAPI.counts(),
      ]);
      setTasks(tasksRes.data || []);
      setCounts(countsRes.data || { open: 0, urgent: 0, my_tasks: 0 });
    } catch (e) { console.error('Compliance load failed:', e); }
    setLoading(false);
  };

  const loadInspectionDrafts = async () => {
    setInspectionLoading(true);
    try {
      const res = await inspectionAPI.listDrafts('pending_review');
      setInspectionDrafts(res.data?.drafts || []);
    } catch (e) { console.error('Inspection drafts load failed:', e); }
    setInspectionLoading(false);
  };

  useEffect(() => { loadTasks(); }, [filter]);
  useEffect(() => { loadInspectionDrafts(); }, []);

  // Load agents for reassign dropdown (admin only)
  useEffect(() => {
    if (isAdmin) {
      adminAPI.listEmployees().then(r => setAgents(r.data || [])).catch(() => {});
    }
  }, [isAdmin]);

  const handleComplete = async (id: number) => {
    try {
      await tasksAPI.update(id, { status: 'completed' });
      loadTasks();
    } catch (e) { console.error('Task update failed:', e); }
  };

  const handleSendTask = async (id: number) => {
    setSendingTaskId(id);
    try {
      const res = await tasksAPI.send(id);
      const d = res.data;
      if (d.success) {
        toast.success(`✅ ${d.method === 'letter' ? 'Letter sent via Thanks.io' : 'Email sent'} successfully!`);
        loadTasks(); // Refresh to show updated last_sent_at
      } else {
        toast.error(`❌ Send failed: ${d.error || 'Unknown error'}`);
      }
    } catch (e: any) {
      toast.error(`❌ Send failed: ${e?.response?.data?.detail || e.message}`);
    }
    setSendingTaskId(null);
  };

  const handleReassign = async (taskId: number, newAgentId: number) => {
    try {
      await tasksAPI.update(taskId, { assigned_to_id: newAgentId });
      setReassigningId(null);
      loadTasks();
    } catch (e) { console.error('Reassign failed:', e); }
  };

  // Inspection actions
  const handleApproveDraft = async (id: number) => {
    setActionLoading(id);
    try {
      await inspectionAPI.approveDraft(id);
      loadInspectionDrafts();
      loadTasks();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Approve failed — check customer email');
    }
    setActionLoading(null);
  };

  const handleRejectDraft = async (id: number) => {
    if (!confirm('Reject this inspection draft? No email will be sent.')) return;
    setActionLoading(id);
    try {
      await inspectionAPI.rejectDraft(id);
      loadInspectionDrafts();
      loadTasks();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Reject failed');
    }
    setActionLoading(null);
  };

  const startEdit = (draft: any) => {
    setEditingDraftId(draft.id);
    setEditForm({
      customer_email: draft.customer_email || '',
      customer_name: draft.customer_name || '',
      action_required: draft.action_required || '',
      deadline: draft.deadline || '',
      severity: draft.severity || 'medium',
    });
  };

  const saveEdit = async (id: number) => {
    setActionLoading(id);
    try {
      await inspectionAPI.updateDraft(id, editForm);
      setEditingDraftId(null);
      loadInspectionDrafts();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Save failed');
    }
    setActionLoading(null);
  };

  const daysUntil = (dateStr: string | null) => {
    if (!dateStr) return null;
    return Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000);
  };

  // Count by type
  const uwCount = tasks.filter(t => t.task_type === 'uw_requirement').length;
  const nrCount = tasks.filter(t => t.task_type === 'non_renewal').length;
  const undCount = tasks.filter(t => t.task_type === 'undeliverable').length;
  const inspCount = inspectionDrafts.length;
  // Inspection tasks whose draft is still pending stay hidden (shown in Inspection Alerts)
  // Inspection tasks with no pending draft (already sent) show for follow-up tracking
  const pendingInspPolicies = new Set(inspectionDrafts?.map(d => d.policy_number));
  const visibleTasks = tasks.filter(t =>
    t.task_type !== 'inspection' || !pendingInspPolicies.has(t.policy_number)
  );
  const nonInspTaskCount = visibleTasks.length;
  const overdueCount = tasks.filter(t => { const d = daysUntil(t.due_date); return d !== null && d < 0; }).length;

  const showInspection = filter === 'all' || filter === 'inspection';

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-slate-800 to-slate-700 px-5 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="p-1.5 rounded-lg bg-white/10">
              <AlertCircle size={18} className="text-white" />
            </div>
            <div>
              <h3 className="text-white font-bold text-sm">Compliance Center</h3>
              <p className="text-slate-300 text-[11px]">UW Requirements • Non-Renewals • Inspections • Notices</p>
            </div>
          </div>
          {(nonInspTaskCount > 0 || inspCount > 0) && (
            <div className="flex items-center space-x-1.5">
              {overdueCount > 0 && (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-500 text-white animate-pulse">
                  {overdueCount} overdue
                </span>
              )}
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-white/20 text-white">
                {nonInspTaskCount + inspCount}
              </span>
            </div>
          )}
        </div>

        {/* Summary pills */}
        {(nonInspTaskCount > 0 || inspCount > 0) && (
          <div className="flex gap-2 mt-3 flex-wrap">
            {uwCount > 0 && (
              <div className="flex items-center space-x-1 px-2 py-1 rounded-lg bg-amber-500/20 text-amber-200 text-[11px] font-semibold">
                <span>📋</span><span>{uwCount} UW</span>
              </div>
            )}
            {nrCount > 0 && (
              <div className="flex items-center space-x-1 px-2 py-1 rounded-lg bg-purple-500/20 text-purple-200 text-[11px] font-semibold">
                <span>🔄</span><span>{nrCount} Non-Renewal</span>
              </div>
            )}
            {inspCount > 0 && (
              <div className="flex items-center space-x-1 px-2 py-1 rounded-lg bg-cyan-500/20 text-cyan-200 text-[11px] font-semibold">
                <span>🔍</span><span>{inspCount} Inspection{inspCount > 1 ? 's' : ''}</span>
              </div>
            )}
            {undCount > 0 && (
              <div className="flex items-center space-x-1 px-2 py-1 rounded-lg bg-violet-500/20 text-violet-200 text-[11px] font-semibold">
                <span>📭</span><span>{undCount} Mail</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="px-4 py-2 border-b border-slate-100 bg-slate-50/50">
        <div className="flex space-x-1 flex-wrap">
          {(['all', 'inspection', 'uw_requirement', 'non_renewal', 'undeliverable'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
                filter === f
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {f === 'all' ? 'All' :
               f === 'inspection' ? `🔍 Inspections${inspCount > 0 ? ` (${inspCount})` : ''}` :
               f === 'uw_requirement' ? 'UW Reqs' :
               f === 'non_renewal' ? 'Non-Renewals' : 'Mail'}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-h-[700px] overflow-y-auto">
        {/* ── Inspection Drafts Section ── */}
        {showInspection && inspCount > 0 && (
          <div>
            {filter === 'all' && (
              <div className="px-4 py-2 bg-cyan-50 border-b border-cyan-100">
                <div className="flex items-center space-x-1.5">
                  <Shield size={13} className="text-cyan-600" />
                  <span className="text-[11px] font-bold text-cyan-700 uppercase tracking-wider">
                    Inspection Alerts — Pending Approval
                  </span>
                </div>
              </div>
            )}

            <div className="divide-y divide-slate-100">
              {inspectionDrafts?.map((draft) => {
                const isExpanded = expandedDraftId === draft.id;
                const isEditing = editingDraftId === draft.id;
                const isActioning = actionLoading === draft.id;
                const sevStyle = draft.severity === 'high'
                  ? { bg: 'bg-red-100', text: 'text-red-700', label: 'HIGH' }
                  : draft.severity === 'low'
                  ? { bg: 'bg-blue-100', text: 'text-blue-700', label: 'LOW' }
                  : { bg: 'bg-orange-100', text: 'text-orange-700', label: 'MEDIUM' };

                return (
                  <div key={`insp-${draft.id}`} className="px-4 py-3 transition-all hover:bg-cyan-50/30">
                    {/* Header row */}
                    <div
                      className="cursor-pointer"
                      onClick={() => { setExpandedDraftId(isExpanded ? null : draft.id); setEditingDraftId(null); }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          {/* Badges */}
                          <div className="flex items-center flex-wrap gap-1.5 mb-1.5">
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-100 text-cyan-700">
                              🔍 INSPECTION
                            </span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${sevStyle.bg} ${sevStyle.text}`}>
                              {sevStyle.label}
                            </span>
                            {!draft.customer_email && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-600">
                                ⚠ NO EMAIL
                              </span>
                            )}
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-yellow-100 text-yellow-700">
                              PENDING REVIEW
                            </span>
                          </div>

                          {/* Title */}
                          <p className="text-[13px] font-semibold text-slate-800 leading-snug">
                            {draft.customer_name || 'Unknown'} — {normalizeCarrierName(draft.carrier)}
                          </p>

                          {/* Meta */}
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400">
                            {getCarrierPortalUrl(draft.carrier) ? (
                              <a href={getCarrierPortalUrl(draft.carrier)!} target="_blank" rel="noopener noreferrer" className="font-mono text-cyan-400 hover:text-cyan-300 hover:underline" onClick={e => e.stopPropagation()}>{draft.policy_number}</a>
                            ) : (
                              <span className="font-mono">{draft.policy_number}</span>
                            )}
                            <span>•</span>
                            <span>Deadline: <strong className={draft.deadline === 'As soon as possible' ? 'text-orange-500' : 'text-red-500'}>{draft.deadline}</strong></span>
                          </div>

                          {/* Action preview */}
                          <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{draft.action_required}</p>
                        </div>

                        {/* Expand chevron */}
                        <ChevronDown size={16} className={`text-slate-400 transition-transform flex-shrink-0 ml-2 ${isExpanded ? 'rotate-180' : ''}`} />
                      </div>
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && !isEditing && (
                      <div className="mt-3 space-y-3">
                        {/* Detail card */}
                        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-2">
                          <div className="grid grid-cols-2 gap-2 text-[11px]">
                            <div><span className="text-slate-400">Customer:</span> <span className="font-semibold text-slate-700">{draft.customer_name}</span></div>
                            <div><span className="text-slate-400">Email:</span> <span className={`font-semibold ${draft.customer_email ? 'text-slate-700' : 'text-red-500'}`}>{draft.customer_email || 'Missing'}</span></div>
                            <div><span className="text-slate-400">Carrier:</span> <span className="font-semibold text-slate-700">{normalizeCarrierName(draft.carrier)}</span></div>
                            <div><span className="text-slate-400">From:</span> <span className="text-slate-600">service@betterchoiceins.com</span></div>
                          </div>

                          <div className="mt-2">
                            <p className="text-[10px] font-bold text-slate-500 uppercase mb-1">Action Required</p>
                            <p className="text-[12px] text-slate-700 leading-relaxed bg-white rounded p-2 border border-slate-100">{draft.action_required}</p>
                          </div>

                          {draft.issues_found && draft.issues_found.length > 0 && (
                            <div className="mt-2">
                              <p className="text-[10px] font-bold text-slate-500 uppercase mb-1">Issues Found</p>
                              <ul className="text-[12px] text-slate-700 space-y-0.5 pl-4">
                                {draft.issues_found?.map((issue: string, i: number) => (
                                  <li key={i} className="list-disc">{issue}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {draft.attachment_info && draft.attachment_info.length > 0 && (
                            <div className="mt-2">
                              <p className="text-[10px] font-bold text-slate-500 uppercase mb-1">Attachments</p>
                              <div className="flex flex-wrap gap-2">
                                {draft.attachment_info?.map((a: any, i: number) => (
                                  <button
                                    key={i}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-red-50 border border-red-200 text-red-700 text-[11px] font-semibold hover:bg-red-100 transition-colors cursor-pointer"
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      try {
                                        const token = localStorage.getItem('token');
                                        const res = await fetch(
                                          `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/inspection/drafts/${draft.id}/attachment/${i}`,
                                          { headers: { 'Authorization': `Bearer ${token}` } }
                                        );
                                        if (!res.ok) throw new Error('Download failed');
                                        const blob = await res.blob();
                                        const url = URL.createObjectURL(blob);
                                        window.open(url, '_blank');
                                      } catch (err) {
                                        console.error('PDF download error:', err);
                                        toast.error('Failed to download PDF');
                                      }
                                    }}
                                  >
                                    📎 {a.filename} <span className="text-red-400 font-normal">({(a.size / 1024).toFixed(0)} KB)</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleApproveDraft(draft.id)}
                            disabled={isActioning}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold text-white transition-colors shadow-sm disabled:opacity-40 disabled:cursor-not-allowed ${
                              draft.customer_email ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-amber-600 hover:bg-amber-700'
                            }`}
                          >
                            {isActioning ? <Loader size={12} className="animate-spin" /> : draft.customer_email ? <Mail size={12} /> : <Send size={12} />}
                            {draft.customer_email ? 'Approve & Send' : 'Approve & Mail Letter'}
                          </button>
                          <button
                            onClick={() => startEdit(draft)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-blue-600 text-white hover:bg-blue-700 transition-colors shadow-sm"
                          >
                            <Edit3 size={12} />
                            Edit Draft
                          </button>
                          <button
                            onClick={() => setPreviewDraftId(previewDraftId === draft.id ? null : draft.id)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-slate-600 text-white hover:bg-slate-700 transition-colors shadow-sm"
                          >
                            <Eye size={12} />
                            {previewDraftId === draft.id ? 'Hide Preview' : 'Preview Email'}
                          </button>
                          <button
                            onClick={() => handleRejectDraft(draft.id)}
                            disabled={isActioning}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-red-100 text-red-700 hover:bg-red-200 transition-colors ml-auto"
                          >
                            <XCircle size={12} />
                            Reject
                          </button>
                        </div>

                        {/* Email preview iframe */}
                        {previewDraftId === draft.id && draft.draft_html && (
                          <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
                            <div className="px-3 py-1.5 bg-slate-100 border-b border-slate-200 text-[10px] font-bold text-slate-500 uppercase">
                              Email Preview — {draft.draft_subject || 'Inspection Follow-Up'}
                            </div>
                            <iframe
                              srcDoc={draft.draft_html}
                              className="w-full border-0"
                              style={{ height: '400px' }}
                              sandbox="allow-same-origin"
                              title="Email Preview"
                            />
                          </div>
                        )}

                        {previewDraftId === draft.id && !draft.draft_html && (
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-center text-sm text-slate-500">
                            Preview not yet generated. Edit and save the draft to generate the email preview.
                          </div>
                        )}
                      </div>
                    )}

                    {/* Edit form */}
                    {isExpanded && isEditing && (
                      <div className="mt-3 rounded-lg bg-blue-50 border border-blue-200 p-3 space-y-3">
                        <p className="text-[11px] font-bold text-blue-700 uppercase">Edit Draft</p>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-[10px] font-bold text-slate-500 uppercase">Customer Name</label>
                            <input
                              value={editForm.customer_name || ''}
                              onChange={(e) => setEditForm({ ...editForm, customer_name: e.target.value })}
                              className="w-full mt-0.5 px-2 py-1.5 border border-slate-200 rounded-lg text-[12px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] font-bold text-slate-500 uppercase">Customer Email</label>
                            <input
                              value={editForm.customer_email || ''}
                              onChange={(e) => setEditForm({ ...editForm, customer_email: e.target.value })}
                              className="w-full mt-0.5 px-2 py-1.5 border border-slate-200 rounded-lg text-[12px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                              placeholder="customer@email.com"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] font-bold text-slate-500 uppercase">Deadline</label>
                            <input
                              value={editForm.deadline || ''}
                              onChange={(e) => setEditForm({ ...editForm, deadline: e.target.value })}
                              className="w-full mt-0.5 px-2 py-1.5 border border-slate-200 rounded-lg text-[12px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                              placeholder="MM/DD/YYYY"
                            />
                          </div>
                          <div>
                            <label className="text-[10px] font-bold text-slate-500 uppercase">Severity</label>
                            <select
                              value={editForm.severity || 'medium'}
                              onChange={(e) => setEditForm({ ...editForm, severity: e.target.value })}
                              className="w-full mt-0.5 px-2 py-1.5 border border-slate-200 rounded-lg text-[12px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                            >
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </div>
                        </div>
                        <div>
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Action Required (customer will see this)</label>
                          <textarea
                            value={editForm.action_required || ''}
                            onChange={(e) => setEditForm({ ...editForm, action_required: e.target.value })}
                            rows={3}
                            className="w-full mt-0.5 px-2 py-1.5 border border-slate-200 rounded-lg text-[12px] bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 leading-relaxed"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => saveEdit(draft.id)}
                            disabled={isActioning}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
                          >
                            {isActioning ? <Loader size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                            Save Changes
                          </button>
                          <button
                            onClick={() => setEditingDraftId(null)}
                            className="px-3 py-1.5 rounded-lg text-[11px] font-bold text-slate-600 hover:bg-slate-100 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {filter === 'all' && visibleTasks.length > 0 && (
              <div className="px-4 py-2 bg-slate-50 border-y border-slate-100">
                <div className="flex items-center space-x-1.5">
                  <ClipboardList size={13} className="text-slate-500" />
                  <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                    Tasks & Compliance Items
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Regular Tasks ── */}
        {filter !== 'inspection' && (
          <>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader size={20} className="animate-spin text-slate-300" />
              </div>
            ) : visibleTasks.length === 0 && inspCount === 0 ? (
              <div className="text-center py-10 px-4">
                <div className="text-3xl mb-2">✅</div>
                <p className="text-sm font-semibold text-slate-600">All clear!</p>
                <p className="text-xs text-slate-400 mt-1">No open compliance items</p>
              </div>
            ) : visibleTasks.length === 0 ? null : (
              <div className="divide-y divide-slate-100">
                {visibleTasks.map((task) => {
                  const pri = PRIORITY_STYLES[task.priority] || PRIORITY_STYLES.medium;
                  const typeConf = TYPE_CONFIG[task.task_type] || { bg: 'bg-slate-100', text: 'text-slate-600', label: task.task_type?.toUpperCase() || 'TASK', icon: '📌' };
                  const days = daysUntil(task.due_date);
                  const isOverdue = days !== null && days < 0;
                  const isUrgent = days !== null && days <= 7;
                  const isExpanded = expandedId === task.id;

                  return (
                    <div
                      key={task.id}
                      className={`px-4 py-3 transition-all cursor-pointer hover:bg-slate-50 ${
                        isOverdue ? 'bg-red-50/40' : isUrgent ? 'bg-orange-50/30' : ''
                      }`}
                      onClick={() => setExpandedId(isExpanded ? null : task.id)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          {/* Type + Priority + Due */}
                          <div className="flex items-center flex-wrap gap-1.5 mb-1.5">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${typeConf.bg} ${typeConf.text}`}>
                              {typeConf.icon} {typeConf.label}
                            </span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${pri.bg} ${pri.text}`}>
                              {pri.label}
                            </span>
                            {days !== null && (
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                isOverdue ? 'bg-red-600 text-white' :
                                isUrgent ? 'bg-orange-500 text-white' :
                                'bg-slate-100 text-slate-600'
                              }`}>
                                {isOverdue ? `${Math.abs(days)}d OVERDUE` :
                                 days === 0 ? 'DUE TODAY' :
                                 `${days}d left`}
                              </span>
                            )}
                          </div>

                          {/* Title */}
                          <p className="text-[13px] font-semibold text-slate-800 leading-snug">{task.title}</p>

                          {/* Meta */}
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400">
                            {task.policy_number && (
                              getCarrierPortalUrl(task.carrier) ? (
                                <a href={getCarrierPortalUrl(task.carrier)!} target="_blank" rel="noopener noreferrer" className="font-mono text-cyan-400 hover:text-cyan-300 hover:underline" onClick={e => e.stopPropagation()}>{task.policy_number}</a>
                              ) : (
                                <span className="font-mono">{task.policy_number}</span>
                              )
                            )}
                            {task.carrier && <span>• {normalizeCarrierName(task.carrier)}</span>}
                          </div>

                          {/* Producer / Assigned To */}
                          <div className="flex items-center gap-1.5 mt-1.5">
                            <UserCheck size={10} className="text-slate-400" />
                            {isAdmin && reassigningId === task.id ? (
                              <select
                                className="text-[11px] border border-slate-200 rounded px-1.5 py-0.5 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-brand-500"
                                value={task.assigned_to_id || ''}
                                onChange={(e) => handleReassign(task.id, parseInt(e.target.value))}
                                onBlur={() => setReassigningId(null)}
                                autoFocus
                              >
                                <option value="">Unassigned</option>
                                {agents.map((a: any) => (
                                  <option key={a.id} value={a.id}>{a.full_name || a.username}</option>
                                ))}
                              </select>
                            ) : (
                              <span
                                className={`text-[11px] font-medium ${isAdmin ? 'text-brand-600 cursor-pointer hover:underline' : 'text-slate-500'}`}
                                onClick={(e) => { if (isAdmin) { e.stopPropagation(); setReassigningId(task.id); } }}
                                title={isAdmin ? 'Click to reassign' : ''}
                              >
                                {task.assigned_to_name || 'Unassigned'}
                              </span>
                            )}
                          </div>

                          {/* Expanded details */}
                          {isExpanded && task.description && (
                            <div className="mt-2 p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                              <p className="text-xs text-slate-600 whitespace-pre-line leading-relaxed">{task.description}</p>
                            </div>
                          )}
                        </div>

                        {/* Action buttons */}
                        <div className="flex flex-col items-center gap-1.5 ml-2 flex-shrink-0">
                          {/* Send button */}
                          <button
                            onClick={(e) => { e.stopPropagation(); handleSendTask(task.id); }}
                            disabled={sendingTaskId === task.id}
                            className={`p-1.5 rounded-lg transition-colors ${
                              sendingTaskId === task.id
                                ? 'bg-blue-100 text-blue-400 animate-pulse'
                                : task.customer_email
                                ? 'hover:bg-blue-100 text-slate-300 hover:text-blue-600'
                                : 'hover:bg-amber-100 text-slate-300 hover:text-amber-600'
                            }`}
                            title={task.customer_email ? `Send email to ${task.customer_email}` : 'Send letter (no email on file)'}
                          >
                            {sendingTaskId === task.id ? (
                              <Loader size={14} className="animate-spin" />
                            ) : task.customer_email ? (
                              <Send size={14} />
                            ) : (
                              <Mail size={14} />
                            )}
                          </button>
                          {/* Complete button */}
                          <button
                            onClick={(e) => { e.stopPropagation(); handleComplete(task.id); }}
                            className="p-1.5 rounded-lg hover:bg-green-100 text-slate-300 hover:text-green-600 transition-colors"
                            title="Mark complete"
                          >
                            <CheckCircle size={14} />
                          </button>
                          {/* Last sent indicator */}
                          {task.last_sent_at && (
                            <span className="text-[9px] text-slate-400 text-center leading-tight" title={`Sent ${task.send_count || 1}x via ${task.last_send_method || 'email'}`}>
                              {task.last_send_method === 'letter' ? '📬' : '📧'} {new Date(task.last_sent_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* Empty state for inspection tab */}
        {filter === 'inspection' && inspCount === 0 && !inspectionLoading && (
          <div className="text-center py-10 px-4">
            <div className="text-3xl mb-2">🔍</div>
            <p className="text-sm font-semibold text-slate-600">No pending inspection alerts</p>
            <p className="text-xs text-slate-400 mt-1">Inspection emails will appear here for review</p>
          </div>
        )}
      </div>
    </div>
  );
};
