import React, { useState, useEffect } from 'react';
import { 
  Alert,
  Card, 
  Row, 
  Col, 
  Statistic, 
  List, 
  Tag, 
  Input, 
  Button, 
  Space, 
  Typography,
  Spin,
  message,
  Modal,
  Form,
  Select,
  InputNumber,
  Divider,
  Empty,
  Avatar,
  Segmented,
  Skeleton
} from 'antd';
import {
  FireOutlined,
  SearchOutlined,
  RiseOutlined,
  ProjectOutlined,
  FileTextOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
  RobotOutlined,
  SettingOutlined
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api, { endpoints } from '../services/api';
import dayjs from 'dayjs';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;
const { Option } = Select;

const HOT_TOPIC_PLATFORMS = [
  { key: 'weibo', label: '微博', name: '微博热搜', taskPlatform: 'weibo' },
  { key: 'bilibili', label: 'B站', name: 'B站热搜', taskPlatform: 'bilibili' },
  { key: 'douyin', label: '抖音', name: '抖音热榜', taskPlatform: 'douyin' },
] as const;

interface HotTopic {
  id: number;
  title: string;
  hot_value: string;
  url: string;
  rank: number;
  category?: string; 
}

interface SystemStats {
  totalTasks: number;
}

export interface DashboardMetrics {
  totalCollected: number;
  activeTasks: number;
  todayNewTasks: number;
}

export const formatDashboardMetricValue = (value: number): string => {
  if (value >= 10000) {
    return `${(value / 10000).toFixed(1)} 万`;
  }
  return `${value}`;
};

const fetchDashboardMetrics = async (): Promise<DashboardMetrics> => {
  const response = await api.get(endpoints.dashboard.metrics);
  return response.data;
};

export const dashboardMetricsQueryOptions = {
  queryKey: ['dashboard-metrics'] as const,
  refetchInterval: 60000,
  refetchIntervalInBackground: true,
  refetchOnWindowFocus: false,
};

export const DashboardMetricsSection: React.FC<{ totalTasks: number }> = ({ totalTasks }) => {
  const { data, isLoading, isError } = useQuery({
    ...dashboardMetricsQueryOptions,
    queryFn: fetchDashboardMetrics,
  });

  const renderMetricCard = (
    title: string,
    value: number | undefined,
    testId: string,
    prefix: React.ReactNode,
  ) => {
    if (isLoading) {
      return (
        <Card className="hover-card">
          <div data-testid={`${testId}-loading`}>
            <Skeleton active paragraph={false} title={{ width: '60%' }} />
          </div>
        </Card>
      );
    }

    if (isError) {
      return (
        <Card className="hover-card">
          <Alert
            data-testid={`${testId}-error`}
            type="error"
            showIcon
            message={`${title}加载失败`}
          />
        </Card>
      );
    }

    return (
      <Card className="hover-card">
        <Statistic
          title={title}
          value={formatDashboardMetricValue(value ?? 0)}
          prefix={prefix}
        />
      </Card>
    );
  };

  return (
    <>
      <Col xs={24} sm={12} lg={6}>
        <Card className="hover-card">
          <Statistic
            title="已分析话题"
            value={totalTasks}
            prefix={<ProjectOutlined style={{ color: '#1890ff' }} />}
          />
        </Card>
      </Col>
      <Col xs={24} sm={12} lg={6}>
        {renderMetricCard(
          '累计采集数据',
          data?.totalCollected,
          'total-collected',
          <FileTextOutlined style={{ color: '#52c41a' }} />,
        )}
      </Col>
      <Col xs={24} sm={12} lg={6}>
        {renderMetricCard(
          '活跃监测任务',
          data?.activeTasks,
          'active-tasks',
          <SyncOutlined spin={(data?.activeTasks ?? 0) > 0} style={{ color: '#faad14' }} />,
        )}
      </Col>
      <Col xs={24} sm={12} lg={6}>
        {renderMetricCard(
          '今日新增任务',
          data?.todayNewTasks,
          'today-new-tasks',
          <RiseOutlined style={{ color: '#f5222d' }} />,
        )}
      </Col>
    </>
  );
};

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [hotTopics, setHotTopics] = useState<HotTopic[]>([]);
  const [hotTopicSource, setHotTopicSource] = useState<(typeof HOT_TOPIC_PLATFORMS)[number]['key']>('weibo');
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [systemConfig, setSystemConfig] = useState({
    site_name: '社交媒体热点话题分析',
    site_description: '实时监控全网热点，深度分析舆情态势，智能解读用户情感。'
  });
  const [systemStats, setSystemStats] = useState<SystemStats>({
    totalTasks: 0
  });
  const [loading, setLoading] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [form] = Form.useForm();
  const currentHotTopicPlatform =
    HOT_TOPIC_PLATFORMS.find((item) => item.key === hotTopicSource) ?? HOT_TOPIC_PLATFORMS[0];

  // 获取热搜榜单
  const fetchHotTopics = async () => {
    try {
      const response = await api.get(endpoints.hotTopics.list, {
        params: { source: hotTopicSource, limit: 10 }
      });
      if (response.data && response.data.items) {
        setHotTopics(response.data.items);
      }
    } catch (error) {
      console.error('获取热搜榜单失败:', error);
      setHotTopics([]);
    }
  };

  // 获取系统统计和最近任务
  const fetchSystemData = async () => {
    try {
      // 同时获取任务列表和系统设置
       const [tasksRes, settingsRes] = await Promise.all([
         api.get(endpoints.tasks, { params: { limit: 5 } }),
        api.get(endpoints.settings)
      ]);

      if (tasksRes.data && tasksRes.data.tasks) {
         const tasks = tasksRes.data.tasks;
         setRecentTasks(tasks);
         setSystemStats({
            totalTasks: tasksRes.data.total ?? tasks.length
         });
      }

      if (settingsRes.data && settingsRes.data.system) {
        setSystemConfig({
          site_name: settingsRes.data.system.site_name || '社交媒体热点话题分析',
          site_description: settingsRes.data.system.site_description || '实时监控全网热点，深度分析舆情态势，智能解读用户情感。'
        });
      }
    } catch (error) {
      console.error('获取系统数据失败:', error);
    }
  };

  useEffect(() => {
    fetchHotTopics();
  }, [hotTopicSource]);

  useEffect(() => {
    fetchSystemData();
    
    // 首页定时刷新热点与任务统计，保持总览数据具备一定实时性。
    const interval = setInterval(() => {
      fetchHotTopics();
      fetchSystemData();
    }, 30000);
    
    return () => clearInterval(interval);
  }, [hotTopicSource]);

  const handleHotTopicClick = (topic: HotTopic) => {
    // 热点榜单可直接带入任务创建表单，缩短“发现热点”到“启动分析”的操作链路。
    form.setFieldsValue({
      keyword: topic.title,
      platform: currentHotTopicPlatform.taskPlatform,
      post_count: 100,
      comment_count: 1000
    });
    setIsModalVisible(true);
  };

  const handleSearch = (value: string) => {
    if (!value.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }
    form.setFieldsValue({
      keyword: value.trim(),
      platform: 'weibo',
      post_count: 100,
      comment_count: 1000
    });
    setIsModalVisible(true);
  };

  const handleCreateTask = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await api.post(endpoints.tasks, values);
      message.success('任务创建成功！');
      setIsModalVisible(false);
      navigate('/tasks');
    } catch (error: any) {
      console.error('创建任务失败:', error);
      const errorMsg = error.response?.data?.message || '创建任务失败';
      message.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '0 0 24px 0' }}>
      <Spin spinning={loading}>
        {/* Hero Section */}
        <div className="hero-gradient">
          <Row align="middle" gutter={[32, 32]}>
            <Col xs={24} md={16}>
              <Title level={1} style={{ color: 'white', marginBottom: 16 }}>
                {systemConfig.site_name}
              </Title>
              <Paragraph style={{ color: 'rgba(255,255,255,0.9)', fontSize: '18px', marginBottom: 24 }}>
                {systemConfig.site_description}
              </Paragraph>
              <div style={{ display: 'flex', gap: '12px' }}>
                <Search
                  placeholder="输入关键词开启深度分析..."
                  enterButton="立即分析"
                  size="large"
                  style={{ maxWidth: 450 }}
                  onSearch={handleSearch}
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                />
              </div>
            </Col>
            <Col xs={0} md={8} style={{ textAlign: 'center' }}>
              <BarChartOutlined style={{ fontSize: '180px', color: 'rgba(255,255,255,0.2)' }} />
            </Col>
          </Row>
        </div>

        {/* System Stats Section */}
        <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
          <DashboardMetricsSection totalTasks={systemStats.totalTasks} />
        </Row>

        <Row gutter={[24, 24]}>
          {/* Left Column: Hot Topics */}
          <Col xs={24} lg={16}>
            <Card 
              title={
                <div className="hot-topic-card-header">
                  <Space size="middle">
                    <div className="hot-topic-card-icon">
                      <FireOutlined />
                    </div>
                    <div>
                      <Text strong style={{ fontSize: 18, display: 'block' }}>
                        实时热搜榜单 ({currentHotTopicPlatform.label})
                      </Text>
                      <Text type="secondary">
                        一键切换已接入平台，快速查看不同站点的最新热点
                      </Text>
                    </div>
                  </Space>
                </div>
              }
              extra={
                <Space wrap>
                  <Segmented
                    value={hotTopicSource}
                    onChange={(value) => setHotTopicSource(value as (typeof HOT_TOPIC_PLATFORMS)[number]['key'])}
                    options={HOT_TOPIC_PLATFORMS.map((item) => ({
                      label: item.label,
                      value: item.key,
                    }))}
                  />
                  <Button onClick={fetchHotTopics}>刷新榜单</Button>
                  <Button type="primary" ghost onClick={() => navigate('/hot-topics')}>
                    查看全网热点
                  </Button>
                </Space>
              }
              className="hover-card"
            >
              <div className="hot-topic-card-summary">
                <Tag color="processing">{currentHotTopicPlatform.name}</Tag>
                <Text type="secondary">当前展示前 30 条热点，可直接创建分析任务</Text>
              </div>
              {hotTopics.length > 0 ? (
                <List
                  itemLayout="horizontal"
                  dataSource={hotTopics}
                  renderItem={(item) => (
                    <List.Item className="hot-topic-list-item">
                      <List.Item.Meta
                        avatar={
                          <div className={`hot-topic-rank-badge${item.rank <= 3 ? ' is-top' : ''}`}>
                            {item.rank}
                          </div>
                        }
                        title={
                          <Space size={[8, 8]} wrap>
                            <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
                              <Text strong>{item.title}</Text>
                            </a>
                            {item.rank <= 3 && <Tag color="error">热</Tag>}
                            {item.hot_value && <Tag>{item.hot_value}</Tag>}
                          </Space>
                        }
                        description={
                          <Space size="middle" wrap>
                            <Text type="secondary">
                              <RiseOutlined /> 热度值: {item.hot_value || '暂无'}
                            </Text>
                            <Text type="secondary">来源: {currentHotTopicPlatform.label}</Text>
                          </Space>
                        }
                      />
                      <Space wrap>
                        <Button
                          size="small"
                          onClick={() => window.open(item.url, '_blank', 'noopener,noreferrer')}
                        >
                          查看原文
                        </Button>
                        <Button
                          type="primary"
                          ghost
                          size="small"
                          onClick={() => handleHotTopicClick(item)}
                          icon={<SearchOutlined />}
                        >
                          分析话题
                        </Button>
                      </Space>
                    </List.Item>
                  )}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={`暂无${currentHotTopicPlatform.label}热点数据`}
                />
              )}
            </Card>
          </Col>

          {/* Right Column: Recent Tasks & Quick Actions */}
          <Col xs={24} lg={8}>
            <Card 
              title={<span><ClockCircleOutlined style={{ marginRight: 8 }} />最近分析任务</span>}
              className="hover-card"
              style={{ marginBottom: 24 }}
            >
              {recentTasks.length > 0 ? (
                <List
                  dataSource={recentTasks}
                  renderItem={(item) => (
                    <List.Item
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate('/analysis', { state: { taskId: item.id } })}
                    >
                      <List.Item.Meta
                        avatar={
                          <Avatar 
                            icon={item.status === 'completed' ? <CheckCircleOutlined /> : <SyncOutlined spin />} 
                            style={{ backgroundColor: item.status === 'completed' ? '#52c41a' : '#1890ff' }}
                          />
                        }
                        title={<Text strong>{item.keyword}</Text>}
                        description={
                          <Space split={<Divider type="vertical" />}>
                            <Text type="secondary" style={{ fontSize: '12px' }}>{item.platform}</Text>
                            <Text type="secondary" style={{ fontSize: '12px' }}>{dayjs(item.created_at).format('MM-DD HH:mm')}</Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <Empty description="暂无最近任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
              <Button block type="dashed" style={{ marginTop: 16 }} onClick={() => navigate('/tasks')}>
                查看全部任务
              </Button>
            </Card>

            <Card title="智能辅助" className="hover-card">
              <Row gutter={[12, 12]}>
                <Col span={12}>
                  <Button 
                    block 
                    style={{ height: '80px', display: 'flex', flexDirection: 'column', gap: 4 }}
                    onClick={() => navigate('/qa')}
                  >
                    <RobotOutlined style={{ fontSize: 24, color: '#722ed1' }} />
                    <span>智能问答</span>
                  </Button>
                </Col>
                <Col span={12}>
                  <Button 
                    block 
                    style={{ height: '80px', display: 'flex', flexDirection: 'column', gap: 4 }}
                    onClick={() => navigate('/hot-topics')}
                  >
                    <FireOutlined style={{ fontSize: 24, color: '#fa8c16' }} />
                    <span>全网热点</span>
                  </Button>
                </Col>
                <Col span={12}>
                  <Button 
                    block 
                    style={{ height: '80px', display: 'flex', flexDirection: 'column', gap: 4 }}
                    onClick={() => navigate('/analysis')}
                  >
                    <BarChartOutlined style={{ fontSize: 24, color: '#13c2c2' }} />
                    <span>舆情分析</span>
                  </Button>
                </Col>
                <Col span={12}>
                  <Button 
                    block 
                    style={{ height: '80px', display: 'flex', flexDirection: 'column', gap: 4 }}
                    onClick={() => navigate('/settings')}
                  >
                    <SettingOutlined style={{ fontSize: 24, color: '#595959' }} />
                    <span>系统设置</span>
                  </Button>
                </Col>
              </Row>
            </Card>
          </Col>
        </Row>

        {/* Task Creation Modal */}
        <Modal
          title="创建分析任务"
          open={isModalVisible}
          onOk={handleCreateTask}
          onCancel={() => setIsModalVisible(false)}
          confirmLoading={loading}
          okText="立即开启分析"
          cancelText="取消"
        >
          <Form form={form} layout="vertical">
            <Form.Item
              name="platform"
              label="数据平台"
              rules={[{ required: true, message: '请选择数据源平台' }]}
              initialValue="weibo"
            >
              <Select>
                <Option value="weibo">新浪微博</Option>
                <Option value="bilibili">哔哩哔哩 (Bilibili)</Option>
                <Option value="douyin">抖音 (Douyin)</Option>
              </Select>
            </Form.Item>
            <Form.Item
              name="keyword"
              label="搜索关键词"
              rules={[{ required: true, message: '请输入要分析的关键词' }]}
            >
              <Input placeholder="例如: 人工智能, 气候变化, 某品牌评价..." />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="post_count"
                  label="采集帖子数"
                  initialValue={100}
                >
                  <InputNumber min={1} max={1000} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="comment_count"
                  label="每贴评论数"
                  initialValue={1000}
                >
                  <InputNumber min={1} max={5000} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Modal>
      </Spin>
    </div>
  );
};

export default HomePage;
