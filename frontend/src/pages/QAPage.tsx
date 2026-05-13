import React, { useState, useRef, useEffect } from 'react';
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
  Empty,
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
  CommentOutlined,
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
  related_data?: any;
  context?: any;
}

const QAPage: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<any[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);

  const [showContextModal, setShowContextModal] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const activeAssistantRef = useRef<string | null>(null);
  const { token } = theme.useToken();

  const predefinedQuestions = [
    '请总结当前的情感分析结果',
    '用户对产品的整体满意度如何？',
    '有哪些主要的负面反馈？',
    '请分析情感趋势变化',
    '基于分析结果，有什么改进建议？',
    '请识别潜在的风险和负面情感',
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

    if (!selectedTaskId) {
      message.warning('请先选择一个分析任务作为上下文');
      return null;
    }

    const selectedTask = tasks.find(t => t.id === selectedTaskId);
    if (selectedTask && selectedTask.status === 'pending') {
      message.warning('该任务尚未开始，可能没有数据可用于回答');
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: content.trim(),
      timestamp: dayjs().format('YYYY-MM-DD HH:mm:ss'),
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

  const sendQaMessage = async (content: string, assistantMsgId: string) => {
    const controller = new AbortController();
    activeRequestRef.current = controller;
    try {
      const response = await fetch(`${api.defaults.baseURL}${endpoints.qa.stream}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
        body: JSON.stringify({
          question: content,
          context_task_id: selectedTaskId,
        }),
      });

      if (!response.ok) {
        throw new Error(response.statusText);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulatedContent = '';
      let relatedData: any = null;
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';

          for (const eventText of events) {
            const payload = eventText
              .split('\n')
              .filter(line => line.startsWith('data: '))
              .map(line => line.slice(6))
              .join('');
            if (payload) {
              try {
                const data = JSON.parse(payload);

                if (data.error) {
                  throw new Error(data.error);
                }

                if (data.type === 'context') {
                  relatedData = data.sources;
                } else if (data.type === 'content') {
                  accumulatedContent += data.content;
                  setMessages(prev => prev.map(msg =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: accumulatedContent, related_data: relatedData }
                      : msg
                  ));
                }
              } catch (e) {
                console.error('Error parsing stream chunk', e);
              }
            }
          }
        }
        if (buffer.trim().startsWith('data: ')) {
          try {
            const data = JSON.parse(buffer.trim().slice(6));
            if (data.type === 'content') {
              accumulatedContent += data.content;
              setMessages(prev => prev.map(msg =>
                msg.id === assistantMsgId
                  ? { ...msg, content: accumulatedContent, related_data: relatedData }
                  : msg
              ));
            }
          } catch (e) {
            console.error('Error parsing trailing stream chunk', e);
          }
        }
      }
      if (!accumulatedContent) {
        setMessages(prev => prev.map(msg =>
          msg.id === assistantMsgId
            ? { ...msg, content: '当前没有收到返回内容，请稍后重试。', context: { empty: true } }
            : msg
        ));
      }
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        return;
      }
      console.error('获取回答失败:', error);
      setMessages(prev => prev.map(msg =>
        msg.id === assistantMsgId
          ? { ...msg, content: '抱歉，处理您的问题时出现了错误。请稍后重试。', context: { error: true } }
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
    await sendQaMessage(content, prepared.assistantMsgId);
  };

  const clearConversation = () => {
    if (loading) {
      cancelActiveRequest('当前回答已取消。');
    }
    setMessages([]);
  };

  const exportConversation = () => {
    const conversationText = messages.map(msg =>
      `${msg.type === 'user' ? '用户' : '助手'} (${msg.timestamp}):\n${msg.content}\n\n`
    ).join('');

    const blob = new Blob([conversationText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `QA对话_${dayjs().format('YYYY-MM-DD_HH-mm')}.txt`;
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
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
          <CommentOutlined style={{ fontSize: 24, color: token.colorPrimary }} />
          <div>
            <Title level={4} style={{ margin: 0 }}>数据分析问答</Title>
            <Text type="secondary" style={{ fontSize: 12 }}>基于任务数据的实时问答</Text>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 0' }}>
          <Tag color="blue">QA 模式</Tag>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <InfoCircleOutlined style={{ color: token.colorTextSecondary }} />
            <Text type="secondary">当前上下文:</Text>
          </span>
          <Select
            placeholder="请选择一个分析任务..."
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
          title="快捷指令"
        >
          <Tag color="blue" style={{ marginBottom: 16 }}>常用问题模板</Tag>
          <div style={{ marginBottom: 16 }}>
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
                    transition: 'all 0.3s',
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
          </div>

          <div style={{ marginTop: 'auto' }}>
            <Button icon={<HistoryOutlined />} block style={{ marginBottom: 8 }} onClick={() => setShowContextModal(true)} disabled={!selectedTaskId}>
              查看数据上下文
            </Button>
            <Button icon={<ExportOutlined />} block style={{ marginBottom: 8 }} onClick={exportConversation}>
              导出对话记录
            </Button>
            <Button icon={<ClearOutlined />} block danger type="dashed" onClick={clearConversation}>
              清空当前对话
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
                <CommentOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 24 }} />
                <Title level={4} style={{ color: '#999' }}>开始您的数据分析问答</Title>
                <Text type="secondary">请在顶部选择一个任务，然后在下方输入问题</Text>
              </div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} style={{
                  display: 'flex',
                  justifyContent: msg.type === 'user' ? 'flex-end' : 'flex-start',
                  marginBottom: 24,
                }}>
                  <div style={{
                    display: 'flex',
                    flexDirection: msg.type === 'user' ? 'row-reverse' : 'row',
                    maxWidth: '80%',
                    gap: 12,
                  }}>
                    <Avatar
                      icon={msg.type === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      style={{
                        backgroundColor: msg.type === 'user' ? token.colorPrimary : token.colorSuccess,
                        flexShrink: 0,
                      }}
                    />
                    <div>
                      <div style={{
                        background: msg.type === 'user' ? token.colorPrimary : '#f5f5f5',
                        color: msg.type === 'user' ? '#fff' : 'rgba(0,0,0,0.88)',
                        padding: '12px 16px',
                        borderRadius: msg.type === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                      }}>
                        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{msg.content}</div>
                      </div>
                      <div style={{
                        textAlign: msg.type === 'user' ? 'right' : 'left',
                        marginTop: 4,
                        fontSize: 12,
                        color: '#999',
                        padding: '0 4px',
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
                placeholder={selectedTaskId ? '请输入您的问题，例如：用户对产品的评价如何？' : '请先在顶部选择一个分析任务...'}
                autoSize={{ minRows: 3, maxRows: 6 }}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault();
                    sendMessage(inputValue);
                  }
                }}
                disabled={loading || !selectedTaskId}
                style={{
                  paddingRight: 60,
                  borderRadius: 12,
                  resize: 'none',
                  border: '1px solid #d9d9d9',
                  boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
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
                    disabled={!inputValue.trim() || loading || !selectedTaskId}
                  />
                </Tooltip>
              </div>
            </div>
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                基于上下文数据生成回答
              </Text>
            </div>
          </div>
        </Card>
      </Content>

      <Modal
        title="当前分析上下文数据"
        open={showContextModal}
        onCancel={() => setShowContextModal(false)}
        footer={[<Button key="close" onClick={() => setShowContextModal(false)}>关闭</Button>]}
        width={800}
      >
        <Empty description="暂无详细上下文数据展示功能（开发中）" />
      </Modal>
    </Layout>
  );
};

export default QAPage;