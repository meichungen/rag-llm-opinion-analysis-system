import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Layout,
  List,
  Modal,
  Select,
  Space,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
  theme,
} from 'antd';
import {
  ClearOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExportOutlined,
  InfoCircleOutlined,
  RobotOutlined,
  SendOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import api, { endpoints } from '../services/api';

const { Header, Content } = Layout;
const { Text, Title } = Typography;
const { TextArea } = Input;

interface RiskFingerprint {
  code: string;
  message: string;
  platform?: string;
}

interface ToolWarning {
  scope?: string;
  message: string;
  risk_fingerprints?: RiskFingerprint[];
}

interface ToolObservation {
  success?: boolean;
  status?: 'success' | 'partial_success' | 'failed';
  platform?: string;
  keyword?: string;
  total_posts?: number;
  total_comments?: number;
  warnings?: ToolWarning[];
  diagnostics?: {
    requested_posts?: number;
    requested_comments?: number;
    fetched_posts?: number;
    fetched_comments?: number;
    risk_fingerprints?: RiskFingerprint[];
    cookie_health?: {
      health?: string;
      issues?: string[];
    };
    [key: string]: any;
  };
  message?: string;
  error?: string;
}

interface AgentTraceStep {
  step: number;
  thought?: string;
  action: string;
  parameters?: Record<string, any>;
  status: 'planned' | 'success' | 'failed' | 'blocked' | 'final';
  risk_level?: 'low' | 'medium' | 'high';
  observation_summary?: string;
  elapsed_ms?: number;
}

interface Message {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: string;
  used_tool?: string;
  decision_summary?: string;
  observation_summary?: string;
  short_memory_turns?: number;
  long_memory_hits?: number;
  tool_observation?: ToolObservation;
  agent_trace?: AgentTraceStep[];
  context?: any;
}

const TOOL_LABELS: Record<string, string> = {
  direct_answer: '直接回答',
  fetch_data: '数据查询',
  sentiment_analysis: '情感分析',
  topic_modeling: '主题建模',
  vector_search: '长期检索',
  crawl_data: '实时采集',
  summarize_crawled_data: '采集摘要',
};

const TOOL_COLORS: Record<string, string> = {
  direct_answer: 'default',
  fetch_data: 'blue',
  sentiment_analysis: 'green',
  topic_modeling: 'purple',
  vector_search: 'orange',
  crawl_data: 'red',
  summarize_crawled_data: 'cyan',
};

const STATUS_COLOR_MAP: Record<string, string> = {
  success: 'success',
  partial_success: 'warning',
  failed: 'error',
};

const STATUS_LABEL_MAP: Record<string, string> = {
  success: '成功',
  partial_success: '部分成功',
  failed: '失败',
};

const TRACE_STATUS_LABELS: Record<string, string> = {
  planned: '已规划',
  success: '成功',
  failed: '失败',
  blocked: '已阻止',
  final: '最终回答',
};

const TRACE_STATUS_COLOR: Record<string, string> = {
  planned: 'blue',
  success: 'green',
  failed: 'red',
  blocked: 'orange',
  final: 'gray',
};

const RISK_COLOR: Record<string, string> = {
  low: 'green',
  medium: 'orange',
  high: 'red',
};

const RISK_LABELS: Record<string, string> = {
  bilibili_412: '412 风控',
  captcha: '验证码',
  login_required: '登录失效',
  empty_json: '空返回/非 JSON',
  blocked: '请求拦截',
  wbi_failed: 'WBI 失败',
};

const predefinedQuestions = [
  '总结当前任务的主要发现',
  '用户对产品的主要反馈是什么？',
  '有哪些需要关注的负面情感？',
  '基于历史对话给出分析建议',
  '分析情感变化趋势',
];

const AgentPage: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<any[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [showContextModal, setShowContextModal] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const agentSessionRef = useRef(`agent-session-${Date.now()}`);
  const activeRequestRef = useRef<AbortController | null>(null);
  const activeAssistantRef = useRef<string | null>(null);
  const { token } = theme.useToken();

  const latestAssistantMessage = useMemo(
    () => [...messages].reverse().find((item) => item.type === 'assistant' && item.used_tool),
    [messages]
  );

  const aggregatedRiskFingerprints = useMemo(() => {
    const summary = new Map<string, { count: number; platforms: Set<string>; message: string }>();
    messages.forEach((msg) => {
      const fingerprints = msg.tool_observation?.diagnostics?.risk_fingerprints || [];
      fingerprints.forEach((item) => {
        const key = item.code || item.message;
        const current = summary.get(key) || {
          count: 0,
          platforms: new Set<string>(),
          message: item.message,
        };
        current.count += 1;
        if (item.platform) {
          current.platforms.add(item.platform);
        }
        summary.set(key, current);
      });
    });
    return Array.from(summary.entries()).map(([code, value]) => ({
      code,
      message: value.message,
      count: value.count,
      platforms: Array.from(value.platforms),
    }));
  }, [messages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    const fetchTasks = async () => {
      try {
        const response = await api.get(endpoints.tasks);
        if (response.data?.tasks) {
          setTasks(response.data.tasks);
        }
      } catch (error) {
        console.error('获取任务列表失败:', error);
      }
    };
    fetchTasks();
  }, []);

  useEffect(() => {
    return () => {
      activeRequestRef.current?.abort();
    };
  }, []);

  const cancelActiveRequest = (notice?: string) => {
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    setLoading(false);
    if (notice && activeAssistantRef.current) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === activeAssistantRef.current
            ? { ...msg, content: notice, context: { cancelled: true } }
            : msg
        )
      );
    }
    activeAssistantRef.current = null;
  };

  const buildBaseMessages = (content: string) => {
    if (!content.trim()) {
      message.warning('请输入问题');
      return null;
    }
    if (loading) {
      message.info('Agent 正在处理，请稍候');
      return null;
    }

    const assistantMsgId = `assistant-${Date.now()}`;
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      type: 'user',
      content,
      timestamp: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    };
    const placeholderMessage: Message = {
      id: assistantMsgId,
      type: 'assistant',
      content: '',
      timestamp: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    };

    setMessages((prev) => [...prev, userMessage, placeholderMessage]);
    setInputValue('');
    setLoading(true);
    activeAssistantRef.current = assistantMsgId;
    return { assistantMsgId };
  };

  const sendAgentMessage = async (content: string, assistantMsgId: string) => {
    const controller = new AbortController();
    activeRequestRef.current = controller;
    try {
      const sessionId = selectedTaskId
        ? `${agentSessionRef.current}-task-${selectedTaskId}`
        : `${agentSessionRef.current}-general`;

      const response = await api.post(
        endpoints.agent.chat,
        { query: content, session_id: sessionId },
        { signal: controller.signal, timeout: 10 * 60 * 1000 }
      );

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                content: response.data.answer || 'Agent 暂未返回内容。',
                used_tool: response.data.used_tool || 'direct_answer',
                decision_summary: response.data.decision_summary,
                observation_summary: response.data.observation_summary,
                short_memory_turns: response.data.short_memory_turns,
                long_memory_hits: response.data.long_memory_hits,
                tool_observation: response.data.tool_observation,
                agent_trace: response.data.agent_trace || [],
              }
            : msg
        )
      );
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.name === 'AbortError') {
        return;
      }
      console.error('Agent 回答失败:', error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, content: '抱歉，Agent 处理失败，请稍后重试。', context: { error: true } }
            : msg
        )
      );
    } finally {
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null;
      }
      if (activeAssistantRef.current === assistantMsgId) {
        activeAssistantRef.current = null;
      }
      setLoading(false);
    }
  };

  const sendMessage = async (content: string) => {
    const prepared = buildBaseMessages(content);
    if (!prepared) return;
    await sendAgentMessage(content, prepared.assistantMsgId);
  };

  const clearConversation = () => {
    if (loading) {
      cancelActiveRequest('当前回答已取消。');
    }
    setMessages([]);
    agentSessionRef.current = `agent-session-${Date.now()}`;
  };

  const exportConversation = () => {
    const conversationText = messages
      .map((msg) => `${msg.type === 'user' ? '用户' : '助手'} (${msg.timestamp}):\n${msg.content}\n\n`)
      .join('');
    const blob = new Blob([conversationText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Agent对话_${dayjs().format('YYYY-MM-DD_HH-mm')}.txt`;
    link.click();
    URL.revokeObjectURL(url);
    message.success('对话历史已导出');
  };

  const renderTrace = (trace?: AgentTraceStep[]) => {
    if (!trace?.length) return null;
    return (
      <div
        style={{
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          padding: '10px 12px',
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8, color: '#595959' }}>
          Agent 执行轨迹
        </div>
        <Timeline
          items={trace.map((step) => ({
            color: TRACE_STATUS_COLOR[step.status] || 'blue',
            children: (
              <div style={{ fontSize: 12, lineHeight: 1.7 }}>
                <Space size={6} wrap>
                  <Text strong>Step {step.step}</Text>
                  <Tag color={TOOL_COLORS[step.action] || 'default'}>
                    {TOOL_LABELS[step.action] || step.action}
                  </Tag>
                  <Tag color={TRACE_STATUS_COLOR[step.status] || 'blue'}>
                    {TRACE_STATUS_LABELS[step.status] || step.status}
                  </Tag>
                  {step.risk_level ? (
                    <Tag color={RISK_COLOR[step.risk_level] || 'default'}>风险: {step.risk_level}</Tag>
                  ) : null}
                  {step.elapsed_ms !== undefined ? <Tag>{step.elapsed_ms} ms</Tag> : null}
                </Space>
                {step.thought ? <div><Text type="secondary">思考:</Text> {step.thought}</div> : null}
                {step.observation_summary ? (
                  <div><Text type="secondary">观察:</Text> {step.observation_summary}</div>
                ) : null}
              </div>
            ),
          }))}
        />
      </div>
    );
  };

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fb' }}>
      <Header
        style={{
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
        }}
      >
        <Space>
          <Avatar icon={<RobotOutlined />} style={{ background: token.colorPrimary }} />
          <Title level={4} style={{ margin: 0 }}>
            智能分析 Agent
          </Title>
          <Tag color="processing" icon={<ThunderboltOutlined />}>多步工具协作</Tag>
        </Space>
        <Space>
          <Button icon={<InfoCircleOutlined />} onClick={() => setShowContextModal(true)}>
            查看 Agent 状态
          </Button>
          <Button icon={<ExportOutlined />} onClick={exportConversation} disabled={!messages.length}>
            导出
          </Button>
          <Button icon={<ClearOutlined />} onClick={clearConversation}>
            清空
          </Button>
        </Space>
      </Header>

      <Content style={{ padding: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr)', gap: 16 }}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card size="small" title="任务上下文">
              <Select
                allowClear
                style={{ width: '100%' }}
                placeholder="选择任务上下文"
                value={selectedTaskId ?? undefined}
                onChange={(value) => setSelectedTaskId(value ?? null)}
                options={tasks.map((task) => ({
                  label: `${task.platform || '-'} · ${task.keyword || `任务 ${task.id}`}`,
                  value: task.id,
                }))}
              />
              <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                选择任务后，Agent 会使用独立会话上下文。
              </Text>
            </Card>

            <Card size="small" title="推荐问题">
              <Space direction="vertical" style={{ width: '100%' }}>
                {predefinedQuestions.map((question) => (
                  <Button key={question} block onClick={() => sendMessage(question)} disabled={loading}>
                    {question}
                  </Button>
                ))}
              </Space>
            </Card>

            <Card size="small" title="风险概览">
              {aggregatedRiskFingerprints.length ? (
                <Space wrap>
                  {aggregatedRiskFingerprints.map((risk) => (
                    <Tooltip key={risk.code} title={risk.message}>
                      <Badge count={risk.count} size="small">
                        <Tag color="volcano">{RISK_LABELS[risk.code] || risk.code}</Tag>
                      </Badge>
                    </Tooltip>
                  ))}
                </Space>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险指纹" />
              )}
            </Card>
          </Space>

          <Card
            style={{ minHeight: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column' }}
            bodyStyle={{ display: 'flex', flexDirection: 'column', flex: 1, padding: 0 }}
          >
            <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
              {!messages.length ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="输入问题后，Agent 会自动规划、调用工具并展示执行轨迹。"
                />
              ) : (
                <List
                  dataSource={messages}
                  renderItem={(msg) => (
                    <List.Item style={{ border: 'none', justifyContent: msg.type === 'user' ? 'flex-end' : 'flex-start' }}>
                      <div
                        style={{
                          display: 'flex',
                          flexDirection: msg.type === 'user' ? 'row-reverse' : 'row',
                          gap: 12,
                          maxWidth: '82%',
                        }}
                      >
                        <Avatar icon={msg.type === 'user' ? <UserOutlined /> : <RobotOutlined />} />
                        <div>
                          <div
                            style={{
                              background: msg.type === 'user' ? token.colorPrimary : '#f5f5f5',
                              color: msg.type === 'user' ? '#fff' : 'rgba(0,0,0,0.88)',
                              padding: '12px 16px',
                              borderRadius: msg.type === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                            }}
                          >
                            {msg.content ? (
                              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{msg.content}</div>
                            ) : (
                              <Text type="secondary">Agent 正在思考...</Text>
                            )}

                            {msg.type === 'assistant' && msg.used_tool ? (
                              <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
                                <Space wrap size={[8, 8]}>
                                  <Tag color={TOOL_COLORS[msg.used_tool] || 'default'}>
                                    工具: {TOOL_LABELS[msg.used_tool] || msg.used_tool}
                                  </Tag>
                                  {msg.tool_observation?.status ? (
                                    <Tag color={STATUS_COLOR_MAP[msg.tool_observation.status] || 'default'}>
                                      状态: {STATUS_LABEL_MAP[msg.tool_observation.status] || msg.tool_observation.status}
                                    </Tag>
                                  ) : null}
                                  {msg.short_memory_turns !== undefined ? (
                                    <Tag icon={<ClockCircleOutlined />}>{msg.short_memory_turns} 轮短期记忆</Tag>
                                  ) : null}
                                  {msg.long_memory_hits !== undefined ? (
                                    <Tag icon={<DatabaseOutlined />}>{msg.long_memory_hits} 条长期命中</Tag>
                                  ) : null}
                                </Space>

                                <div
                                  style={{
                                    background: '#fafafa',
                                    border: '1px solid #f0f0f0',
                                    borderRadius: 8,
                                    padding: '10px 12px',
                                  }}
                                >
                                  <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 6, color: '#595959' }}>
                                    Agent 决策面板
                                  </div>
                                  <div style={{ fontSize: 12, lineHeight: 1.7, color: 'rgba(0,0,0,0.75)' }}>
                                    <div><Text type="secondary">决策摘要:</Text> {msg.decision_summary || '本轮未返回决策摘要。'}</div>
                                    <div><Text type="secondary">工具观察:</Text> {msg.observation_summary || '本轮未返回工具观察。'}</div>
                                    {msg.tool_observation?.diagnostics?.cookie_health?.health ? (
                                      <div>
                                        <Text type="secondary">Cookie 健康:</Text> {msg.tool_observation.diagnostics.cookie_health.health}
                                      </div>
                                    ) : null}
                                  </div>
                                </div>

                                {renderTrace(msg.agent_trace)}

                                {msg.tool_observation?.warnings?.length ? (
                                  <Alert
                                    type={msg.tool_observation.status === 'failed' ? 'error' : 'warning'}
                                    showIcon
                                    message={`抓取告警 ${msg.tool_observation.warnings.length} 条`}
                                    description={
                                      <Space direction="vertical" size={6}>
                                        {msg.tool_observation.warnings.map((warning, index) => (
                                          <div key={`${msg.id}-warning-${index}`}>
                                            <Text strong>{warning.scope || 'runtime'}:</Text> {warning.message}
                                          </div>
                                        ))}
                                      </Space>
                                    }
                                  />
                                ) : null}

                                {msg.tool_observation?.diagnostics?.risk_fingerprints?.length ? (
                                  <Space wrap>
                                    {msg.tool_observation.diagnostics.risk_fingerprints.map((risk, index) => (
                                      <Tooltip
                                        key={`${msg.id}-risk-${index}`}
                                        title={`${risk.message}${risk.platform ? ` | 平台: ${risk.platform}` : ''}`}
                                      >
                                        <Tag color="volcano">{RISK_LABELS[risk.code] || risk.code}</Tag>
                                      </Tooltip>
                                    ))}
                                  </Space>
                                ) : null}
                              </Space>
                            ) : null}
                          </div>
                          <div
                            style={{
                              textAlign: msg.type === 'user' ? 'right' : 'left',
                              marginTop: 4,
                              fontSize: 12,
                              color: '#999',
                              padding: '0 4px',
                            }}
                          >
                            {dayjs(msg.timestamp).format('HH:mm')}
                          </div>
                        </div>
                      </div>
                    </List.Item>
                  )}
                />
              )}
              <div ref={messagesEndRef} />
            </div>

            <div style={{ padding: 16, background: '#fff', borderTop: '1px solid #f0f0f0' }}>
              <div style={{ position: 'relative' }}>
                <TextArea
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                  placeholder={selectedTaskId ? '输入分析指令，例如：分析这个话题的用户反馈' : '直接提问，或选择任务获得更好上下文'}
                  autoSize={{ minRows: 3, maxRows: 6 }}
                  onPressEnter={(event) => {
                    if (!event.shiftKey) {
                      event.preventDefault();
                      sendMessage(inputValue);
                    }
                  }}
                  disabled={loading}
                  style={{ paddingRight: 60, borderRadius: 8, resize: 'none' }}
                />
                <div style={{ position: 'absolute', right: 12, bottom: 12 }}>
                  <Tooltip title="发送 (Enter)">
                    <Button
                      type="primary"
                      shape="circle"
                      icon={<SendOutlined />}
                      onClick={() => sendMessage(inputValue)}
                      loading={loading}
                      disabled={!inputValue.trim() || loading}
                    />
                  </Tooltip>
                </div>
              </div>
              <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 8, fontSize: 12 }}>
                {selectedTaskId ? 'Agent 会基于任务数据进行精准分析' : 'Agent 会根据问题自主选择工具并生成回答'}
              </Text>
            </div>
          </Card>
        </div>
      </Content>

      <Modal
        title="Agent 状态信息"
        open={showContextModal}
        onCancel={() => setShowContextModal(false)}
        footer={[<Button key="close" onClick={() => setShowContextModal(false)}>关闭</Button>]}
        width={680}
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="当前会话">{agentSessionRef.current}</Descriptions.Item>
          <Descriptions.Item label="选中的任务">{selectedTaskId || '未选择'}</Descriptions.Item>
          <Descriptions.Item label="对话轮次">{messages.filter((item) => item.type === 'user').length}</Descriptions.Item>
          <Descriptions.Item label="Agent 模式">多步规划 · 工具校验 · 长期记忆</Descriptions.Item>
          <Descriptions.Item label="最近一次工具状态">
            {latestAssistantMessage?.tool_observation?.status
              ? STATUS_LABEL_MAP[latestAssistantMessage.tool_observation.status] || latestAssistantMessage.tool_observation.status
              : '暂无'}
          </Descriptions.Item>
          <Descriptions.Item label="最近一次风险数">
            {latestAssistantMessage?.tool_observation?.diagnostics?.risk_fingerprints?.length || 0}
          </Descriptions.Item>
        </Descriptions>
        {latestAssistantMessage?.tool_observation ? (
          <Card size="small" title="最近一次工具观察" style={{ marginTop: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="平台">{latestAssistantMessage.tool_observation.platform || '-'}</Descriptions.Item>
              <Descriptions.Item label="关键词">{latestAssistantMessage.tool_observation.keyword || '-'}</Descriptions.Item>
              <Descriptions.Item label="帖子/评论">
                {(latestAssistantMessage.tool_observation.total_posts ?? 0)} /{' '}
                {(latestAssistantMessage.tool_observation.total_comments ?? 0)}
              </Descriptions.Item>
              <Descriptions.Item label="说明">
                {latestAssistantMessage.tool_observation.message || latestAssistantMessage.tool_observation.error || '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        ) : null}
      </Modal>
    </Layout>
  );
};

export default AgentPage;
