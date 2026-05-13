import React, { useState, useEffect } from 'react';
import { 
  Card, 
  Row, 
  Col, 
  Statistic, 
  Typography,
  Select,
  Tabs,
  Table,
  Tag,
  Empty,
  Spin,
  Button,
  Radio,
  InputNumber,
  Form,
  Space,
  message,
  Alert,
  Descriptions,
  Divider,
} from 'antd';
import { 
  PieChartOutlined, 
  LineChartOutlined,
  CloudOutlined,
  DotChartOutlined,
  TableOutlined,
  ReloadOutlined,
  FilePdfOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import 'echarts-wordcloud';
import { useLocation } from 'react-router-dom';
import api, { endpoints } from '../services/api';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

interface AnalysisData {
  sentiment_distribution: {
    positive: number;
    neutral: number;
    negative: number;
  };
  trend_data: Array<{
    date: string;
    positive: number;
    neutral: number;
    negative: number;
  }>;
  confidence_stats: {
    mean: number;
  };
}

interface TaskRiskFingerprint {
  code: string;
  message: string;
}

interface TaskWarning {
  scope: string;
  message: string;
  risk_fingerprints?: TaskRiskFingerprint[];
}

interface TaskDetailData {
  id: number;
  platform: string;
  keyword: string;
  status: string;
  progress: number;
  progress_message?: string;
  post_count: number;
  comment_count: number;
  post_count_actual?: number;
  comment_count_actual?: number;
  warnings?: TaskWarning[];
  risk_fingerprints?: TaskRiskFingerprint[];
  diagnostics?: Record<string, any>;
}

const RISK_LABELS: Record<string, string> = {
  bilibili_412: '412 风控',
  captcha: '验证码',
  login_required: '登录失效',
  empty_json: '空返回/非 JSON',
  blocked: '请求拦截',
  wbi_failed: 'WBI 失败',
};

const AnalysisPage: React.FC = () => {
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [analysisData, setAnalysisData] = useState<AnalysisData | null>(null);
  const [selectedTask, setSelectedTask] = useState<number | null>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [taskDetail, setTaskDetail] = useState<TaskDetailData | null>(null);
  
  // Word Cloud State
  const [wordCloudData, setWordCloudData] = useState<{ name: string; value: number }[]>([]);
  const [wordCloudLoading, setWordCloudLoading] = useState(false);
  const [wordCloudConfig, setWordCloudConfig] = useState({
    sourceType: 'comments',
    limit: 100
  });

  // LDA State
  const [ldaData, setLdaData] = useState<any[]>([]);
  const [ldaLoading, setLdaLoading] = useState(false);
  const [ldaConfig, setLdaConfig] = useState({
    sourceType: 'comments',
    numTopics: 5
  });

  // Data Preview State
  const [previewData, setPreviewData] = useState<{ items: any[], total: number }>({ items: [], total: 0 });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewConfig, setPreviewConfig] = useState<{
    type: string;
    page: number;
    perPage: number;
    sentiment?: string;
  }>({
    type: 'comments',
    page: 1,
    perPage: 10,
    sentiment: undefined
  });

  // AI Report State
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  // Fetch Tasks
  const fetchTasks = async () => {
    try {
      const response = await api.get(endpoints.tasks);
      if (response.data && response.data.tasks) {
        setTasks(response.data.tasks.filter((t: any) => t.status === 'completed'));
      }
    } catch (error) {
      console.error('获取任务列表失败:', error);
    }
  };

  // Fetch AI Report
  const fetchReport = async (taskId: number, forceRegenerate = false) => {
    try {
      setReportLoading(true);
      // 切换任务时仅读取已有报告；只有用户主动点击“重新生成”才触发后端生成。
      const response = forceRegenerate
        ? await api.post(`${endpoints.taskReport(taskId)}?force_regenerate=true`)
        : await api.get(endpoints.taskReport(taskId));
      if (response.data && response.data.report) {
        setReportContent(response.data.report);
      } else {
        setReportContent(null);
      }
    } catch (error) {
      console.error('获取AI报告失败:', error);
      if (forceRegenerate) {
        // 如果是强制生成失败，可以提示错误
      }
    } finally {
      setReportLoading(false);
    }
  };

  const fetchTaskDetail = async (taskId: number) => {
    try {
      const response = await api.get(`${endpoints.tasks}/${taskId}`);
      setTaskDetail(response.data);
    } catch (error) {
      console.error('获取任务详情失败:', error);
      setTaskDetail(null);
    }
  };

  // Fetch Word Cloud
  const fetchWordCloud = async (taskId: number) => {
    try {
      setWordCloudLoading(true);
      const response = await api.get(endpoints.analysis.wordcloud(taskId), {
        params: {
          source_type: wordCloudConfig.sourceType,
          limit: wordCloudConfig.limit
        }
      });
      setWordCloudData(response.data.words || []);
    } catch (error) {
      console.error('获取词云数据失败:', error);
      setWordCloudData([]);
    } finally {
      setWordCloudLoading(false);
    }
  };

  // Fetch LDA
  const fetchLDA = async (taskId: number) => {
    try {
      setLdaLoading(true);
      const response = await api.get(endpoints.analysis.lda(taskId), {
        params: {
          source_type: ldaConfig.sourceType,
          num_topics: ldaConfig.numTopics
        }
      });
      setLdaData(response.data.topics || []);
    } catch (error) {
      console.error('获取LDA数据失败:', error);
      setLdaData([]);
    } finally {
      setLdaLoading(false);
    }
  };

  // Fetch Preview
  const fetchPreview = async (taskId: number) => {
    try {
      setPreviewLoading(true);
      const response = await api.get(endpoints.analysis.preview(taskId), {
        params: {
          type: previewConfig.type,
          page: previewConfig.page,
          per_page: previewConfig.perPage,
          sentiment: previewConfig.sentiment
        }
      });
      setPreviewData({
        items: response.data.items || [],
        total: response.data.total || 0
      });
    } catch (error) {
      console.error('获取预览数据失败:', error);
      setPreviewData({ items: [], total: 0 });
    } finally {
      setPreviewLoading(false);
    }
  };

  // Fetch Analysis Data (Sentiment & Trend)
  const fetchAnalysisData = async (taskId: number) => {
    try {
      setLoading(true);
      const response = await api.get(endpoints.analysis.sentiment(taskId));
      const data = response.data;
      
      const sentimentDist = { positive: 0, neutral: 0, negative: 0 };
      let totalConfidence = 0;
      let count = 0;
      
      if (data.sentiment_distribution) {
        data.sentiment_distribution.forEach((item: any) => {
            if (item.label === 'positive') sentimentDist.positive = item.count;
            if (item.label === 'neutral') sentimentDist.neutral = item.count;
            if (item.label === 'negative') sentimentDist.negative = item.count;
            totalConfidence += item.confidence * item.count;
            count += item.count;
        });
      }

      // 趋势数据在前端按日期排序，确保折线图时间轴展示稳定。
      const sortedTrendData = (data.trend_data || []).sort((a: any, b: any) => 
        new Date(a.date).getTime() - new Date(b.date).getTime()
      );

      setAnalysisData({
        sentiment_distribution: sentimentDist,
        trend_data: sortedTrendData,
        confidence_stats: {
          mean: count > 0 ? totalConfidence / count : 0
        }
      });
    } catch (error) {
      console.error('获取分析数据失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const [downloading, setDownloading] = useState(false);

  const handleDownloadReport = async () => {
    if (!selectedTask) return;
    try {
      setDownloading(true);
      // Hardcoded URL to match the new endpoint
      const response = await api.get(`/analysis/report/${selectedTask}/pdf`, {
        responseType: 'blob'
      });
      
      // Create Blob URL and download
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      
      // Try to get filename from header
      let filename = `report_${selectedTask}.pdf`;
      const contentDisposition = response.headers['content-disposition'];
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename=(.+)/);
        if (filenameMatch && filenameMatch.length === 2) {
            filename = decodeURIComponent(filenameMatch[1]);
        }
      }
      
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.parentNode?.removeChild(link);
    } catch (error) {
      console.error('Download failed', error);
      message.error('下载失败');
    } finally {
      setDownloading(false);
    }
  };

  const sanitizeReportContent = (content: string) => {
    return content
      .replace(/\r\n/g, '\n')
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => !/^```[\w-]*$/.test(line) && line !== '```')
      .map((line) => line.replace(/^`{1,3}markdown\s*/i, '').replace(/^`{1,3}/, '').replace(/`{1,3}$/, '').trim())
      .map((line) => {
        const match = line.match(/^(\d+)[\.\u3001]\s*(.+)$/);
        if (match && match[2].length <= 30) {
          return `## ${match[1]}. ${match[2]}`;
        }
        return line;
      })
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  };

  const renderInlineMarkdown = (text: string) => {
    const nodes: React.ReactNode[] = [];
    const boldPattern = /(\*\*[^*]+\*\*|__[^_]+__)/g;
    let lastIndex = 0;

    for (const match of text.matchAll(boldPattern)) {
      const fullMatch = match[0];
      const index = match.index ?? 0;
      if (index > lastIndex) {
        nodes.push(text.slice(lastIndex, index));
      }
      nodes.push(
        <Text strong key={`${index}-${fullMatch}`}>
          {fullMatch.slice(2, -2)}
        </Text>,
      );
      lastIndex = index + fullMatch.length;
    }

    if (lastIndex < text.length) {
      nodes.push(text.slice(lastIndex));
    }

    return nodes.length ? nodes : text;
  };

  const renderReportContent = (content: string) => {
    const normalizedContent = sanitizeReportContent(content);

    // 按 Markdown 标题与列表规则渲染报告正文，提升页面可读性。
    return normalizedContent.split('\n').map((line, index) => {
      const text = line.trim();
      if (!text) {
        return <div key={index} style={{ height: 12 }} />;
      }
      if (text.startsWith('# ')) {
        return (
          <Title key={index} level={3} style={{ marginTop: 16, marginBottom: 12 }}>
            {renderInlineMarkdown(text.slice(2))}
          </Title>
        );
      }
      if (text.startsWith('## ')) {
        return (
          <Title key={index} level={4} style={{ marginTop: 16, marginBottom: 8 }}>
            {renderInlineMarkdown(text.slice(3))}
          </Title>
        );
      }
      if (text.startsWith('### ')) {
        return (
          <Title key={index} level={5} style={{ marginTop: 12, marginBottom: 8 }}>
            {renderInlineMarkdown(text.slice(4))}
          </Title>
        );
      }
      if (text.startsWith('- ') || text.startsWith('* ')) {
        return (
          <div key={index} style={{ marginBottom: 8, paddingLeft: 12 }}>
            • {renderInlineMarkdown(text.slice(2))}
          </div>
        );
      }
      if (/^\d+[\.\u3001]\s+/.test(text) && text.length <= 40) {
        return (
          <Title key={index} level={4} style={{ marginTop: 16, marginBottom: 8 }}>
            {renderInlineMarkdown(text.replace(/^\d+[\.\u3001]\s+/, ''))}
          </Title>
        );
      }
      return (
        <div key={index} style={{ marginBottom: 10, whiteSpace: 'pre-wrap' }}>
          {renderInlineMarkdown(text)}
        </div>
      );
    });
  };

  useEffect(() => {
    fetchTasks();
    const taskId = location.state?.taskId;
    if (taskId) {
      setSelectedTask(taskId);
    }
  }, [location]);

  useEffect(() => {
    if (selectedTask) {
      // Clear previous report
      setReportContent(null);
      fetchTaskDetail(selectedTask);
      // Try to fetch existing report
      fetchReport(selectedTask, false);
      
      fetchAnalysisData(selectedTask);
      fetchWordCloud(selectedTask);
      fetchLDA(selectedTask);
      fetchPreview(selectedTask);
    }
  }, [selectedTask]);

  // Watch for config changes
  useEffect(() => { if(selectedTask) fetchWordCloud(selectedTask); }, [wordCloudConfig]);
  useEffect(() => { if(selectedTask) fetchLDA(selectedTask); }, [ldaConfig]);
  useEffect(() => { if(selectedTask) fetchPreview(selectedTask); }, [previewConfig]);

  // Charts Options
  const getSentimentPieOption = () => {
    if (!analysisData) return {};
    return {
      title: { text: '情感分布', left: 'center' },
      tooltip: { trigger: 'item', formatter: '{a} <br/>{b}: {c} ({d}%)' },
      legend: { bottom: '5%', left: 'center' },
      series: [{
        name: '情感分布',
        type: 'pie',
        radius: ['40%', '70%'],
        itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, formatter: '{b}: {c} ({d}%)' },
        data: [
          { value: analysisData.sentiment_distribution.positive, name: '正面', itemStyle: { color: '#52c41a' } },
          { value: analysisData.sentiment_distribution.neutral, name: '中性', itemStyle: { color: '#faad14' } },
          { value: analysisData.sentiment_distribution.negative, name: '负面', itemStyle: { color: '#f5222d' } }
        ]
      }]
    };
  };

  const getSentimentTrendOption = () => {
    if (!analysisData) return {};
    const dates = analysisData.trend_data.map(item => item.date);
    return {
      title: { text: '情感趋势变化', left: 'center' },
      tooltip: { trigger: 'axis' },
      legend: { data: ['正面', '中性', '负面'], bottom: '5%' },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value' },
      series: [
        { name: '正面', type: 'line', smooth: true, data: analysisData.trend_data.map(item => item.positive), itemStyle: { color: '#52c41a' } },
        { name: '中性', type: 'line', smooth: true, data: analysisData.trend_data.map(item => item.neutral), itemStyle: { color: '#faad14' } },
        { name: '负面', type: 'line', smooth: true, data: analysisData.trend_data.map(item => item.negative), itemStyle: { color: '#f5222d' } }
      ]
    };
  };

  const getWordCloudOption = () => {
    return {
      title: { text: wordCloudConfig.sourceType === 'posts' ? '帖子热词云' : '评论热词云', left: 'center' },
      tooltip: { show: true },
      series: [{
        type: 'wordCloud',
        shape: 'circle',
        width: '90%',
        height: '80%',
        sizeRange: [12, 60],
        rotationRange: [-45, 45],
        textStyle: {
          fontFamily: 'sans-serif',
          fontWeight: 'bold',
          color: () => `rgb(${Math.round(Math.random() * 160)}, ${Math.round(Math.random() * 160)}, ${Math.round(Math.random() * 160)})`
        },
        data: wordCloudData
      }]
    };
  };

  const getLDAOption = () => {
    const data: any[] = [];
    const categories: string[] = [];
    const weights: number[] = [];
    
    ldaData.forEach((topic, index) => {
      const topicName = `Topic ${index + 1}`;
      categories.push(topicName);
      topic.keywords.forEach((kw: any) => {
        const weight = Number(kw.weight) || 0;
        weights.push(weight);
      });
    });

    const minWeight = weights.length ? Math.min(...weights) : 0;
    const maxWeight = weights.length ? Math.max(...weights) : 0;
    const sizeForWeight = (weight: number) => {
      if (maxWeight <= minWeight) {
        return 24;
      }
      const ratio = (weight - minWeight) / (maxWeight - minWeight);
      return 18 + ratio * 20;
    };

    ldaData.forEach((topic, index) => {
      topic.keywords.forEach((kw: any) => {
        const weight = Number(kw.weight) || 0;
        data.push([
          index, // x: topic index
          weight, // y: weight
          sizeForWeight(weight), // size
          kw.name, // label
          index // color index
        ]);
      });
    });

    return {
      title: { text: '主题-关键词分布气泡图', left: 'center' },
      tooltip: {
        formatter: (params: any) => {
          return `Topic ${params.value[0] + 1}<br/>Keyword: ${params.value[3]}<br/>Weight: ${params.value[1].toFixed(4)}`;
        }
      },
      xAxis: { 
        type: 'category', 
        data: categories,
        splitLine: { show: true }
      },
      yAxis: { 
        type: 'value', 
        name: '权重',
        splitLine: { show: false }
      },
      series: [{
        type: 'scatter',
        symbolSize: (data: any) => {
          return data[2];
        },
        data: data,
        itemStyle: {
            color: (params: any) => {
                const colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'];
                return colors[params.value[4] % colors.length];
            },
            opacity: 0.8,
        },
        label: {
            show: true,
            formatter: (params: any) => params.value[3],
            position: 'top',
            fontSize: 11
        }
      }]
    };
  };

  const columns = [
    { title: '内容', dataIndex: 'content', key: 'content', width: '50%', ellipsis: true },
    { title: '作者', dataIndex: 'author', key: 'author' },
    { title: '时间', dataIndex: 'time', key: 'time', render: (text: string) => text ? new Date(text).toLocaleString() : '-' },
    ...(previewConfig.type === 'comments' ? [{
      title: '情感',
      dataIndex: 'sentiment',
      key: 'sentiment',
      render: (sentiment: any) => {
        if (!sentiment) return <Tag>未分析</Tag>;
        const colors: any = { positive: 'green', neutral: 'orange', negative: 'red' };
        const labels: any = { positive: '正面', neutral: '中性', negative: '负面' };
        return <Tag color={colors[sentiment.label]}>{labels[sentiment.label]} ({(sentiment.confidence * 100).toFixed(0)}%)</Tag>;
      }
    }] : [])
  ];

  return (
    <div style={{ padding: '24px' }}>
      <Spin spinning={loading}>
        <div style={{ marginBottom: '24px' }}>
          <Row justify="space-between" align="middle">
            <Col>
              <Title level={2}>数据分析</Title>
              <Text type="secondary">查看和分析社交媒体数据的情感倾向</Text>
            </Col>
            <Col>
              <Space>
                <Select
                  placeholder="选择分析任务"
                  style={{ width: 200 }}
                  value={selectedTask}
                  onChange={(value) => setSelectedTask(value)}
                >
                  {tasks.map(task => (
                    <Select.Option key={task.id} value={task.id}>{task.keyword} ({task.platform})</Select.Option>
                  ))}
                </Select>
                <Button icon={<ReloadOutlined />} onClick={() => selectedTask && fetchAnalysisData(selectedTask)}>刷新</Button>
                <Button 
                  type="primary" 
                  danger
                  icon={<FilePdfOutlined />} 
                  loading={downloading}
                  onClick={handleDownloadReport}
                  disabled={!selectedTask}
                >
                  导出分析报告
                </Button>
              </Space>
            </Col>
          </Row>
        </div>

        {!analysisData ? (
          <Empty description="请选择要分析的任务" style={{ marginTop: '100px' }} />
        ) : (
          <>
            <Card style={{ marginBottom: 16 }} title="任务执行与风险摘要">
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={8}>
                  <Statistic title="任务状态" value={taskDetail?.status || '-'} />
                </Col>
                <Col xs={24} lg={8}>
                  <Statistic
                    title="帖子完成度"
                    value={`${taskDetail?.post_count_actual ?? 0} / ${taskDetail?.post_count ?? 0}`}
                  />
                </Col>
                <Col xs={24} lg={8}>
                  <Statistic
                    title="评论完成度"
                    value={`${taskDetail?.comment_count_actual ?? 0} / ${taskDetail?.comment_count ?? 0}`}
                  />
                </Col>
              </Row>
              <Divider />
              <Descriptions size="small" bordered column={2}>
                <Descriptions.Item label="平台">{taskDetail?.platform || '-'}</Descriptions.Item>
                <Descriptions.Item label="关键词">{taskDetail?.keyword || '-'}</Descriptions.Item>
                <Descriptions.Item label="进度">{taskDetail?.diagnostics?.progress ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="进度说明">{taskDetail?.progress_message || '-'}</Descriptions.Item>
              </Descriptions>
              <div style={{ marginTop: 16 }}>
                {taskDetail?.warnings?.length ? (
                  <Alert
                    type={taskDetail.status === 'failed' ? 'error' : 'warning'}
                    showIcon
                    message={`任务告警 ${taskDetail.warnings.length} 条`}
                    description={
                      <Space direction="vertical" size={6}>
                        {taskDetail.warnings.map((warning, index) => (
                          <div key={`${warning.scope}-${index}`}>
                            <Text strong>{warning.scope}:</Text> {warning.message}
                          </div>
                        ))}
                      </Space>
                    }
                  />
                ) : (
                  <Alert type="success" showIcon message="当前任务没有结构化风险告警" />
                )}
              </div>
              <div style={{ marginTop: 16 }}>
                <Text strong>风险指纹：</Text>
                <div style={{ marginTop: 8 }}>
                  {taskDetail?.risk_fingerprints?.length ? (
                    <Space wrap>
                      {taskDetail.risk_fingerprints.map((risk, index) => (
                        <Tag color="volcano" key={`${risk.code}-${index}`}>
                          {RISK_LABELS[risk.code] || risk.code}
                        </Tag>
                      ))}
                    </Space>
                  ) : (
                    <Text type="secondary">暂无已识别风控指纹</Text>
                  )}
                </div>
              </div>
            </Card>
            <Tabs defaultActiveKey="0">
            {/* 0. AI Report */}
            <TabPane tab={<span><FilePdfOutlined />智能分析报告</span>} key="0">
              <Card>
                <div style={{ minHeight: '300px' }}>
                  {!reportContent && !reportLoading ? (
                    <div style={{ textAlign: 'center', padding: '50px 0' }}>
                      <Empty description="暂无分析报告" />
                      <Button 
                        type="primary" 
                        icon={<CloudOutlined />} 
                        loading={reportLoading}
                        onClick={() => selectedTask && fetchReport(selectedTask, true)}
                        style={{ marginTop: 16 }}
                      >
                        生成 AI 分析报告
                      </Button>
                    </div>
                  ) : (
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
                        <Button 
                          icon={<ReloadOutlined />} 
                          loading={reportLoading}
                          onClick={() => selectedTask && fetchReport(selectedTask, true)}
                        >
                          重新生成
                        </Button>
                      </div>
                      <Spin spinning={reportLoading}>
                        <div style={{ 
                            padding: '24px', 
                            background: '#f9f9f9', 
                            borderRadius: '8px', 
                            lineHeight: '1.6',
                            fontSize: '16px',
                            fontFamily: 'sans-serif'
                        }}>
                            {reportContent ? renderReportContent(reportContent) : null}
                        </div>
                      </Spin>
                    </div>
                  )}
                </div>
              </Card>
            </TabPane>

            {/* 1. Word Cloud */}
            <TabPane tab={<span><CloudOutlined />词云分析</span>} key="1">
              <Card>
                <Form layout="inline" style={{ marginBottom: 20 }}>
                  <Form.Item label="分析对象">
                    <Radio.Group value={wordCloudConfig.sourceType} onChange={e => setWordCloudConfig({...wordCloudConfig, sourceType: e.target.value})}>
                      <Radio.Button value="posts">帖子内容</Radio.Button>
                      <Radio.Button value="comments">评论内容</Radio.Button>
                    </Radio.Group>
                  </Form.Item>
                  <Form.Item label="词汇数量">
                    <InputNumber min={20} max={500} value={wordCloudConfig.limit} onChange={val => setWordCloudConfig({...wordCloudConfig, limit: val || 100})} />
                  </Form.Item>
                </Form>
                <ReactECharts option={getWordCloudOption()} style={{ height: '500px' }} showLoading={wordCloudLoading} />
              </Card>
            </TabPane>

            {/* 2. LDA Topic Modeling */}
            <TabPane tab={<span><DotChartOutlined />LDA主题建模</span>} key="2">
              <Card>
                 <Form layout="inline" style={{ marginBottom: 20 }}>
                  <Form.Item label="分析对象">
                    <Radio.Group value={ldaConfig.sourceType} onChange={e => setLdaConfig({...ldaConfig, sourceType: e.target.value})}>
                      <Radio.Button value="posts">帖子内容</Radio.Button>
                      <Radio.Button value="comments">评论内容</Radio.Button>
                    </Radio.Group>
                  </Form.Item>
                  <Form.Item label="主题数量">
                    <InputNumber min={2} max={10} value={ldaConfig.numTopics} onChange={val => setLdaConfig({...ldaConfig, numTopics: val || 5})} />
                  </Form.Item>
                </Form>
                <ReactECharts option={getLDAOption()} style={{ height: '500px' }} showLoading={ldaLoading} />
              </Card>
            </TabPane>

            {/* 3. Data Preview */}
            <TabPane tab={<span><TableOutlined />数据预览</span>} key="3">
              <Card>
                 <Form layout="inline" style={{ marginBottom: 20 }}>
                  <Form.Item label="数据类型">
                    <Radio.Group value={previewConfig.type} onChange={e => setPreviewConfig({...previewConfig, type: e.target.value, page: 1})}>
                      <Radio.Button value="posts">帖子</Radio.Button>
                      <Radio.Button value="comments">评论</Radio.Button>
                    </Radio.Group>
                  </Form.Item>
                  {previewConfig.type === 'comments' && (
                    <Form.Item label="情感筛选">
                      <Select 
                        allowClear 
                        placeholder="全部情感" 
                        style={{ width: 120 }}
                        value={previewConfig.sentiment}
                        onChange={val => setPreviewConfig({...previewConfig, sentiment: val, page: 1})}
                      >
                        <Select.Option value="positive">正面</Select.Option>
                        <Select.Option value="neutral">中性</Select.Option>
                        <Select.Option value="negative">负面</Select.Option>
                      </Select>
                    </Form.Item>
                  )}
                </Form>
                <Table 
                  dataSource={previewData.items} 
                  columns={columns} 
                  rowKey="id" 
                  loading={previewLoading}
                  pagination={{
                    current: previewConfig.page,
                    pageSize: previewConfig.perPage,
                    total: previewData.total,
                    onChange: (page, pageSize) => setPreviewConfig({...previewConfig, page, perPage: pageSize || 10})
                  }}
                />
              </Card>
            </TabPane>

            {/* 4. Sentiment Distribution */}
            <TabPane tab={<span><PieChartOutlined />情感分布</span>} key="4">
              <Row gutter={[16, 16]}>
                  <Col xs={24} lg={12}>
                    <Card title="情感分布饼图">
                      <ReactECharts option={getSentimentPieOption()} style={{ height: '400px' }} />
                    </Card>
                  </Col>
                  <Col xs={24} lg={12}>
                    <Card title="情感分布统计">
                       <div style={{ padding: '20px' }}>
                        <Statistic title="正面情感" value={analysisData.sentiment_distribution.positive} valueStyle={{ color: '#52c41a' }} />
                        <Statistic title="中性情感" value={analysisData.sentiment_distribution.neutral} valueStyle={{ color: '#faad14' }} style={{ marginTop: 16 }} />
                        <Statistic title="负面情感" value={analysisData.sentiment_distribution.negative} valueStyle={{ color: '#f5222d' }} style={{ marginTop: 16 }} />
                        <Statistic title="平均置信度" value={(analysisData.confidence_stats.mean * 100).toFixed(1)} precision={1} suffix="%" valueStyle={{ color: '#1890ff' }} style={{ marginTop: 16 }} />
                      </div>
                    </Card>
                  </Col>
                </Row>
            </TabPane>

            {/* 5. Trend Analysis */}
            <TabPane tab={<span><LineChartOutlined />趋势分析</span>} key="5">
               <Card title="情感趋势变化">
                  <ReactECharts option={getSentimentTrendOption()} style={{ height: '400px' }} />
               </Card>
            </TabPane>
            </Tabs>
          </>
        )}
      </Spin>
    </div>
  );
};

export default AnalysisPage;
