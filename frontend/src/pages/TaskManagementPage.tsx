import React, { useState, useEffect } from 'react';
import { 
  Card, 
  Table, 
  Button, 
  Space, 
  Modal, 
  Form, 
  Input, 
  Select, 
  Progress,
  Badge,
  message,
  Row,
  Col,
  Statistic,
  Typography,
  InputNumber
} from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  DeleteOutlined,
  EyeOutlined,
  ReloadOutlined
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import api, { endpoints } from '../services/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { Option } = Select;

interface Task {
  id: number;
  platform: string;
  keyword: string;
  post_count: number;
  comment_count: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'paused';
  progress: number;
  progress_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  sentiment_distribution?: {
    positive: number;
    neutral: number;
    negative: number;
  };
}

const TaskManagementPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  // 获取任务列表
  const fetchTasks = async () => {
    try {
      const response = await api.get(endpoints.tasks);
      if (response.data && response.data.tasks) {
        setTasks(response.data.tasks);
      }
    } catch (error) {
      console.error('获取任务列表失败:', error);
      message.error('获取任务列表失败');
    }
  };

  useEffect(() => {
    fetchTasks();
    
    // 通过定时轮询更新任务状态，使界面能够实时反映后台执行进度。
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  // 创建新任务
  const handleCreateTask = async (values: any) => {
    try {
      // 前端仅提交任务参数，由后端异步完成采集与分析流程。
      await api.post(endpoints.tasks, {
        platform: values.platform,
        keyword: values.keyword,
        post_count: values.post_count,
        comment_count: values.comment_count
      });
      
      message.success('任务创建成功');
      setModalVisible(false);
      form.resetFields();
      fetchTasks(); // Refresh list
      
    } catch (error: any) {
      const errorMsg = error.response?.data?.error || '创建任务失败';
      message.error(errorMsg);
      console.error('创建任务失败:', error);
    }
  };

  // 删除任务
  const handleDeleteTask = async (id: number) => {
    try {
      Modal.confirm({
        title: '确认删除',
        content: '确定要删除这个任务吗？相关数据也将被清除。',
        onOk: async () => {
          await api.delete(`${endpoints.tasks}/${id}`);
          message.success('任务删除成功');
          fetchTasks();
        }
      });
    } catch (error) {
      message.error('任务删除失败');
    }
  };

  // 暂停/恢复任务
  const handleTaskAction = async (id: number, action: 'pause' | 'resume' | 'restart') => {
    try {
      await api.post(`${endpoints.tasks}/${id}/action`, { action });
      message.success(`操作成功: ${action}`);
      fetchTasks();
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 处理搜索关键词
  useEffect(() => {
    if (location.state?.keyword) {
      form.setFieldsValue({ keyword: location.state.keyword });
      setModalVisible(true);
    }
  }, [location.state, form]);

  // 表格列定义
  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      render: (platform: string) => {
        const platformNames: { [key: string]: string } = {
          'weibo': '微博',
          'douyin': '抖音',
          'bilibili': 'B站',
          'xhs': '小红书'
        };
        return platformNames[platform] || platform;
      }
    },
    {
      title: '关键词',
      dataIndex: 'keyword',
      key: 'keyword',
      render: (text: string) => <Text strong>{text}</Text>
    },
    {
      title: '目标帖子数',
      dataIndex: 'post_count',
      key: 'post_count',
      render: (count: number) => count?.toLocaleString() || '-'
    },
    {
      title: '目标评论总数',
      dataIndex: 'comment_count',
      key: 'comment_count',
      render: (count: number) => count?.toLocaleString() || '-'
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const statusConfig: { [key: string]: { color: string; text: string } } = {
          'pending': { color: 'default', text: '待处理' },
          'running': { color: 'processing', text: '进行中' },
          'completed': { color: 'success', text: '已完成' },
          'failed': { color: 'error', text: '失败' }
        };
        const config = statusConfig[status] || { color: 'default', text: status };
        return <Badge status={config.color as any} text={config.text} />;
      }
    },
    {
      title: '进度',
      key: 'progress',
      width: 250,
      render: (_: any, record: Task) => (
        <div style={{ width: '100%' }}>
          {/* 进度条用于展示任务所处阶段，文字说明用于补充当前执行步骤。 */}
          <Progress 
            percent={record.progress} 
            status={
              record.status === 'failed' ? 'exception' : 
              record.status === 'completed' ? 'success' : 
              record.status === 'paused' ? 'normal' : 'active'
            }
            size="small"
          />
          {record.status === 'running' && record.progress_message && (
             <div style={{ fontSize: '12px', color: '#888', marginTop: 4 }}>
                {record.progress_message}
             </div>
          )}
          {record.status === 'failed' && (
            <div style={{ fontSize: '12px', color: 'red', marginTop: 4 }}>
               任务失败
            </div>
          )}
        </div>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-'
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Task) => (
        <Space size="small">
          <Button
            type="link"
            icon={<EyeOutlined />}
            size="small"
            onClick={() => navigate('/analysis', { state: { taskId: record.id } })}
            disabled={record.status === 'pending' || record.status === 'failed'}
          >
            分析
          </Button>
          
          {record.status === 'running' && (
            <Button 
              type="text" 
              icon={<PauseCircleOutlined />} 
              size="small"
              onClick={() => handleTaskAction(record.id, 'pause')}
            >
              暂停
            </Button>
          )}
          
          {record.status === 'paused' && (
            <Button 
              type="text" 
              icon={<PlayCircleOutlined />} 
              size="small"
              onClick={() => handleTaskAction(record.id, 'resume')}
            >
              恢复
            </Button>
          )}
          
          {(record.status === 'failed' || record.status === 'completed') && (
             <Button 
              type="text" 
              icon={<ReloadOutlined />} 
              size="small"
              onClick={() => handleTaskAction(record.id, 'restart')}
            >
              重试
            </Button>
          )}

          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            size="small"
            onClick={() => handleDeleteTask(record.id)}
          >
            删除
          </Button>
        </Space>
      )
    }
  ];

  // 获取状态统计
  const getStatusStats = () => {
    const stats = {
      pending: tasks.filter(t => t.status === 'pending').length,
      running: tasks.filter(t => t.status === 'running').length,
      completed: tasks.filter(t => t.status === 'completed').length,
      failed: tasks.filter(t => t.status === 'failed').length
    };
    return stats;
  };

  const statusStats = getStatusStats();

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: '24px' }}>
        <Title level={2}>任务管理</Title>
        <Text type="secondary">创建和管理社交媒体数据爬取任务</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="待处理"
              value={statusStats.pending}
              valueStyle={{ color: '#999' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="进行中"
              value={statusStats.running}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="已完成"
              value={statusStats.completed}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="失败"
              value={statusStats.failed}
              valueStyle={{ color: '#f5222d' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 操作栏 */}
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between' }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalVisible(true)}
        >
          创建新任务
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={fetchTasks}
        >
          刷新
        </Button>
      </div>

      {/* 任务列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条记录`
          }}
        />
      </Card>

      {/* 创建任务模态框 */}
      <Modal
        title="创建新任务"
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        onOk={() => form.submit()}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreateTask}
        >
          <Form.Item
            name="platform"
            label="平台"
            rules={[{ required: true, message: '请选择平台' }]}
            initialValue="weibo"
          >
            <Select placeholder="选择要爬取的平台">
              <Option value="weibo">微博</Option>
              <Option value="douyin">抖音</Option>
              <Option value="bilibili">B站</Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="keyword"
            label="关键词"
            rules={[{ required: true, message: '请输入关键词' }]}
          >
            <Input placeholder="输入要搜索的关键词" />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="post_count"
                label="目标帖子数"
                initialValue={100}
                rules={[{ required: true, message: '请输入目标帖子数' }]}
              >
                <InputNumber min={1} max={1000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="comment_count"
                label="目标评论总数"
                initialValue={1000}
                rules={[{ required: true, message: '请输入目标评论总数' }]}
              >
                <InputNumber min={1} max={10000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};

export default TaskManagementPage;
