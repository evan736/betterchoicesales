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
  list: () => api.get('/api/sales/'),
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

// Statements API
export const statementsAPI = {
  upload: (carrier: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/api/statements/upload?carrier=${carrier}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  process: (id: number) => api.post(`/api/statements/${id}/process`),
  list: () => api.get('/api/statements/'),
  get: (id: number) => api.get(`/api/statements/${id}`),
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
