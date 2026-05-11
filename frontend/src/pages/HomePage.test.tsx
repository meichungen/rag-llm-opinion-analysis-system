import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import api from '../services/api';
import {
  DashboardMetricsSection,
  dashboardMetricsQueryOptions,
  formatDashboardMetricValue,
} from './HomePage';

vi.mock('../services/api', () => ({
  __esModule: true,
  default: {
    get: vi.fn(),
  },
  endpoints: {
    dashboard: {
      metrics: '/v1/dashboard/metrics',
    },
  },
}));

const mockedGet = vi.mocked(api.get);

const renderMetricsSection = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardMetricsSection totalTasks={8} />
    </QueryClientProvider>,
  );
};

describe('DashboardMetricsSection', () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders formatted dashboard metrics when data loads successfully', async () => {
    mockedGet.mockResolvedValue({
      data: {
        totalCollected: 12000,
        activeTasks: 6,
        todayNewTasks: 18,
      },
    });

    renderMetricsSection();

    expect(await screen.findByText('1.2 万')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
  });

  it('renders skeletons while loading', () => {
    mockedGet.mockImplementation(() => new Promise(() => undefined));

    renderMetricsSection();

    expect(screen.getByTestId('total-collected-loading')).toBeInTheDocument();
    expect(screen.getByTestId('active-tasks-loading')).toBeInTheDocument();
    expect(screen.getByTestId('today-new-tasks-loading')).toBeInTheDocument();
  });

  it('renders error alerts when the query fails', async () => {
    mockedGet.mockRejectedValue(new Error('network error'));

    renderMetricsSection();

    expect(await screen.findByTestId('total-collected-error')).toHaveTextContent('累计采集数据加载失败');
    expect(screen.getByTestId('active-tasks-error')).toHaveTextContent('活跃监测任务加载失败');
    expect(screen.getByTestId('today-new-tasks-error')).toHaveTextContent('今日新增任务加载失败');
  });

  it('configures silent refetch every 60 seconds', () => {
    expect(dashboardMetricsQueryOptions.refetchInterval).toBe(60000);
    expect(dashboardMetricsQueryOptions.refetchIntervalInBackground).toBe(true);
    expect(dashboardMetricsQueryOptions.refetchOnWindowFocus).toBe(false);
  });
});

describe('formatDashboardMetricValue', () => {
  it('formats values above ten thousand using wan units', () => {
    expect(formatDashboardMetricValue(12000)).toBe('1.2 万');
  });

  it('keeps small values as plain numbers', () => {
    expect(formatDashboardMetricValue(9999)).toBe('9999');
  });
});
