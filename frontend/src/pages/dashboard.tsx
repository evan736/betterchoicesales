import React, { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import TrendingGoals from '../components/TrendingGoals';
import { salesAPI, commissionsAPI, timeclockAPI } from '../lib/api';
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
} from 'lucide-react';

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

  useEffect(() => {
    if (!loading && !user) router.push('/');
    else if (user) { loadDashboardData(); loadClockStatus(); }
  }, [user, loading]);

  const loadDashboardData = async () => {
    // Load independently so one failure doesn't kill the others
    try {
      const salesRes = await salesAPI.list();
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
      alert(`Clock in failed: ${msg}`);
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
      alert(`Clock out failed: ${msg}`);
    }
    finally { setClockLoading(false); }
  };

  const fmtTime = (iso: string) => {
    if (!iso) return '—';
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center"><div className="animate-pulse text-brand-600 font-semibold">Loading...</div></div>;
  if (!user) return null;

  const currentRate = tierInfo ? `${(tierInfo.commission_rate * 100).toFixed(0)}%` : '—';
  const currentTier = tierInfo?.current_tier || '—';
  const premiumToNext = tierInfo?.premium_to_next_tier;
  const nextRate = tierInfo?.next_tier ? `${(tierInfo.next_tier.commission_rate * 100).toFixed(0)}%` : null;
  const isAdmin = user.role?.toLowerCase() === 'admin';

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* ── Row 1: Welcome + Clock Widget ── */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-6">
          <div>
            <h1 className="font-display text-3xl font-bold text-slate-900">
              Welcome back, {user.full_name}!
            </h1>
            <p className="text-slate-600">Here's your performance snapshot.</p>
          </div>
          <ClockWidget
            status={clockStatus} elapsedTime={elapsedTime} clockLoading={clockLoading}
            gpsStatus={gpsStatus} onClockIn={handleClockIn} onClockOut={handleClockOut} fmtTime={fmtTime}
          />
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
              { name: 'Travelers', url: 'https://signin.travelers.com/#/' },
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
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-6">
          <StatCard title="Total Sales" value={stats?.totalSales || 0} icon={<FileText className="text-brand-600" size={20} />} />
          <StatCard title="Written Premium" value={`$${(stats?.totalPremium || 0).toLocaleString()}`} icon={<DollarSign className="text-green-600" size={20} />} />
          <StatCard title="Active Policies" value={stats?.activePolicies || 0} icon={<TrendingUp className="text-blue-600" size={20} />} />
          {/* Commission Tier inline as 4th stat */}
          <div className="stat-card bg-gradient-to-br from-brand-600 to-brand-700 text-white relative overflow-hidden">
            <div className="flex items-start justify-between mb-2">
              <div className="p-2 rounded-lg bg-white/10"><Award size={20} /></div>
            </div>
            <div className="text-3xl font-bold mb-0.5">Tier {currentTier}</div>
            <div className="text-sm font-semibold text-blue-100">{currentRate} commission</div>
            {premiumToNext && premiumToNext > 0 && nextRate && (
              <p className="text-xs text-blue-200 mt-1">${Number(premiumToNext).toLocaleString()} to {nextRate}</p>
            )}
            {!premiumToNext && tierInfo?.current_tier === 7 && (
              <p className="text-xs text-blue-200 mt-1">Top tier!</p>
            )}
          </div>
        </div>

        {/* ── Row 3: Trending & Goals (full width) ── */}
        <div className="mb-6">
          <TrendingGoals compact />
        </div>

        {/* ── Row 4: Recent Sales Ticker ── */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wide">Recent Sales</h3>
            <button onClick={() => router.push('/sales')} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
              View All →
            </button>
          </div>
          <SalesTicker sales={recentSales} />
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
      <div className="p-2 rounded-lg bg-gradient-to-br from-slate-50 to-slate-100">{icon}</div>
    </div>
    <div className="text-2xl font-bold text-slate-900 mb-0.5">{value}</div>
    <div className="text-xs text-slate-600 font-medium">{title}</div>
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
