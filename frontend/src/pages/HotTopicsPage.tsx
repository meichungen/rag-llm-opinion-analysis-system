import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Button, Space, Select, message, Typography, InputNumber, Modal, Form, Divider } from 'antd';
import { ReloadOutlined, SettingOutlined, LinkOutlined, RobotOutlined, FilePdfOutlined, FileWordOutlined } from '@ant-design/icons';
import api, { endpoints } from '../services/api';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;
const { Option } = Select;

interface HotTopic {
  id: number;
  source: string;
  title: string;
  url: string;
  rank: number;
  hot_value: string;
  created_at: string;
  extra_data?: any;
}

const HotTopicsPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<HotTopic[]>([]);
  const [source, setSource] = useState('weibo');
  const [sourceList, setSourceList] = useState<{id: string, name: string}[]>([]);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [settingsVisible, setSettingsVisible] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  
  // AI Analysis States
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [analysisModalVisible, setAnalysisModalVisible] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<{summary: string, analysis: string, title: string} | null>(null);
  
  const [form] = Form.useForm();

  useEffect(() => {
    const fetchSources = async () => {
      try {
        const res = await api.get(endpoints.hotTopics.sources);
        if (res.data) {
          setSourceList(res.data);
        }
      } catch (error) {
        console.error('Failed to fetch sources:', error);
      }
    };
    fetchSources();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await api.get(endpoints.hotTopics.list, { params: { source } });
      setData(res.data.items);
      setUpdatedAt(res.data.updated_at);
    } catch (error) {
      message.error('获取热点数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [source]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.post(endpoints.hotTopics.refresh, null, { params: { source } });
      message.success('已触发刷新，请稍后查看');
      setRefreshing(false);
      window.setTimeout(() => {
        fetchData();
      }, 3000);
    } catch (error) {
      message.error('刷新失败');
      setRefreshing(false);
    }
  };

  const handleSettingsSave = async (values: any) => {
    try {
      await api.post(endpoints.hotTopics.settings, { interval_minutes: values.interval });
      message.success('设置已保存');
      setSettingsVisible(false);
    } catch (error) {
      message.error('保存设置失败');
    }
  };

  const handleAnalyze = async (record: HotTopic) => {
    setAnalyzingId(record.id);
    try {
      const res = await api.post(endpoints.hotTopics.analyze, {
        title: record.title,
        url: record.url,
        source: record.source,
        summary: record.extra_data?.hover || record.extra_data?.desc || '',
      });
      setAnalysisResult({ ...res.data, title: record.title });
      setAnalysisModalVisible(true);
    } catch (error) {
      message.error('AI 分析失败，请稍后重试');
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleExport = async (format: 'pdf' | 'word') => {
    if (!analysisResult) return;
    try {
      const response = await api.post(endpoints.hotTopics.export, {
        title: analysisResult.title,
        summary: analysisResult.summary,
        analysis: analysisResult.analysis,
        format: format
      }, {
        responseType: 'blob'
      });
      
      const blob = new Blob([response.data], { type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `report_${analysisResult.title.substring(0, 10)}.${format === 'word' ? 'docx' : 'pdf'}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error) {
      message.error('导出失败');
    }
  };

  const columns: ColumnsType<HotTopic> = [
    {
      title: '排名',
      dataIndex: 'rank',
      key: 'rank',
      width: 80,
      render: (rank) => {
        let color = 'default';
        if (rank === 1) color = 'red';
        else if (rank === 2) color = 'volcano';
        else if (rank === 3) color = 'orange';
        return <Tag color={color}>{rank}</Tag>;
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (text, record) => (
        <a href={record.url} target="_blank" rel="noopener noreferrer">
          {text} <LinkOutlined />
        </a>
      ),
    },
    {
      title: '获取时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date) => new Date(date).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Button 
            type="link" 
            icon={<RobotOutlined />} 
            onClick={() => handleAnalyze(record)}
            loading={analyzingId === record.id}
        >
            AI 分析
        </Button>
      )
    }
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={2} style={{ margin: 0 }}>全网热点追踪</Title>
          <Space>
            <Select value={source} onChange={setSource} style={{ width: 150 }}>
              {sourceList.map(s => (
                <Option key={s.id} value={s.id}>{s.name}</Option>
              ))}
              {!sourceList.length && <Option value="weibo">微博热搜</Option>}
            </Select>
            <Button 
              icon={<ReloadOutlined spin={refreshing} />} 
              onClick={handleRefresh}
              loading={refreshing}
            >
              刷新
            </Button>
            <Button icon={<SettingOutlined />} onClick={() => setSettingsVisible(true)}>
              设置
            </Button>
          </Space>
        </div>

        <Card>
          <Table 
            columns={columns} 
            dataSource={data} 
            rowKey="id" 
            loading={loading}
            pagination={{ pageSize: 50 }}
            footer={() => updatedAt ? `上次更新时间: ${new Date(updatedAt).toLocaleString()}` : null}
          />
        </Card>
      </Space>

      {/* Settings Modal */}
      <Modal
        title="自动推送设置"
        open={settingsVisible}
        onCancel={() => setSettingsVisible(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={handleSettingsSave} layout="vertical" initialValues={{ interval: 60 }}>
          <Form.Item 
            name="interval" 
            label="更新频率 (分钟)" 
            rules={[{ required: true, message: '请输入更新频率' }]}
          >
            <InputNumber min={5} max={1440} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">系统将按照设定的时间间隔自动获取最新热点数据。</Text>
        </Form>
      </Modal>

      {/* AI Analysis Modal */}
      <Modal
        title={
          <Space>
            <RobotOutlined style={{ color: '#1890ff' }} />
            <span>AI 深度分析</span>
          </Space>
        }
        open={analysisModalVisible}
        onCancel={() => setAnalysisModalVisible(false)}
        width={800}
        footer={[
          <Button key="close" onClick={() => setAnalysisModalVisible(false)}>
            关闭
          </Button>,
          <Button key="pdf" icon={<FilePdfOutlined />} onClick={() => handleExport('pdf')}>
            导出 PDF
          </Button>,
          <Button key="word" icon={<FileWordOutlined />} onClick={() => handleExport('word')}>
            导出 Word
          </Button>
        ]}
      >
        {analysisResult && (
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            <Title level={4}>{analysisResult.title}</Title>
            <Divider orientation="left">内容提炼</Divider>
            <Card style={{ background: '#f5f5f5' }} bordered={false}>
              <Text>{analysisResult.summary}</Text>
            </Card>
            
            <Divider orientation="left">智能解读</Divider>
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>
              {analysisResult.analysis}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default HotTopicsPage;
