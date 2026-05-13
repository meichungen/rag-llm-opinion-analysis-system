import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // Increased to 60s for LLM requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
api.interceptors.request.use(
  (config) => {
    // You can add auth tokens here if needed
    // const token = localStorage.getItem('token');
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    // Handle common errors
    if (error.response) {
      // Server responded with a status code outside of 2xx
      console.error('API Error:', error.response.data);
    } else if (error.request) {
      // No response received
      console.error('Network Error:', error.request);
    } else {
      // Request setup error
      console.error('Error:', error.message);
    }
    return Promise.reject(error);
  }
);

export const endpoints = {
  health: '/health',
  hotSearch: '/hot-search',
  tasks: '/tasks',
  taskReport: (taskId: number) => `/tasks/${taskId}/report`,
  settings: '/settings',
  settingsPlatformCookie: '/settings/platform-cookie',
  dashboard: {
    metrics: '/v1/dashboard/metrics',
  },
  analysis: {
    sentiment: (taskId: number) => `/analysis/sentiment/${taskId}`,
    wordcloud: (taskId: number) => `/analysis/wordcloud/${taskId}`,
    lda: (taskId: number) => `/analysis/lda/${taskId}`,
    preview: (taskId: number) => `/analysis/preview/${taskId}`,
  },
  qa: {
    chat: '/qa',
    stream: '/qa/stream',
    history: '/qa/history',
  },
  agent: {
    chat: '/agent/chat',
  },
  hotTopics: {
    list: '/hot-topics',
    sources: '/hot-topics/sources',
    settings: '/hot-topics/settings',
    refresh: '/hot-topics/refresh',
    analyze: '/hot-topics/analyze',
    export: '/hot-topics/export',
  }
};

export default api;
