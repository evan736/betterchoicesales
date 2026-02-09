import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { salesAPI } from '../lib/api';
import { Plus, FileText, Upload, X, Check } from 'lucide-react';

export default function Sales() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sales, setSales] = useState<any[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [loadingSales, setLoadingSales] = useState(true);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/');
    } else if (user) {
      loadSales();
    }
  }, [user, loading]);

  const loadSales = async () => {
    try {
      const response = await salesAPI.list();
      setSales(response.data);
    } catch (error) {
      console.error('Failed to load sales:', error);
    } finally {
      setLoadingSales(false);
    }
  };

  if (loading || !user) return null;

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">Sales</h1>
            <p className="text-slate-600">Manage your policy sales and applications</p>
          </div>
          <button onClick={() => setShowCreateModal(true)} className="btn-primary flex items-center space-x-2">
            <Plus size={20} />
            <span>New Sale</span>
          </button>
        </div>

        {/* Sales List */}
        {loadingSales ? (
          <div className="text-center py-12">
            <div className="animate-pulse text-brand-600 font-semibold">Loading sales...</div>
          </div>
        ) : sales.length === 0 ? (
          <div className="card text-center py-12">
            <FileText size={64} className="mx-auto mb-4 text-slate-300" />
            <h3 className="font-display text-2xl font-bold text-slate-900 mb-2">
              No sales yet
            </h3>
            <p className="text-slate-600 mb-6">Get started by creating your first sale</p>
            <button onClick={() => setShowCreateModal(true)} className="btn-primary">
              Create Your First Sale
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {sales.map((sale) => (
              <SaleListItem key={sale.id} sale={sale} onUpdate={loadSales} />
            ))}
          </div>
        )}

        {/* Create Sale Modal */}
        {showCreateModal && (
          <CreateSaleModal
            onClose={() => setShowCreateModal(false)}
            onSuccess={() => {
              setShowCreateModal(false);
              loadSales();
            }}
          />
        )}
      </main>
    </div>
  );
}

const SaleListItem: React.FC<{ sale: any; onUpdate: () => void }> = ({ sale, onUpdate }) => {
  const [uploading, setUploading] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      await salesAPI.uploadPDF(sale.id, file);
      onUpdate();
    } catch (error) {
      console.error('Upload failed:', error);
      alert('Failed to upload file');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="card hover:shadow-xl transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center space-x-3 mb-3">
            <h3 className="font-display text-xl font-bold text-slate-900">{sale.client_name}</h3>
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
            {sale.application_pdf_path && (
              <span className="badge badge-info">
                <Check size={12} /> PDF Uploaded
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <InfoItem label="Policy Number" value={sale.policy_number} />
            <InfoItem label="Premium" value={`$${parseFloat(sale.written_premium).toLocaleString()}`} />
            <InfoItem label="Lead Source" value={sale.lead_source} />
            <InfoItem label="Email" value={sale.client_email || 'N/A'} />
            <InfoItem label="Phone" value={sale.client_phone || 'N/A'} />
            <InfoItem label="Items" value={sale.item_count} />
          </div>

          {sale.notes && (
            <div className="p-3 bg-slate-50 rounded-lg">
              <p className="text-sm text-slate-700">{sale.notes}</p>
            </div>
          )}
        </div>

        <div className="ml-6">
          {!sale.application_pdf_path ? (
            <label className="btn-secondary cursor-pointer flex items-center space-x-2">
              <Upload size={18} />
              <span>{uploading ? 'Uploading...' : 'Upload PDF'}</span>
              <input
                type="file"
                accept=".pdf"
                onChange={handleFileUpload}
                className="hidden"
                disabled={uploading}
              />
            </label>
          ) : (
            <div className="text-green-600 flex items-center space-x-2">
              <Check size={20} />
              <span className="font-semibold">PDF Uploaded</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const InfoItem: React.FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div>
    <div className="text-xs text-slate-500 font-medium mb-1">{label}</div>
    <div className="text-sm font-semibold text-slate-900">{value}</div>
  </div>
);

const CreateSaleModal: React.FC<{ onClose: () => void; onSuccess: () => void }> = ({
  onClose,
  onSuccess,
}) => {
  const [formData, setFormData] = useState({
    policy_number: '',
    written_premium: '',
    lead_source: 'referral',
    client_name: '',
    client_email: '',
    client_phone: '',
    item_count: 1,
    notes: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await salesAPI.create({
        ...formData,
        written_premium: parseFloat(formData.written_premium),
      });
      onSuccess();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create sale');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <h2 className="font-display text-2xl font-bold text-slate-900">Create New Sale</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={24} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Policy Number *
              </label>
              <input
                type="text"
                value={formData.policy_number}
                onChange={(e) => setFormData({ ...formData, policy_number: e.target.value })}
                className="input-field"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Written Premium *
              </label>
              <input
                type="number"
                step="0.01"
                value={formData.written_premium}
                onChange={(e) => setFormData({ ...formData, written_premium: e.target.value })}
                className="input-field"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Client Name *
              </label>
              <input
                type="text"
                value={formData.client_name}
                onChange={(e) => setFormData({ ...formData, client_name: e.target.value })}
                className="input-field"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Lead Source *
              </label>
              <select
                value={formData.lead_source}
                onChange={(e) => setFormData({ ...formData, lead_source: e.target.value })}
                className="input-field"
              >
                <option value="referral">Referral</option>
                <option value="website">Website</option>
                <option value="cold_call">Cold Call</option>
                <option value="social_media">Social Media</option>
                <option value="email_campaign">Email Campaign</option>
                <option value="walk_in">Walk In</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Client Email
              </label>
              <input
                type="email"
                value={formData.client_email}
                onChange={(e) => setFormData({ ...formData, client_email: e.target.value })}
                className="input-field"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Client Phone
              </label>
              <input
                type="tel"
                value={formData.client_phone}
                onChange={(e) => setFormData({ ...formData, client_phone: e.target.value })}
                className="input-field"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              Notes
            </label>
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="input-field"
              rows={3}
            />
          </div>

          <div className="flex items-center justify-end space-x-4 pt-4 border-t border-slate-200">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn-primary">
              {loading ? 'Creating...' : 'Create Sale'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
