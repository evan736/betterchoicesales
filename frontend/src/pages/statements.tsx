import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { statementsAPI } from '../lib/api';
import { Upload, FileText, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

export default function Statements() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [imports, setImports] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState<number | null>(null);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/');
    } else if (user && user.role !== 'admin') {
      router.push('/dashboard');
    } else if (user) {
      loadImports();
    }
  }, [user, loading]);

  const loadImports = async () => {
    try {
      const response = await statementsAPI.list();
      setImports(response.data);
    } catch (error) {
      console.error('Failed to load imports:', error);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const carrier = (document.getElementById('carrier-select') as HTMLSelectElement).value;

    setUploading(true);
    try {
      const response = await statementsAPI.upload(carrier, file);
      alert('File uploaded successfully!');
      loadImports();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleProcess = async (importId: number) => {
    if (!confirm('Process this statement import?')) return;

    setProcessing(importId);
    try {
      await statementsAPI.process(importId);
      alert('Processing started!');
      loadImports();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Processing failed');
    } finally {
      setProcessing(null);
    }
  };

  if (loading || !user || user.role !== 'admin') return null;

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-display text-4xl font-bold text-slate-900 mb-2">
            Statement Imports
          </h1>
          <p className="text-slate-600">Upload and process carrier commission statements</p>
        </div>

        {/* Upload Card */}
        <div className="card mb-8">
          <h2 className="font-display text-2xl font-bold text-slate-900 mb-6">
            Upload New Statement
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Carrier
              </label>
              <select id="carrier-select" className="input-field">
                <option value="national_general">National General</option>
                <option value="progressive">Progressive</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">
                Statement File (CSV, XLSX, PDF)
              </label>
              <label className="btn-primary cursor-pointer inline-flex items-center space-x-2">
                <Upload size={20} />
                <span>{uploading ? 'Uploading...' : 'Choose File'}</span>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.pdf"
                  onChange={handleFileUpload}
                  className="hidden"
                  disabled={uploading}
                />
              </label>
            </div>
          </div>
        </div>

        {/* Import History */}
        <div className="card">
          <h2 className="font-display text-2xl font-bold text-slate-900 mb-6">
            Import History
          </h2>

          {imports.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <FileText size={48} className="mx-auto mb-4 opacity-50" />
              <p>No imports yet. Upload your first statement above.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {imports.map((imp) => (
                <ImportCard
                  key={imp.id}
                  import={imp}
                  onProcess={handleProcess}
                  processing={processing === imp.id}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

const ImportCard: React.FC<{
  import: any;
  onProcess: (id: number) => void;
  processing: boolean;
}> = ({ import: imp, onProcess, processing }) => {
  const getStatusIcon = () => {
    switch (imp.status) {
      case 'completed':
      case 'matched':
        return <CheckCircle className="text-green-600" size={24} />;
      case 'failed':
        return <XCircle className="text-red-600" size={24} />;
      case 'processing':
        return <AlertCircle className="text-yellow-600 animate-pulse" size={24} />;
      default:
        return <FileText className="text-blue-600" size={24} />;
    }
  };

  const getStatusColor = () => {
    switch (imp.status) {
      case 'completed':
      case 'matched':
        return 'badge-success';
      case 'failed':
        return 'badge-danger';
      case 'processing':
        return 'badge-warning';
      default:
        return 'badge-info';
    }
  };

  return (
    <div className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:border-brand-300 transition-all">
      <div className="flex items-center space-x-4 flex-1">
        {getStatusIcon()}
        
        <div className="flex-1">
          <div className="flex items-center space-x-3 mb-2">
            <h3 className="font-semibold text-slate-900">{imp.filename}</h3>
            <span className={`badge ${getStatusColor()}`}>{imp.status}</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-600">Carrier: </span>
              <span className="font-semibold capitalize">{imp.carrier.replace('_', ' ')}</span>
            </div>
            <div>
              <span className="text-slate-600">Total: </span>
              <span className="font-semibold">{imp.total_rows || 0}</span>
            </div>
            <div>
              <span className="text-slate-600">Matched: </span>
              <span className="font-semibold text-green-600">{imp.matched_rows || 0}</span>
            </div>
            <div>
              <span className="text-slate-600">Unmatched: </span>
              <span className="font-semibold text-red-600">{imp.unmatched_rows || 0}</span>
            </div>
          </div>
        </div>
      </div>

      {imp.status === 'uploaded' && (
        <button
          onClick={() => onProcess(imp.id)}
          disabled={processing}
          className="btn-primary ml-4"
        >
          {processing ? 'Processing...' : 'Process'}
        </button>
      )}
    </div>
  );
};
