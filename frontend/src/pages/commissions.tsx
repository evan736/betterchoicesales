import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { commissionsAPI } from '../lib/api';
import { DollarSign, TrendingUp, Award, Calendar } from 'lucide-react';

export default function Commissions() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [commissions, setCommissions] = useState<any[]>([]);
  const [tiers, setTiers] = useState<any[]>([]);
  const [tierInfo, setTierInfo] = useState<any>(null);
  const [selectedPeriod, setSelectedPeriod] = useState('');
  const [loadingData, setLoadingData] = useState(true);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/');
    } else if (user) {
      loadData();
    }
  }, [user, loading]);

  const loadData = async () => {
    try {
      const [commissionsRes, tiersRes, tierInfoRes] = await Promise.all([
        commissionsAPI.myCommissions(),
        commissionsAPI.tiers(),
        commissionsAPI.myTier(),
      ]);
      setCommissions(commissionsRes.data);
      setTiers(tiersRes.data);
      setTierInfo(tierInfoRes.data);
    } catch (error) {
      console.error('Failed to load commissions:', error);
    } finally {
      setLoadingData(false);
    }
  };

  if (loading || !user) return null;

  const totalCommission = commissions.reduce(
    (sum, c) => sum + parseFloat(c.commission_amount),
    0
  );

  const currentPeriod = new Date().toISOString().slice(0, 7); // YYYY-MM
  const currentMonthCommissions = commissions.filter((c) => c.period === currentPeriod);
  const currentMonthTotal = currentMonthCommissions.reduce(
    (sum, c) => sum + parseFloat(c.commission_amount),
    0
  );

  const currentTierLevel = tierInfo?.current_tier || 1;
  const currentRate = tierInfo ? `${(tierInfo.commission_rate * 100).toFixed(0)}%` : '—';

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">
            Commission Tracking
          </h1>
          <p className="text-slate-600">View your earnings and commission tiers</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="stat-card bg-gradient-to-br from-brand-600 to-brand-700 text-white">
            <div className="flex items-center justify-between mb-4">
              <Award size={32} />
              <div className="text-3xl font-bold">Tier {currentTierLevel}</div>
            </div>
            <div className="text-blue-100">Current Tier — {currentRate} commission</div>
          </div>

          <div className="stat-card">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-3 rounded-lg bg-green-100">
                <DollarSign className="text-green-600" size={24} />
              </div>
              <div>
                <div className="text-3xl font-bold text-slate-900">
                  ${currentMonthTotal.toLocaleString()}
                </div>
                <div className="text-slate-600 text-sm">This Month</div>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-3 rounded-lg bg-blue-100">
                <TrendingUp className="text-blue-600" size={24} />
              </div>
              <div>
                <div className="text-3xl font-bold text-slate-900">
                  ${totalCommission.toLocaleString()}
                </div>
                <div className="text-slate-600 text-sm">Total Earned</div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Commission History */}
          <div className="lg:col-span-2">
            <div className="card">
              <h2 className="font-display text-2xl font-bold text-slate-900 mb-6">
                Commission History
              </h2>

              {loadingData ? (
                <div className="text-center py-12 text-slate-500">Loading...</div>
              ) : commissions.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <DollarSign size={48} className="mx-auto mb-4 opacity-50" />
                  <p>No commissions yet</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {commissions.slice(0, 10).map((commission) => (
                    <CommissionCard key={commission.id} commission={commission} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Commission Tiers */}
          <div>
            <div className="card">
              <h3 className="font-display text-xl font-bold text-slate-900 mb-6">
                Commission Tiers
              </h3>

              <div className="space-y-4">
                {tiers.map((tier) => (
                  <TierCard
                    key={tier.id}
                    tier={tier}
                    isCurrentTier={tier.tier_level === currentTierLevel}
                  />
                ))}
              </div>

              <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
                <p className="text-sm text-blue-900">
                  <strong>Note:</strong> Tiers are based on monthly written premium. Commission
                  is paid on recognized premium.
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

const CommissionCard: React.FC<{ commission: any }> = ({ commission }) => (
  <div className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:border-brand-300 hover:bg-brand-50/50 transition-all">
    <div className="flex-1">
      <div className="flex items-center space-x-3 mb-2">
        <Calendar size={16} className="text-slate-500" />
        <span className="font-semibold text-slate-900">Period: {commission.period}</span>
        <span
          className={`badge ${
            commission.status === 'paid'
              ? 'badge-success'
              : commission.status === 'calculated'
              ? 'badge-info'
              : 'badge-warning'
          }`}
        >
          {commission.status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-slate-600">Written: </span>
          <span className="font-semibold">
            ${parseFloat(commission.written_premium).toLocaleString()}
          </span>
        </div>
        <div>
          <span className="text-slate-600">Tier: </span>
          <span className="font-semibold">{commission.tier_level}</span>
        </div>
      </div>
    </div>
    <div className="text-right ml-6">
      <div className="text-2xl font-bold text-brand-600">
        ${parseFloat(commission.commission_amount).toLocaleString()}
      </div>
      <div className="text-xs text-slate-500">
        {(parseFloat(commission.commission_rate) * 100).toFixed(1)}% rate
      </div>
    </div>
  </div>
);

const TierCard: React.FC<{ tier: any; isCurrentTier: boolean }> = ({ tier, isCurrentTier }) => (
  <div
    className={`p-4 rounded-lg border-2 ${
      isCurrentTier
        ? 'border-brand-500 bg-brand-50'
        : 'border-slate-200 bg-white hover:border-brand-300'
    } transition-all`}
  >
    <div className="flex items-center justify-between mb-2">
      <div className="font-bold text-lg text-slate-900">Tier {tier.tier_level}</div>
      {isCurrentTier && (
        <span className="badge badge-info">
          <Award size={12} /> Current
        </span>
      )}
    </div>
    <div className="text-sm text-slate-600 mb-2">
      ${parseFloat(tier.min_written_premium).toLocaleString()}
      {tier.max_written_premium
        ? ` - $${parseFloat(tier.max_written_premium).toLocaleString()}`
        : '+'}{' '}
      written
    </div>
    <div className="text-2xl font-bold text-brand-600">
      {(parseFloat(tier.commission_rate) * 100).toFixed(1)}%
    </div>
    {tier.description && <p className="text-xs text-slate-500 mt-2">{tier.description}</p>}
  </div>
);
