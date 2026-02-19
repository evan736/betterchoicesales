import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
});

// Add token to requests automatically
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Sales API
export const salesAPI = {
  list: (params?: { date_from?: string; date_to?: string; producer_id?: number }) =>
    api.get('/api/sales/', { params }),
  get: (id: number) => api.get(`/api/sales/${id}`),
  create: (data: any) => api.post('/api/sales/', data),
  createFromPdf: (data: any) => api.post('/api/sales/create-from-pdf', data),
  update: (id: number, data: any) => api.patch(`/api/sales/${id}`, data),
  delete: (id: number) => api.delete(`/api/sales/${id}`),
  uploadPDF: (id: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/api/sales/${id}/upload-application`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  extractPDF: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/sales/extract-pdf', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    });
  },
  sendForSignature: (id: number, file?: File) => {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      return api.post(`/api/sales/${id}/send-for-signature`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000, // 2 minutes — BoldSign can be slow
      });
    }
    return api.post(`/api/sales/${id}/send-for-signature`, {}, { timeout: 120000 });
  },
  signatureStatus: (id: number) => api.get(`/api/sales/${id}/signature-status`),
  importCSV: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/sales/import-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    });
  },
};

// Commissions API
export const commissionsAPI = {
  calculate: (producerId: number, period: string) =>
    api.get(`/api/commissions/calculate/${producerId}/${period}`),
  myCommissions: (period?: string) =>
    api.get('/api/commissions/my-commissions', { params: { period } }),
  myTier: () => api.get('/api/commissions/my-tier'),
  tiers: () => api.get('/api/commissions/tiers'),
  createTier: (data: any) => api.post('/api/commissions/tiers', data),
};

// Reconciliation API (commission statement processing)
export const reconciliationAPI = {
  upload: (carrier: string, period: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('carrier', carrier);
    formData.append('period', period);
    return api.post('/api/reconciliation/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    });
  },
  list: () => api.get('/api/reconciliation/'),
  get: (id: number) => api.get(`/api/reconciliation/${id}`),
  match: (id: number) => api.post(`/api/reconciliation/${id}/match`),
  calculate: (id: number) => api.post(`/api/reconciliation/${id}/calculate`),
  delete: (id: number) => api.delete(`/api/reconciliation/${id}`),
  manualMatch: (lineId: number, saleId: number) =>
    api.post(`/api/reconciliation/lines/${lineId}/match?sale_id=${saleId}`),
  monthlyPay: (period: string) =>
    api.post(`/api/reconciliation/monthly-pay/${period}`),
  getMonthlyPay: (period: string) =>
    api.get(`/api/reconciliation/monthly-pay/${period}`),
  agentSheet: (period: string, agentId: number, rateAdjustment?: number, bonus?: number) => {
    const params: any = {};
    if (rateAdjustment) params.rate_adjustment = rateAdjustment;
    if (bonus) params.bonus = bonus;
    return api.get(`/api/reconciliation/agent-sheet/${period}/${agentId}`, {
      params: Object.keys(params).length ? params : undefined,
    });
  },
  agentSheetPdfUrl: (period: string, agentId: number) =>
    `/api/reconciliation/agent-sheet/${period}/${agentId}/pdf`,
};

// Legacy alias
export const statementsAPI = {
  upload: (carrier: string, file: File) => {
    const period = new Date().toISOString().slice(0, 7);
    return reconciliationAPI.upload(carrier, period, file);
  },
  process: (id: number) => reconciliationAPI.match(id),
  list: () => reconciliationAPI.list(),
  get: (id: number) => reconciliationAPI.get(id),
};

export default api;

// Analytics API
export const analyticsAPI = {
  summary: (params?: any) => api.get('/api/analytics/summary', { params }),
  byGroup: (params: any) => api.get('/api/analytics/by-group', { params }),
  salesTable: (params?: any) => api.get('/api/analytics/sales-table', { params }),
  filterOptions: () => api.get('/api/analytics/filter-options'),
  trending: (params?: any) => api.get('/api/analytics/trending', { params }),
};

// Payroll API
export const payrollAPI = {
  submit: (period: string, agentOverrides?: Record<string, { rate_adjustment: number; bonus: number }>) =>
    api.post(`/api/payroll/submit/${period}`, { agent_overrides: agentOverrides || {} }),
  unlock: (period: string) => api.post(`/api/payroll/unlock/${period}`),
  markPaid: (period: string) => api.post(`/api/payroll/mark-paid/${period}`),
  history: () => api.get('/api/payroll/history'),
  detail: (period: string) => api.get(`/api/payroll/detail/${period}`),
};

// Retention Analytics API
export const retentionAPI = {
  overview: (period?: string) => api.get('/api/retention/overview', { params: period ? { period } : {} }),
  byAgent: (period?: string) => api.get('/api/retention/by-agent', { params: period ? { period } : {} }),
  byCarrier: (period?: string) => api.get('/api/retention/by-carrier', { params: period ? { period } : {} }),
  bySource: (period?: string) => api.get('/api/retention/by-source', { params: period ? { period } : {} }),
  trend: (months?: number) => api.get('/api/retention/trend', { params: { months: months || 6 } }),
  earlyCancellations: (days?: number, period?: string) =>
    api.get('/api/retention/early-cancellations', { params: { days: days || 90, ...(period ? { period } : {}) } }),
};

// Survey / Welcome Email API
export const surveyAPI = {
  sendWelcome: (saleId: number, opts?: { file?: File; attachSavedPdf?: boolean }) => {
    if (opts?.file) {
      const formData = new FormData();
      formData.append('file', opts.file);
      return api.post(`/api/survey/send-welcome/${saleId}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
      });
    }
    if (opts?.attachSavedPdf) {
      return api.post(`/api/survey/send-welcome/${saleId}?attach_saved_pdf=true`, {}, { timeout: 30000 });
    }
    return api.post(`/api/survey/send-welcome/${saleId}`);
  },
  previewEmail: (saleId: number) => api.get(`/api/survey/preview/${saleId}`),
  responses: () => api.get('/api/survey/responses'),
  stats: () => api.get('/api/survey/stats'),
  welcomeTemplates: () => api.get('/api/survey/welcome-templates'),
  previewTemplate: (carrierKey: string) => api.get(`/api/survey/welcome-templates/${encodeURIComponent(carrierKey)}/preview`),
};

// Admin API
export const adminAPI = {
  // Employees
  listEmployees: () => api.get('/api/admin/employees'),
  createEmployee: (data: any) => api.post('/api/admin/employees', data),
  updateEmployee: (id: number, data: any) => api.put(`/api/admin/employees/${id}`, data),
  deleteEmployee: (id: number) => api.delete(`/api/admin/employees/${id}`),
  resetPassword: (id: number, newPassword: string) =>
    api.post(`/api/admin/employees/${id}/reset-password`, { new_password: newPassword }),
  // Commission Tiers
  listTiers: () => api.get('/api/admin/commission-tiers'),
  createTier: (data: any) => api.post('/api/admin/commission-tiers', data),
  updateTier: (id: number, data: any) => api.put(`/api/admin/commission-tiers/${id}`, data),
  deleteTier: (id: number) => api.delete(`/api/admin/commission-tiers/${id}`),
  // Lead Sources & Carriers
  listLeadSources: () => api.get('/api/admin/lead-sources'),
  addLeadSource: (data: any) => api.post('/api/admin/lead-sources', data),
  listCarriers: () => api.get('/api/admin/carriers'),
  addCarrier: (data: any) => api.post('/api/admin/carriers', data),
  deleteCarrier: (name: string) => api.delete('/api/admin/carriers/' + encodeURIComponent(name)),
  deleteLeadSource: (name: string) => api.delete('/api/admin/lead-sources/' + encodeURIComponent(name)),
  // Survey stats
  surveyStats: () => api.get('/api/admin/survey-stats'),
  // Dropdown options (any user)
  dropdownOptions: () => api.get('/api/admin/dropdown-options'),
};

export const timeclockAPI = {
  clockIn: (data?: { note?: string; latitude?: number; longitude?: number; gps_accuracy?: number }) =>
    api.post('/api/timeclock/clock-in', null, { params: data || {} }),
  clockOut: (data?: { note?: string; latitude?: number; longitude?: number; gps_accuracy?: number }) =>
    api.post('/api/timeclock/clock-out', null, { params: data || {} }),
  status: () => api.get('/api/timeclock/status'),
  myHistory: (month?: string) => api.get('/api/timeclock/my-history', { params: { month } }),
  adminSummary: (month?: string) => api.get('/api/timeclock/admin/summary', { params: { month } }),
  adminEmployeeDetail: (userId: number, month?: string) =>
    api.get(`/api/timeclock/admin/employee/${userId}`, { params: { month } }),
  excuse: (entryId: number, note?: string) =>
    api.post(`/api/timeclock/admin/excuse/${entryId}`, null, { params: { note } }),
  unexcuse: (entryId: number) => api.post(`/api/timeclock/admin/unexcuse/${entryId}`),
};

export const customersAPI = {
  search: (params: { q?: string; source?: string; page?: number; page_size?: number }) =>
    api.get('/api/customers/search', { params }),
  get: (id: number) => api.get(`/api/customers/${id}`),
  sync: (id: number) => api.post(`/api/customers/${id}/sync`),
  importFromNowCerts: (nowcertsId: string) =>
    api.post('/api/customers/import-from-nowcerts', null, { params: { nowcerts_insured_id: nowcertsId } }),
  syncAll: () => api.post('/api/customers/sync-all'),
  nowcertsStatus: () => api.get('/api/customers/nowcerts/status'),
  agencyStats: () => api.get('/api/customers/agency-stats'),
  duplicates: () => api.get('/api/customers/duplicates'),
  merge: (keepId: number, mergeIds: number[]) =>
    api.post('/api/customers/merge', null, { params: { keep_id: keepId, merge_ids: mergeIds.join(',') } }),
};

export const nonpayAPI = {
  upload: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/nonpay/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 });
  },
  history: (limit?: number) => api.get('/api/nonpay/history', { params: { limit: limit || 20 } }),
  emails: (policyNumber?: string) => api.get('/api/nonpay/emails', { params: { policy_number: policyNumber } }),
  carriers: () => api.get('/api/nonpay/carriers'),
  preview: (params: { carrier: string; client_name?: string; policy_number?: string; amount_due?: number; due_date?: string }) =>
    api.get('/api/nonpay/preview', { params }),
  sendTest: (params: { to_email: string; carrier: string }) =>
    api.post('/api/nonpay/send-test', null, { params }),
};
