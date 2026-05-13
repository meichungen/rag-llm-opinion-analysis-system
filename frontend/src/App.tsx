// 前端主应用组件
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import MainLayout from './layouts/MainLayout';
import HomePage from './pages/HomePage';
import TaskManagementPage from './pages/TaskManagementPage';
import AnalysisPage from './pages/AnalysisPage';
import QAPage from './pages/QAPage';
import AgentPage from './pages/AgentPage';
import SettingsPage from './pages/SettingsPage';
import HotTopicsPage from './pages/HotTopicsPage';
import './App.css';

const queryClient = new QueryClient();

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        theme={{
          token: {
            colorPrimary: '#1890ff',
            borderRadius: 8,
          },
        }}
      >
        <Router>
          <Routes>
            <Route path="/" element={<MainLayout />}>
              <Route index element={<HomePage />} />
              <Route path="tasks" element={<TaskManagementPage />} />
              <Route path="hot-topics" element={<HotTopicsPage />} />
              <Route path="analysis" element={<AnalysisPage />} />
              <Route path="qa" element={<QAPage />} />
              <Route path="agent" element={<AgentPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Router>
      </ConfigProvider>
    </QueryClientProvider>
  );
};

export default App;
