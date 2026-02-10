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
  agentSheet: (period: string, agentId: number) =>
    api.get(`/api/reconciliation/agent-sheet/${period}/${agentId}`),
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
  submit: (period: string) => api.post(`/api/payroll/submit/${period}`),
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
