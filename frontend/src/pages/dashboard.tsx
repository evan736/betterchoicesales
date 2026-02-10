import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import TrendingGoals from '../components/TrendingGoals';
import { salesAPI, commissionsAPI } from '../lib/api';
import {
  DollarSign,
  TrendingUp,
  FileText,
  Users,
  Calendar,
  Award,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';

export default function Dashboard() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [recentSales, setRecentSales] = useState<any[]>([]);
  const [tierInfo, setTierInfo] = useState<any>(null);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/');
    } else if (user) {
      loadDashboardData();
    }
  }, [user, loading]);

  const loadDashboardData = async () => {
    try {
      const [salesRes, commissionsRes, tierRes] = await Promise.all([
        salesAPI.list(),
        commissionsAPI.myCommissions(),
        commissionsAPI.myTier(),
      ]);

      const sales = salesRes.data;
      setRecentSales(sales.slice(0, 5));
      setTierInfo(tierRes.data);

      // Calculate stats
      const totalPremium = sales.reduce((sum: number, s: any) => sum + parseFloat(s.written_premium), 0);
      const totalCommission = commissionsRes.data.reduce(
        (sum: number, c: any) => sum + parseFloat(c.commission_amount),
        0
      );

      setStats({
        totalSales: sales.length,
        totalPremium,
        totalCommission,
        activePolicies: sales.filter((s: any) => s.status === 'active').length,
      });
    } catch (error) {
      console.error('Failed to load dashboard data:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse text-brand-600 font-semibold">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  const currentRate = tierInfo ? `${(tierInfo.commission_rate * 100).toFixed(0)}%` : '—';
  const currentTier = tierInfo?.current_tier || '—';
  const premiumToNext = tierInfo?.premium_to_next_tier;
  const nextRate = tierInfo?.next_tier ? `${(tierInfo.next_tier.commission_rate * 100).toFixed(0)}%` : null;

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Welcome Section */}
        <div className="mb-8 animate-fade-in">
          <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">
            Welcome back, {user.full_name}! 👋
          </h1>
          <p className="text-slate-600 text-lg">Here's what's happening with your sales today.</p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard
            title="Total Sales"
            value={stats?.totalSales || 0}
            icon={<FileText className="text-brand-600" size={24} />}
          />
          <StatCard
            title="Written Premium"
            value={`$${(stats?.totalPremium || 0).toLocaleString()}`}
            icon={<DollarSign className="text-green-600" size={24} />}
          />
          <StatCard
            title="Commission Rate"
            value={currentRate}
            icon={<Award className="text-accent-500" size={24} />}
          />
          <StatCard
            title="Active Policies"
            value={stats?.activePolicies || 0}
            icon={<TrendingUp className="text-blue-600" size={24} />}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Recent Sales */}
          <div className="lg:col-span-2">
            <div className="card">
              <div className="flex items-center justify-between mb-6">
                <h2 className="font-display text-2xl font-bold text-slate-900">Recent Sales</h2>
                <button
                  onClick={() => router.push('/sales')}
                  className="text-brand-600 hover:text-brand-700 font-semibold text-sm"
                >
                  View All →
                </button>
              </div>

              <div className="space-y-4">
                {recentSales.length === 0 ? (
                  <div className="text-center py-12 text-slate-500">
                    <FileText size={48} className="mx-auto mb-4 opacity-50" />
                    <p>No sales yet. Create your first sale!</p>
                    <button
                      onClick={() => router.push('/sales')}
                      className="btn-primary mt-4"
                    >
                      Create Sale
                    </button>
                  </div>
                ) : (
                  recentSales.map((sale) => (
                    <SaleCard key={sale.id} sale={sale} />
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Quick Actions + Trending + Tier */}
          <div className="space-y-6">
            <div className="card">
              <h3 className="font-display text-xl font-bold text-slate-900 mb-4">
                Quick Actions
              </h3>
              <div className="space-y-3">
                <QuickActionButton
                  onClick={() => router.push('/sales')}
                  icon={<FileText size={20} />}
                  text="New Sale"
                />
                <QuickActionButton
                  onClick={() => router.push('/commissions')}
                  icon={<DollarSign size={20} />}
                  text="View Commissions"
                />
                {user.role?.toLowerCase() === 'admin' && (
                  <QuickActionButton
                    onClick={() => router.push('/statements')}
                    icon={<TrendingUp size={20} />}
                    text="Import Statement"
                  />
                )}
              </div>
            </div>

            {/* Trending Data & Goals */}
            <TrendingGoals compact />

            {/* Commission Tier - Dynamic */}
            <div className="card bg-gradient-to-br from-brand-600 to-brand-700 text-white">
              <h3 className="font-display text-lg font-bold mb-2">Your Commission Tier</h3>
              <div className="text-4xl font-bold mb-1">Tier {currentTier}</div>
              <div className="text-2xl font-semibold text-blue-100 mb-3">{currentRate} commission</div>
              <div className="text-blue-100 text-sm mb-2">
                Monthly premium: ${tierInfo ? Number(tierInfo.total_written_premium).toLocaleString() : '0'}
              </div>
              {premiumToNext && premiumToNext > 0 && nextRate && (
                <div className="mt-3 pt-3 border-t border-blue-400/30">
                  <p className="text-blue-100 text-sm">
                    📈 ${Number(premiumToNext).toLocaleString()} more to reach {nextRate} commission
                  </p>
                </div>
              )}
              {!premiumToNext && tierInfo?.current_tier === 7 && (
                <div className="mt-3 pt-3 border-t border-blue-400/30">
                  <p className="text-blue-100 text-sm">🏆 You're at the top tier!</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

const StatCard: React.FC<{
  title: string;
  value: string | number;
  icon: React.ReactNode;
}> = ({ title, value, icon }) => (
  <div className="stat-card">
    <div className="flex items-start justify-between mb-4">
      <div className="p-3 rounded-lg bg-gradient-to-br from-slate-50 to-slate-100">{icon}</div>
    </div>
    <div className="text-3xl font-bold text-slate-900 mb-1">{value}</div>
    <div className="text-sm text-slate-600 font-medium">{title}</div>
  </div>
);

const SaleCard: React.FC<{ sale: any }> = ({ sale }) => (
  <div className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:border-brand-300 hover:bg-brand-50/50 transition-all">
    <div className="flex-1">
      <div className="flex items-center space-x-3 mb-1">
        <h4 className="font-semibold text-slate-900">{sale.client_name}</h4>
        <span
          className={`badge ${
            sale.status === 'active'
              ? 'badge-success'
              : sale.status === 'pending'
              ? 'badge-warning'
              : 'badge-danger'
          }`}
        >
          {sale.status}
        </span>
      </div>
      <p className="text-sm text-slate-600">Policy: {sale.policy_number}</p>
    </div>
    <div className="text-right">
      <div className="text-lg font-bold text-brand-600">
        ${parseFloat(sale.written_premium).toLocaleString()}
      </div>
      <div className="text-xs text-slate-500">{sale.lead_source}</div>
    </div>
  </div>
);

const QuickActionButton: React.FC<{
  onClick: () => void;
  icon: React.ReactNode;
  text: string;
}> = ({ onClick, icon, text }) => (
  <button
    onClick={onClick}
    className="w-full flex items-center space-x-3 p-4 rounded-lg border-2 border-slate-200 hover:border-brand-400 hover:bg-brand-50 transition-all group"
  >
    <div className="p-2 rounded-lg bg-brand-100 text-brand-600 group-hover:bg-brand-600 group-hover:text-white transition-all">
      {icon}
    </div>
    <span className="font-semibold text-slate-700 group-hover:text-brand-700">{text}</span>
  </button>
);
