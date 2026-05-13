import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Card,
  Input,
  Button,
  Space,
  Typography,
  Avatar,
  List,
  Tag,
  Modal,
  Select,
  message,
  Layout,
  theme,
  Tooltip,
  Descriptions,
  Badge,
  Alert,
  Empty,
  Divider,
} from 'antd';
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  ClearOutlined,
  HistoryOutlined,
  ExportOutlined,
  BulbOutlined,
  InfoCircleOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  ClockCircleOutlined
} from '@ant-design/icons';
import api, { endpoints } from '../services/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Header, Content } = Layout;

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
  context?: any;
}

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

const TOOL_LABELS: Record<string, string> = {
  direct_answer: '直接回答',
  fetch_data: '数据查询',
  sentiment_analysis: '情感分析',
  topic_modeling: '主题建模',
  vector_search: '长期检索',
};

const TOOL_COLORS: Record<string, string> = {
  direct_answer: 'default',
  fetch_data: 'blue',
  sentiment_analysis: 'green',
  topic_modeling: 'purple',
  vector_search: 'orange',
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

const RISK_LABELS: Record<string, string> = {
  bilibili_412: '412 风控',
  captcha: '验证码',
  login_required: '登录失效',
  empty_json: '空返回/非 JSON',
  blocked: '请求拦截',
  wbi_failed: 'WBI 失败',
};

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

  const predefinedQuestions = [
    '总结当前任务的主要发现',
    '用户对产品的主要反馈是什么？',
    '有哪些需要关注的负面情感？',
    '基于历史对话给出分析建议',
    '分析情感变化趋势',
  ];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const fetchTasks = async () => {
    try {
      const response = await api.get(endpoints.tasks);
      if (response.data && response.data.tasks) {
        setTasks(response.data.tasks);
      }
    } catch (error) {
      console.error('获取任务列表失败:', error);
    }
  };

  useEffect(() => {
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
      setMessages(prev => prev.map(msg =>
        msg.id === activeAssistantRef.current
          ? { ...msg, content: notice, context: { cancelled: true } }
          : msg
      ));
    }
    activeAssistantRef.current = null;
  };

  const buildBaseMessages = (content: string) => {
    if (!content.trim() || loading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: content.trim(),
      timestamp: dayjs().format('YYYY-MM-DD HH:mm:ss')
    };

    const assistantMsgId = (Date.now() + 1).toString();
    const placeholderMessage: Message = {
      id: assistantMsgId,
      type: 'assistant',
      content: '',
      timestamp: dayjs().format('YYYY-MM-DD HH:mm:ss'),
    };

    setMessages(prev => [...prev, userMessage, placeholderMessage]);
    setInputValue('');
    setLoading(true);
    activeAssistantRef.current = assistantMsgId;
    return { assistantMsgId };
  };

  const sendAgentMessage = async (content: string, assistantMsgId: string) => {
    const controller = new AbortController();
    activeRequestRef.current = controller;
    try {
      // 生成session_id，如果有选择任务则包含任务ID，否则使用通用session
      const sessionId = selectedTaskId 
        ? `${agentSessionRef.current}-task-${selectedTaskId}`
        : `${agentSessionRef.current}-general`;
      
      const response = await api.post(endpoints.agent.chat, {
        query: content,
        session_id: sessionId
      }, {
        signal: controller.signal,
      });

      setMessages(prev => prev.map(msg =>
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
            }
          : msg
      ));
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.name === 'AbortError') {
        return;
      }
      console.error('Agent 回答失败:', error);
      setMessages(prev => prev.map(msg =>
        msg.id === assistantMsgId
          ? { ...msg, content: '抱歉，Agent 处理失败，请稍后重试。', context: { error: true } }
          : msg
      ));
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
    const conversationText = messages.map(msg =>
      `${msg.type === 'user' ? '用户' : '助手'} (${msg.timestamp}):\n${msg.content}\n\n`
    ).join('');

    const blob = new Blob([conversationText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Agent对话_${dayjs().format('YYYY-MM-DD_HH-mm')}.txt`;
    link.click();
    URL.revokeObjectURL(url);
    message.success('对话历史已导出');
  };

  return (
    <Layout style={{ height: 'calc(100vh - 64px)', background: '#f0f2f5', marginLeft: -24, marginRight: -24, marginTop: -24, marginBottom: -24 }}>
      <Header style={{
        background: '#fff',
        padding: '0 24px',
        height: 'auto',
        minHeight: 64,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #f0f0f0',
        boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
        zIndex: 10,
        flexWrap: 'wrap'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
          <ThunderboltOutlined style={{ fontSize: 24, color: token.colorPrimary }} />
          <div>
            <Title level={4} style={{ margin: 0 }}>智能分析 Agent</Title>
            <Text type="secondary" style={{ fontSize: 12 }}>多工具协作 · 长期记忆 · 自主决策</Text>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 0' }}>
          <Tag color="processing" icon={<RobotOutlined />}>Agent 模式</Tag>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <InfoCircleOutlined style={{ color: token.colorTextSecondary }} />
            <Text type="secondary">分析上下文:</Text>
          </span>
          <Select
            placeholder="可选：选择任务获得更好上下文..."
            style={{ width: 350 }}
            value={selectedTaskId}
            onChange={setSelectedTaskId}
            optionLabelProp="label"
            listHeight={400}
            popupMatchSelectWidth={false}
            getPopupContainer={() => document.body}
            showSearch
            filterOption={(input, option) =>
              ((option?.label as any)?.toString() ?? '').toLowerCase().includes(input.toLowerCase())
            }
          >
            {tasks.map(task => (
              <Select.Option
                key={task.id}
                value={task.id}
                label={`${task.keyword} (${task.platform})`}
              >
                <div style={{ display: 'flex', flexDirection: 'column', padding: '4px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 500 }}>{task.keyword}</span>
                    <Tag color={task.status === 'completed' ? 'success' : task.status === 'running' ? 'processing' : 'default'}>
                      {task.status}
                    </Tag>
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>平台: {task.platform} | ID: {task.id}</Text>
                </div>
              </Select.Option>
            ))}
          </Select>
        </div>
      </Header>

      <Content style={{ padding: '24px', display: 'flex', gap: 24, height: 'calc(100% - 64px)', overflow: 'hidden' }}>
        <Card
          style={{ width: 300, display: 'flex', flexDirection: 'column', height: '100%' }}
          bodyStyle={{ flex: 1, overflowY: 'auto', padding: '16px' }}
          title="Agent 能力"
        >
          <Badge status="processing" text="工具调用" />
          <div style={{ marginBottom: 16, marginTop: 8 }}>
            <List
              dataSource={[
                { icon: '🔍', name: '数据查询', desc: '检索任务数据' },
                { icon: '💬', name: '情感分析', desc: '分析用户情感' },
                { icon: '📊', name: '主题建模', desc: 'LDA主题提取' },
                { icon: '🧠', name: '长期记忆', desc: '跨会话检索' },
              ]}
              size="small"
              renderItem={(item) => (
                <List.Item style={{ padding: '8px 0' }}>
                  <Space>
                    <Text>{item.icon}</Text>
                    <Text strong style={{ fontSize: 13 }}>{item.name}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.desc}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </div>

          <Text strong style={{ marginBottom: 8, display: 'block' }}>快捷指令</Text>
          <List
            dataSource={predefinedQuestions}
            size="small"
            renderItem={(question) => (
              <List.Item
                style={{
                  cursor: 'pointer',
                  padding: '8px 12px',
                  borderRadius: 6,
                  marginBottom: 8,
                  border: '1px solid #f0f0f0',
                  transition: 'all 0.3s'
                }}
                className="hover-card"
                onClick={() => sendMessage(question)}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = token.colorPrimary; e.currentTarget.style.background = token.colorPrimaryBg; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#f0f0f0'; e.currentTarget.style.background = 'transparent'; }}
              >
                <Space align="start">
                  <BulbOutlined style={{ color: token.colorPrimary, marginTop: 4 }} />
                  <Text style={{ fontSize: 13 }}>{question}</Text>
                </Space>
              </List.Item>
            )}
          />

          <div style={{ marginTop: 'auto' }}>
            <Divider style={{ margin: '16px 0 12px' }}>平台风控面板</Divider>
            {aggregatedRiskFingerprints.length > 0 ? (
              <List
                size="small"
                dataSource={aggregatedRiskFingerprints}
                renderItem={(item) => (
                  <List.Item style={{ padding: '8px 0', display: 'block' }}>
                    <Space wrap size={[8, 4]}>
                      <Tag color="volcano">{RISK_LABELS[item.code] || item.code}</Tag>
                      <Tag>{item.count} 次</Tag>
                      {item.platforms.map((platform) => (
                        <Tag key={`${item.code}-${platform}`} color="blue">
                          {platform}
                        </Tag>
                      ))}
                    </Space>
                    <div style={{ fontSize: 12, color: token.colorTextSecondary, marginTop: 4 }}>
                      {item.message}
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="当前会话还没有识别到风控指纹"
              />
            )}

            <Divider style={{ margin: '16px 0 12px' }} />
            <Button icon={<HistoryOutlined />} block style={{ marginBottom: 8 }} onClick={() => setShowContextModal(true)} disabled={messages.length === 0 && !selectedTaskId}>
              查看 Agent 状态
            </Button>
            <Button icon={<ExportOutlined />} block style={{ marginBottom: 8 }} onClick={exportConversation} disabled={messages.length === 0}>
              导出对话记录
            </Button>
            <Button icon={<ClearOutlined />} block danger type="dashed" onClick={clearConversation} disabled={messages.length === 0 && !selectedTaskId}>
              清空对话
            </Button>
          </div>
        </Card>

        <Card
          style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}
          bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0, height: '100%', overflow: 'hidden' }}
        >
          <div style={{ flex: 1, overflowY: 'auto', padding: '24px', background: '#fff' }}>
            {messages.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', opacity: 0.6 }}>
                <RobotOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 24 }} />
                <Title level={4} style={{ color: '#999' }}>Agent 智能分析助手</Title>
                <Text type="secondary">可以直接提问，或选择任务获得更好的上下文分析</Text>
              </div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} style={{
                  display: 'flex',
                  justifyContent: msg.type === 'user' ? 'flex-end' : 'flex-start',
                  marginBottom: 24
                }}>
                  <div style={{
                    display: 'flex',
                    flexDirection: msg.type === 'user' ? 'row-reverse' : 'row',
                    maxWidth: '85%',
                    gap: 12
                  }}>
                    <Avatar
                      icon={msg.type === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      style={{
                        backgroundColor: msg.type === 'user' ? token.colorPrimary : '#722ed1',
                        flexShrink: 0
                      }}
                    />
                    <div>
                      <div style={{
                        background: msg.type === 'user' ? token.colorPrimary : '#f5f5f5',
                        color: msg.type === 'user' ? '#fff' : 'rgba(0,0,0,0.88)',
                        padding: '12px 16px',
                        borderRadius: msg.type === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
                      }}>
                        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{msg.content}</div>

                        {msg.type === 'assistant' && msg.used_tool && (
                          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                              <Tag color={TOOL_COLORS[msg.used_tool] || 'default'}>
                                工具: {TOOL_LABELS[msg.used_tool] || msg.used_tool}
                              </Tag>
                              {msg.tool_observation?.status && (
                                <Tag color={STATUS_COLOR_MAP[msg.tool_observation.status] || 'default'}>
                                  状态: {STATUS_LABEL_MAP[msg.tool_observation.status] || msg.tool_observation.status}
                                </Tag>
                              )}
                              {msg.short_memory_turns !== undefined && (
                                <Tag icon={<ClockCircleOutlined />}>{msg.short_memory_turns} 轮短期记忆</Tag>
                              )}
                              {msg.long_memory_hits !== undefined && (
                                <Tag icon={<DatabaseOutlined />}>{msg.long_memory_hits} 条长期命中</Tag>
                              )}
                            </div>

                            <div style={{
                              background: '#fafafa',
                              border: '1px solid #f0f0f0',
                              borderRadius: 8,
                              padding: '10px 12px',
                            }}>
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
                              <div style={{
                                background: '#fff7e6',
                                border: '1px solid #ffd591',
                                borderRadius: 8,
                                padding: '10px 12px',
                              }}>
                                <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8, color: '#ad6800' }}>
                                  风控指纹
                                </div>
                                <Space wrap size={[8, 8]}>
                                  {msg.tool_observation.diagnostics.risk_fingerprints.map((risk, index) => (
                                    <Tooltip
                                      key={`${msg.id}-risk-${index}`}
                                      title={`${risk.message}${risk.platform ? ` | 平台: ${risk.platform}` : ''}`}
                                    >
                                      <Tag color="volcano">
                                        {RISK_LABELS[risk.code] || risk.code}
                                      </Tag>
                                    </Tooltip>
                                  ))}
                                </Space>
                              </div>
                            ) : null}
                          </div>
                        )}
                      </div>
                      <div style={{
                        textAlign: msg.type === 'user' ? 'right' : 'left',
                        marginTop: 4,
                        fontSize: 12,
                        color: '#999',
                        padding: '0 4px'
                      }}>
                        {dayjs(msg.timestamp).format('HH:mm')}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          <div style={{ padding: '16px 24px', background: '#fff', borderTop: '1px solid #f0f0f0' }}>
            <div style={{ position: 'relative' }}>
              <TextArea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={selectedTaskId ? "输入分析指令，例如：分析这个话题的用户反馈..." : "直接提问，或选择任务获得更好上下文..."}
                autoSize={{ minRows: 3, maxRows: 6 }}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault();
                    sendMessage(inputValue);
                  }
                }}
                disabled={loading}
                style={{
                  paddingRight: 60,
                  borderRadius: 12,
                  resize: 'none',
                  border: '1px solid #d9d9d9',
                  boxShadow: '0 2px 6px rgba(0,0,0,0.02)'
                }}
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
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {selectedTaskId ? "Agent 会基于任务数据进行精准分析" : "Agent 会根据问题自主选择工具并生成回答"}
              </Text>
            </div>
          </div>
        </Card>
      </Content>

      <Modal
        title="Agent 状态信息"
        open={showContextModal}
        onCancel={() => setShowContextModal(false)}
        footer={[<Button key="close" onClick={() => setShowContextModal(false)}>关闭</Button>]}
        width={600}
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="当前会话">{agentSessionRef.current}</Descriptions.Item>
          <Descriptions.Item label="选中的任务">{selectedTaskId || '未选择'}</Descriptions.Item>
          <Descriptions.Item label="对话轮次">{messages.filter(m => m.type === 'user').length}</Descriptions.Item>
          <Descriptions.Item label="Agent 模式">多工具协作 · 长期记忆</Descriptions.Item>
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
          <Card size="small" title="最近一次工具观测" style={{ marginTop: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="平台">{latestAssistantMessage.tool_observation.platform || '-'}</Descriptions.Item>
              <Descriptions.Item label="关键词">{latestAssistantMessage.tool_observation.keyword || '-'}</Descriptions.Item>
              <Descriptions.Item label="帖子/评论">
                {(latestAssistantMessage.tool_observation.total_posts ?? 0)} / {(latestAssistantMessage.tool_observation.total_comments ?? 0)}
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
