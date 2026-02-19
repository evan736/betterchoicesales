import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../contexts/AuthContext';
import Navbar from '../components/Navbar';
import { adminAPI, surveyAPI } from '../lib/api';

const ROLES = ['admin', 'manager', 'producer', 'retention_specialist'];

const AdminPage = () => {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<'employees' | 'tiers' | 'sources' | 'carriers' | 'templates'>('employees');

  useEffect(() => {
    if (!authLoading && !user) router.push('/');
  }, [user, authLoading]);

  if (authLoading || !user) return null;
  if (user.role?.toLowerCase() !== 'admin') {
    return (
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <div className="max-w-4xl mx-auto px-4 py-20 text-center">
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Admin Access Required</h1>
          <p className="text-slate-500">You don&apos;t have permission to view this page.</p>
        </div>
      </div>
    );
  }

  const tabs = [
    { key: 'employees', label: 'Employees' },
    { key: 'tiers', label: 'Commission Plans' },
    { key: 'sources', label: 'Lead Sources' },
    { key: 'carriers', label: 'Carriers' },
    { key: 'templates', label: 'Email Templates' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold text-slate-900 mb-1">Admin Panel</h1>
        <p className="text-sm text-slate-500 mb-6">Manage employees, commission plans, lead sources, carriers, and email templates</p>

        <div className="flex space-x-1 bg-white rounded-xl p-1 shadow-sm border border-slate-200 mb-6 overflow-x-auto">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key as any)}
              className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all whitespace-nowrap ${
                tab === t.key ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'employees' && <EmployeesTab />}
        {tab === 'tiers' && <CommissionTiersTab />}
        {tab === 'sources' && <LeadSourcesTab />}
        {tab === 'carriers' && <CarriersTab />}
        {tab === 'templates' && <EmailTemplatesTab />}
      </main>
    </div>
  );
};


// ── Employees Tab ───────────────────────────────────────────────────

const EmployeesTab = () => {
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [resetId, setResetId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');

  // Create form
  const [form, setForm] = useState({ email: '', username: '', full_name: '', password: '', role: 'producer', producer_code: '', commission_tier: 1 });
  const [editForm, setEditForm] = useState<any>({});

  useEffect(() => { load(); }, []);

  const load = async () => {
    try {
      const res = await adminAPI.listEmployees();
      setEmployees(res.data);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleCreate = async () => {
    try {
      await adminAPI.createEmployee(form);
      setShowCreate(false);
      setForm({ email: '', username: '', full_name: '', password: '', role: 'producer', producer_code: '', commission_tier: 1 });
      load();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create employee');
    }
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    try {
      await adminAPI.updateEmployee(editingId, editForm);
      setEditingId(null);
      load();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update');
    }
  };

  const handleDelete = async (emp: any) => {
    if (!confirm(`Delete ${emp.full_name}? This cannot be undone.`)) return;
    try {
      await adminAPI.deleteEmployee(emp.id);
      load();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete');
    }
  };

  const handleResetPassword = async () => {
    if (!resetId || !newPassword) return;
    try {
      await adminAPI.resetPassword(resetId, newPassword);
      alert('Password reset successfully');
      setResetId(null);
      setNewPassword('');
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to reset password');
    }
  };

  const startEdit = (emp: any) => {
    setEditingId(emp.id);
    setEditForm({ email: emp.email, full_name: emp.full_name, role: emp.role, producer_code: emp.producer_code || '', commission_tier: emp.commission_tier, is_active: emp.is_active });
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Loading employees...</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-sm text-slate-500">{employees.length} employees</span>
        <button onClick={() => setShowCreate(!showCreate)} className="bg-slate-900 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-800">
          + Add Employee
        </button>
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h3 className="font-bold text-slate-900 mb-4">New Employee</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <input placeholder="Full Name *" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Email *" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Username *" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Password *" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm">
              {ROLES.map(r => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
            </select>
            <input placeholder="Producer Code" value={form.producer_code} onChange={e => setForm({ ...form, producer_code: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm" />
            <select value={form.commission_tier} onChange={e => setForm({ ...form, commission_tier: parseInt(e.target.value) })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm">
              {[1,2,3,4,5,6,7].map(t => <option key={t} value={t}>Tier {t}</option>)}
            </select>
            <button onClick={handleCreate} className="bg-green-600 text-white rounded-lg px-4 py-2 text-sm font-semibold hover:bg-green-700">
              Create
            </button>
          </div>
        </div>
      )}

      {/* Employee Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-left py-3 px-4 font-semibold text-slate-600">Name</th>
              <th className="text-left py-3 px-4 font-semibold text-slate-600">Username</th>
              <th className="text-left py-3 px-4 font-semibold text-slate-600">Email</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Role</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Code</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Tier</th>
              <th className="text-right py-3 px-4 font-semibold text-slate-600">Sales</th>
              <th className="text-right py-3 px-4 font-semibold text-slate-600">Premium</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Status</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((emp, i) => (
              <tr key={emp.id} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                {editingId === emp.id ? (
                  <>
                    <td className="py-2 px-4"><input value={editForm.full_name} onChange={e => setEditForm({ ...editForm, full_name: e.target.value })} className="border rounded px-2 py-1 text-sm w-full" /></td>
                    <td className="py-2 px-4 text-slate-400 text-xs font-mono">{emp.username}</td>
                    <td className="py-2 px-4"><input value={editForm.email} onChange={e => setEditForm({ ...editForm, email: e.target.value })} className="border rounded px-2 py-1 text-sm w-full" /></td>
                    <td className="py-2 px-4 text-center">
                      <select value={editForm.role} onChange={e => setEditForm({ ...editForm, role: e.target.value })} className="border rounded px-2 py-1 text-sm">
                        {ROLES.map(r => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
                      </select>
                    </td>
                    <td className="py-2 px-4 text-center"><input value={editForm.producer_code} onChange={e => setEditForm({ ...editForm, producer_code: e.target.value })} className="border rounded px-2 py-1 text-xs w-20 text-center" /></td>
                    <td className="py-2 px-4 text-center">
                      <select value={editForm.commission_tier} onChange={e => setEditForm({ ...editForm, commission_tier: parseInt(e.target.value) })} className="border rounded px-1 py-1 text-sm">
                        {[1,2,3,4,5,6,7].map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td className="py-2 px-4 text-right text-slate-400">{emp.sale_count}</td>
                    <td className="py-2 px-4 text-right text-slate-400">${(emp.total_premium || 0).toLocaleString()}</td>
                    <td className="py-2 px-4 text-center">
                      <select value={editForm.is_active ? 'active' : 'inactive'} onChange={e => setEditForm({ ...editForm, is_active: e.target.value === 'active' })} className="border rounded px-1 py-1 text-xs">
                        <option value="active">Active</option>
                        <option value="inactive">Inactive</option>
                      </select>
                    </td>
                    <td className="py-2 px-4 text-center">
                      <button onClick={handleUpdate} className="text-green-600 font-semibold text-xs mr-2 hover:underline">Save</button>
                      <button onClick={() => setEditingId(null)} className="text-slate-400 text-xs hover:underline">Cancel</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="py-2.5 px-4 font-medium">{emp.full_name}</td>
                    <td className="py-2.5 px-4 text-slate-500 font-mono text-xs">{emp.username}</td>
                    <td className="py-2.5 px-4 text-slate-500">{emp.email}</td>
                    <td className="py-2.5 px-4 text-center">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full capitalize ${
                        emp.role === 'admin' ? 'bg-purple-100 text-purple-700' :
                        emp.role === 'manager' ? 'bg-blue-100 text-blue-700' :
                        emp.role === 'producer' ? 'bg-green-100 text-green-700' :
                        'bg-slate-100 text-slate-600'
                      }`}>{emp.role?.replace('_', ' ')}</span>
                    </td>
                    <td className="py-2.5 px-4 text-center font-mono text-xs">{emp.producer_code || '—'}</td>
                    <td className="py-2.5 px-4 text-center">{emp.commission_tier}</td>
                    <td className="py-2.5 px-4 text-right">{emp.sale_count}</td>
                    <td className="py-2.5 px-4 text-right">${(emp.total_premium || 0).toLocaleString()}</td>
                    <td className="py-2.5 px-4 text-center">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${emp.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                        {emp.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-center">
                      <div className="flex items-center justify-center space-x-1">
                        <button onClick={() => startEdit(emp)} className="text-blue-600 text-xs font-semibold hover:underline">Edit</button>
                        <button onClick={() => { setResetId(emp.id); setNewPassword(''); }} className="text-amber-600 text-xs font-semibold hover:underline">Reset PW</button>
                        <button onClick={() => handleDelete(emp)} className="text-red-500 text-xs font-semibold hover:underline">Delete</button>
                      </div>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Reset Password Modal */}
      {resetId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setResetId(null)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-sm shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold text-lg mb-4">Reset Password</h3>
            <p className="text-sm text-slate-500 mb-3">
              For: {employees.find(e => e.id === resetId)?.full_name}
            </p>
            <input
              type="text"
              placeholder="New password (min 6 chars)"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm mb-4"
            />
            <div className="flex space-x-3">
              <button onClick={handleResetPassword} disabled={newPassword.length < 6}
                className="flex-1 bg-amber-500 text-white font-semibold py-2 rounded-lg hover:bg-amber-600 disabled:opacity-50 text-sm">
                Reset Password
              </button>
              <button onClick={() => setResetId(null)} className="flex-1 border border-slate-300 py-2 rounded-lg text-sm hover:bg-slate-50">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};


// ── Commission Tiers Tab ────────────────────────────────────────────

const CommissionTiersTab = () => {
  const [tiers, setTiers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ tier_level: 0, min_written_premium: 0, max_written_premium: null as number | null, commission_rate: 0, description: '' });

  useEffect(() => { load(); }, []);

  const load = async () => {
    try { const res = await adminAPI.listTiers(); setTiers(res.data); } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleSave = async () => {
    try {
      if (editId) {
        await adminAPI.updateTier(editId, form);
      } else {
        await adminAPI.createTier(form);
      }
      setEditId(null);
      setForm({ tier_level: 0, min_written_premium: 0, max_written_premium: null, commission_rate: 0, description: '' });
      load();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to save tier');
    }
  };

  const handleDelete = async (tier: any) => {
    if (!confirm(`Delete Tier ${tier.tier_level}?`)) return;
    try { await adminAPI.deleteTier(tier.id); load(); } catch (err: any) { alert(err.response?.data?.detail || 'Failed'); }
  };

  const startEdit = (tier: any) => {
    setEditId(tier.id);
    setForm({ tier_level: tier.tier_level, min_written_premium: tier.min_written_premium, max_written_premium: tier.max_written_premium, commission_rate: tier.commission_rate, description: tier.description || '' });
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Loading...</div>;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex justify-between items-center">
          <div>
            <h3 className="font-bold text-slate-900">Commission Tiers</h3>
            <p className="text-xs text-slate-500">Monthly written premium brackets determine agent commission rates</p>
          </div>
          <button onClick={() => { setEditId(null); setForm({ tier_level: tiers.length + 1, min_written_premium: 0, max_written_premium: null, commission_rate: 0, description: '' }); }}
            className="bg-slate-900 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-slate-800">
            + Add Tier
          </button>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Tier</th>
              <th className="text-right py-3 px-4 font-semibold text-slate-600">Min Premium</th>
              <th className="text-right py-3 px-4 font-semibold text-slate-600">Max Premium</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Rate</th>
              <th className="text-left py-3 px-4 font-semibold text-slate-600">Description</th>
              <th className="text-center py-3 px-4 font-semibold text-slate-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier, i) => (
              <tr key={tier.id} className={`border-t border-slate-100 ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                <td className="py-2.5 px-4 text-center font-bold">{tier.tier_level}</td>
                <td className="py-2.5 px-4 text-right">${(tier.min_written_premium || 0).toLocaleString()}</td>
                <td className="py-2.5 px-4 text-right">{tier.max_written_premium ? `$${tier.max_written_premium.toLocaleString()}` : 'No limit'}</td>
                <td className="py-2.5 px-4 text-center font-bold text-green-700">{(tier.commission_rate * 100).toFixed(1)}%</td>
                <td className="py-2.5 px-4 text-slate-500">{tier.description}</td>
                <td className="py-2.5 px-4 text-center">
                  <button onClick={() => startEdit(tier)} className="text-blue-600 text-xs font-semibold hover:underline mr-2">Edit</button>
                  <button onClick={() => handleDelete(tier)} className="text-red-500 text-xs font-semibold hover:underline">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit/Create Form */}
      {(editId !== null || form.tier_level > 0) && form.commission_rate !== undefined && (
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h3 className="font-bold text-slate-900 mb-3">{editId ? 'Edit Tier' : 'New Tier'}</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Tier Level</label>
              <input type="number" value={form.tier_level} onChange={e => setForm({ ...form, tier_level: parseInt(e.target.value) })}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Min Premium ($)</label>
              <input type="number" value={form.min_written_premium} onChange={e => setForm({ ...form, min_written_premium: parseFloat(e.target.value) })}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Max Premium ($)</label>
              <input type="number" value={form.max_written_premium || ''} onChange={e => setForm({ ...form, max_written_premium: e.target.value ? parseFloat(e.target.value) : null })}
                placeholder="No limit" className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Rate (decimal, e.g. 0.05)</label>
              <input type="number" step="0.001" value={form.commission_rate} onChange={e => setForm({ ...form, commission_rate: parseFloat(e.target.value) })}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <div className="flex items-end space-x-2">
              <button onClick={handleSave} className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-green-700 flex-1">Save</button>
              <button onClick={() => { setEditId(null); setForm({ tier_level: 0, min_written_premium: 0, max_written_premium: null, commission_rate: 0, description: '' }); }}
                className="border border-slate-300 px-3 py-2 rounded-lg text-sm hover:bg-slate-50">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};


// ── Lead Sources Tab ────────────────────────────────────────────────

const LeadSourcesTab = () => {
  const [sources, setSources] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [newSource, setNewSource] = useState('');

  useEffect(() => { load(); }, []);

  const load = async () => {
    try { const res = await adminAPI.listLeadSources(); setSources(res.data); } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!newSource.trim()) return;
    try {
      await adminAPI.addLeadSource({ name: newSource });
      setNewSource('');
      load();
    } catch (err: any) { alert(err.response?.data?.detail || 'Failed'); }
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Loading...</div>;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200">
          <h3 className="font-bold text-slate-900">Lead Sources</h3>
          <p className="text-xs text-slate-500">Lead sources available when creating sales</p>
        </div>
        <div className="p-5">
          <div className="flex space-x-3 mb-4">
            <input
              value={newSource}
              onChange={e => setNewSource(e.target.value)}
              placeholder="New lead source name (e.g. Facebook Ads)"
              className="flex-1 border border-slate-300 rounded-lg px-4 py-2.5 text-sm"
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
            <button onClick={handleAdd} className="bg-slate-900 text-white px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-slate-800">
              Add
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {sources.map(s => (
              <div key={s.name} className="flex items-center justify-between bg-slate-50 rounded-lg px-4 py-3 border border-slate-200">
                <span className="text-sm font-medium capitalize">{s.display_name}</span>
                <div className="flex items-center space-x-3">
                  <span className="text-xs text-slate-400">{s.sale_count} sales</span>
                  <button
                    onClick={async () => {
                      if (!confirm('Delete lead source "' + s.display_name + '"?')) return;
                      try { await adminAPI.deleteLeadSource(s.name); load(); }
                      catch (err: any) { alert(err.response?.data?.detail || 'Failed to delete'); }
                    }}
                    className="text-red-400 hover:text-red-600 text-xs font-semibold"
                    title="Delete source"
                  >
                    &times;
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};


// ── Carriers Tab ────────────────────────────────────────────────────

const CarriersTab = () => {
  const [carriers, setCarriers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [newCarrier, setNewCarrier] = useState('');

  useEffect(() => { load(); }, []);

  const load = async () => {
    try { const res = await adminAPI.listCarriers(); setCarriers(res.data); } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!newCarrier.trim()) return;
    try {
      await adminAPI.addCarrier({ name: newCarrier });
      setNewCarrier('');
      load();
    } catch (err: any) { alert(err.response?.data?.detail || 'Failed'); }
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Loading...</div>;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200">
          <h3 className="font-bold text-slate-900">Carriers</h3>
          <p className="text-xs text-slate-500">Insurance carriers used in sales and commission statements</p>
        </div>
        <div className="p-5">
          <div className="flex space-x-3 mb-4">
            <input
              value={newCarrier}
              onChange={e => setNewCarrier(e.target.value)}
              placeholder="New carrier name (e.g. GEICO)"
              className="flex-1 border border-slate-300 rounded-lg px-4 py-2.5 text-sm"
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
            <button onClick={handleAdd} className="bg-slate-900 text-white px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-slate-800">
              Add
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {carriers.map(c => (
              <div key={c.name} className="flex items-center justify-between bg-slate-50 rounded-lg px-4 py-3 border border-slate-200">
                <span className="text-sm font-medium capitalize">{c.display_name}</span>
                <div className="flex items-center space-x-3">
                  <div className="text-right">
                    <span className="text-xs text-slate-400 block">{c.sale_count} sales</span>
                    {c.statement_count > 0 && <span className="text-xs text-blue-400">{c.statement_count} statements</span>}
                  </div>
                  <button
                    onClick={async () => {
                      if (!confirm('Delete carrier "' + c.display_name + '"?')) return;
                      try { await adminAPI.deleteCarrier(c.name); load(); }
                      catch (err: any) { alert(err.response?.data?.detail || 'Failed to delete'); }
                    }}
                    className="text-red-400 hover:text-red-600 text-xs font-semibold"
                    title="Delete carrier"
                  >
                    &times;
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Email Templates Tab ─────────────────────────────────────────────

const EmailTemplatesTab = () => {
  const [templates, setTemplates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState<string>('');
  const [previewSubject, setPreviewSubject] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => { load(); }, []);

  const load = async () => {
    try {
      const res = await surveyAPI.welcomeTemplates();
      setTemplates(res.data.templates || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handlePreview = async (key: string) => {
    if (previewKey === key) {
      setPreviewKey(null);
      return;
    }
    setPreviewKey(key);
    setPreviewLoading(true);
    try {
      const res = await surveyAPI.previewTemplate(key);
      setPreviewHtml(res.data.html || '');
      setPreviewSubject(res.data.subject || '');
    } catch (e) {
      console.error(e);
      setPreviewHtml('<p style="padding:20px;color:#ef4444;">Failed to load preview</p>');
    }
    setPreviewLoading(false);
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Loading templates...</div>;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200">
          <h3 className="font-bold text-slate-900">Welcome Email Templates</h3>
          <p className="text-xs text-slate-500 mt-1">
            {templates.length} carrier-specific templates + 1 generic fallback. Click any template to preview.
          </p>
        </div>
        <div className="p-5">
          {/* Generic fallback card */}
          <div className="mb-4">
            <button
              onClick={() => handlePreview('generic')}
              className={`w-full text-left rounded-xl border-2 border-dashed p-4 transition-all ${
                previewKey === 'generic'
                  ? 'border-blue-400 bg-blue-50'
                  : 'border-slate-300 hover:border-slate-400 hover:bg-slate-50'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center text-lg" style={{ background: '#1a2b5f' }}>
                    <span className="text-white text-sm font-bold">BCI</span>
                  </div>
                  <div>
                    <p className="font-semibold text-slate-900">Generic Fallback Template</p>
                    <p className="text-xs text-slate-500">Used when no carrier-specific template exists</p>
                  </div>
                </div>
                <span className="text-xs text-slate-400">{previewKey === 'generic' ? '▲ Close' : '▼ Preview'}</span>
              </div>
            </button>
          </div>

          {/* Carrier template grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {templates.map(t => (
              <button
                key={t.key}
                onClick={() => handlePreview(t.key)}
                className={`text-left rounded-xl border p-4 transition-all ${
                  previewKey === t.key
                    ? 'border-blue-400 bg-blue-50 shadow-md'
                    : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'
                }`}
              >
                <div className="flex items-center space-x-3 mb-2">
                  <div
                    className="w-8 h-8 rounded-lg flex-shrink-0"
                    style={{ backgroundColor: t.accent_color }}
                  />
                  <p className="font-semibold text-slate-900 text-sm leading-tight">{t.display_name}</p>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {t.has_mobile_app && (
                    <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">📱 App</span>
                  )}
                  {t.has_online_account && (
                    <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium">🌐 Portal</span>
                  )}
                  {t.has_payment_url && (
                    <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded font-medium">💳 Pay</span>
                  )}
                  {t.has_claims_phone && (
                    <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-medium">📞 Claims</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Preview Panel */}
      {previewKey && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h3 className="font-bold text-slate-900 text-sm">
                Preview: {previewKey === 'generic' ? 'Generic Fallback' : templates.find(t => t.key === previewKey)?.display_name}
              </h3>
              {previewSubject && (
                <p className="text-xs text-slate-500 mt-1">
                  <span className="font-medium">Subject:</span> {previewSubject}
                </p>
              )}
            </div>
            <button
              onClick={() => setPreviewKey(null)}
              className="text-slate-400 hover:text-slate-600 text-lg font-bold px-2"
            >
              ×
            </button>
          </div>
          <div className="p-4 bg-slate-100">
            {previewLoading ? (
              <div className="text-center py-12 text-slate-500">Loading preview...</div>
            ) : (
              <div className="max-w-[600px] mx-auto bg-white rounded-lg shadow-sm overflow-hidden">
                <iframe
                  srcDoc={previewHtml}
                  title="Email Preview"
                  className="w-full border-0"
                  style={{ minHeight: '700px' }}
                  sandbox="allow-same-origin"
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminPage;
