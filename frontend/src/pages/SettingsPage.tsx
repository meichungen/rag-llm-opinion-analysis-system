import React, { useState, useEffect } from 'react';
import { 
  Card, 
  Form, 
  Input, 
  Button, 
  Select, 
  Switch,
  Tabs,
  Space,
  message,
  Typography,
  Row,
  Col,
  Table,
  Tag,
  Modal,
} from 'antd';
import {
  SaveOutlined,
  SettingOutlined,
  UserOutlined,
  DatabaseOutlined,
  ApiOutlined,
  SecurityScanOutlined
} from '@ant-design/icons';
import api, { endpoints } from '../services/api';

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { TextArea } = Input;
const { Option } = Select;
type PlatformKey = 'weibo' | 'douyin' | 'bilibili' | 'xhs';

interface User {
  id: number;
  username: string;
  email: string;
  role: 'admin' | 'user';
  created_at: string;
  last_login: string;
  status: 'active' | 'inactive';
}

interface PlatformSetting {
  enabled: boolean;
  max_posts_per_request: number;
  request_delay: number;
}

type PlatformConfig = Record<PlatformKey, PlatformSetting>;

interface PlatformCookieStatus {
  has_cookie: boolean;
  cookie_file: string;
  cookie_count: number;
  updated_at: number | null;
  format: 'json' | 'raw' | null;
}

const PLATFORM_NAMES: Record<PlatformKey, string> = {
  weibo: '微博',
  douyin: '抖音',
  bilibili: 'B站',
  xhs: '小红书',
};

const DEFAULT_PLATFORM_CONFIG: PlatformConfig = {
  weibo: {
    enabled: true,
    max_posts_per_request: 100,
    request_delay: 2,
  },
  douyin: {
    enabled: true,
    max_posts_per_request: 80,
    request_delay: 3,
  },
  bilibili: {
    enabled: true,
    max_posts_per_request: 50,
    request_delay: 2,
  },
  xhs: {
    enabled: false,
    max_posts_per_request: 60,
    request_delay: 2.5,
  },
};

const EMPTY_COOKIE_INPUTS: Record<PlatformKey, string> = {
  weibo: '',
  douyin: '',
  bilibili: '',
  xhs: '',
};

const SettingsPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [userModalVisible, setUserModalVisible] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [platformConfig, setPlatformConfig] = useState<PlatformConfig>(DEFAULT_PLATFORM_CONFIG);
  const [platformCookieStatus, setPlatformCookieStatus] = useState<Partial<Record<PlatformKey, PlatformCookieStatus>>>({});
  const [cookieInputs, setCookieInputs] = useState<Record<PlatformKey, string>>(EMPTY_COOKIE_INPUTS);
  const [cookieSavingPlatform, setCookieSavingPlatform] = useState<PlatformKey | null>(null);

  const [systemForm] = Form.useForm();
  const [modelForm] = Form.useForm();
  const [llmForm] = Form.useForm();
  const [userForm] = Form.useForm();

  const getErrorMessage = (error: any, fallback = '保存失败') =>
    error?.response?.data?.detail || error?.response?.data?.message || fallback;

  const mergePlatformConfig = (value?: Partial<Record<PlatformKey, Partial<PlatformSetting>>>) => ({
    weibo: { ...DEFAULT_PLATFORM_CONFIG.weibo, ...(value?.weibo || {}) },
    douyin: { ...DEFAULT_PLATFORM_CONFIG.douyin, ...(value?.douyin || {}) },
    bilibili: { ...DEFAULT_PLATFORM_CONFIG.bilibili, ...(value?.bilibili || {}) },
    xhs: { ...DEFAULT_PLATFORM_CONFIG.xhs, ...(value?.xhs || {}) },
  });

  const updatePlatformField = <K extends keyof PlatformSetting>(
    platform: PlatformKey,
    field: K,
    value: PlatformSetting[K]
  ) => {
    setPlatformConfig(prev => ({
      ...prev,
      [platform]: {
        ...prev[platform],
        [field]: value,
      },
    }));
  };

  // 获取用户列表
  const fetchUsers = async () => {
    try {
      // 模拟用户数据
      const mockUsers: User[] = [
        {
          id: 1,
          username: 'admin',
          email: 'admin@example.com',
          role: 'admin',
          created_at: '2025-12-27 10:00:00',
          last_login: '2026-5-10 9:30:00',
          status: 'active'
        },
        // ... rest of mock users
      ];
      setUsers(mockUsers);
    } catch (error) {
      console.error('获取用户列表失败:', error);
    }
  };

  // 获取设置
  const fetchSettings = async () => {
    try {
      const response = await api.get(endpoints.settings);
      const settings = response.data;
      
      if (settings.system) systemForm.setFieldsValue(settings.system);
      if (settings.model) modelForm.setFieldsValue(settings.model);
      if (settings.llm) llmForm.setFieldsValue(settings.llm);
      setPlatformConfig(mergePlatformConfig(settings.platform));
      if (settings.platform_cookie_status) {
        setPlatformCookieStatus(settings.platform_cookie_status);
      }
      
    } catch (error) {
      console.error('获取设置失败:', error);
      // Don't show error on first load if empty
    }
  };

  useEffect(() => {
    fetchUsers();
    fetchSettings();
  }, []);

  // 保存系统配置
  const handleSystemConfigSave = async (values: any) => {
    try {
      setLoading(true);
      await api.post(endpoints.settings, { key: 'system', value: values });
      message.success('系统配置保存成功');
    } catch (error) {
      console.error('保存系统配置失败:', error);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 保存模型配置
  const handleModelConfigSave = async (values: any) => {
    try {
      setLoading(true);
      await api.post(endpoints.settings, { key: 'model', value: values });
      message.success('模型配置保存成功');
    } catch (error) {
      console.error('保存模型配置失败:', error);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 保存大模型配置
  const handleLLMConfigSave = async (values: any) => {
    try {
      setLoading(true);
      await api.post(endpoints.settings, { key: 'llm', value: values });
      message.success('大模型配置保存成功');
    } catch (error) {
      console.error('保存大模型配置失败:', error);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 保存平台配置
  const handlePlatformConfigSave = async () => {
    try {
      setLoading(true);
      await api.post(endpoints.settings, { key: 'platform', value: platformConfig });
      message.success('平台配置保存成功');
    } catch (error) {
      console.error('保存平台配置失败:', error);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  const handlePlatformCookieSave = async (platform: PlatformKey) => {
    const cookieContent = cookieInputs[platform]?.trim();
    if (!cookieContent) {
      message.warning(`请先粘贴${PLATFORM_NAMES[platform]} Cookie`);
      return;
    }

    try {
      setCookieSavingPlatform(platform);
      const response = await api.post(endpoints.settingsPlatformCookie, {
        platform,
        cookie_content: cookieContent,
      });
      setCookieInputs(prev => ({ ...prev, [platform]: '' }));
      if (response.data?.cookie_status) {
        setPlatformCookieStatus(prev => ({
          ...prev,
          [platform]: response.data.cookie_status,
        }));
      }
      message.success(`${PLATFORM_NAMES[platform]} Cookie 更新成功`);
    } catch (error) {
      console.error('更新 Cookie 失败:', error);
      message.error(getErrorMessage(error, 'Cookie 更新失败'));
    } finally {
      setCookieSavingPlatform(null);
    }
  };

  // 用户管理相关函数
  const handleUserEdit = (user: User) => {
    setEditingUser(user);
    userForm.setFieldsValue(user);
    setUserModalVisible(true);
  };

  const handleUserSave = async (values: any) => {
    try {
      setLoading(true);
      if (editingUser) {
        // 编辑用户
        setUsers(users.map(user => 
          user.id === editingUser.id 
            ? { ...user, ...values }
            : user
        ));
        message.success('用户更新成功');
      } else {
        // 新增用户
        const newUser: User = {
          id: users.length + 1,
          ...values,
          created_at: new Date().toLocaleString(),
          last_login: '',
          status: 'active'
        };
        setUsers([...users, newUser]);
        message.success('用户创建成功');
      }
      setUserModalVisible(false);
      userForm.resetFields();
      setEditingUser(null);
    } catch (error) {
      console.error('保存用户失败:', error);
      message.error('保存失败');
    } finally {
      setLoading(false);
    }
  };

  const handleUserDelete = (userId: number) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个用户吗？此操作不可恢复。',
      onOk: () => {
        setUsers(users.filter(user => user.id !== userId));
        message.success('用户删除成功');
      }
    });
  };

  // 用户表格列
  const userColumns = [
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : 'blue'}>
          {role === 'admin' ? '管理员' : '普通用户'}
        </Tag>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status === 'active' ? '活跃' : '未激活'}
        </Tag>
      )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
    },
    {
      title: '最后登录',
      dataIndex: 'last_login',
      key: 'last_login',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: User) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleUserEdit(record)}>
            编辑
          </Button>
          <Button type="link" size="small" danger onClick={() => handleUserDelete(record.id)}>
            删除
          </Button>
        </Space>
      )
    }
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: '24px' }}>
        <Title level={2}>系统设置</Title>
        <Text type="secondary">配置系统参数、管理用户和平台设置</Text>
      </div>

      <Tabs defaultActiveKey="1">
        <TabPane 
          tab={
            <span>
              <SettingOutlined />
              系统配置
            </span>
          } 
          key="1"
        >
          <Card title="基本设置">
            <Form
              form={systemForm}
              layout="vertical"
              onFinish={handleSystemConfigSave}
              initialValues={{
                site_name: '社交媒体分析系统',
                site_description: '专业的社交媒体热点话题发现与情感分析平台',
                max_tasks_per_user: 10,
                task_timeout: 3600,
                enable_registration: true,
                enable_email_verification: false
              }}
            >
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="站点名称"
                    name="site_name"
                    rules={[{ required: true, message: '请输入站点名称' }]}
                  >
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="站点描述"
                    name="site_description"
                  >
                    <TextArea rows={2} />
                  </Form.Item>
                </Col>
              </Row>
              
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="每用户最大任务数"
                    name="max_tasks_per_user"
                    rules={[{ required: true, message: '请输入最大任务数' }]}
                  >
                    <Input type="number" min={1} max={100} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="任务超时时间（秒）"
                    name="task_timeout"
                    rules={[{ required: true, message: '请输入超时时间' }]}
                  >
                    <Input type="number" min={300} max={86400} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="启用用户注册"
                    name="enable_registration"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading}>
                  <SaveOutlined /> 保存设置
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>

        <TabPane 
          tab={
            <span>
              <DatabaseOutlined />
              平台配置
            </span>
          } 
          key="2"
        >
          <Card title="社交媒体平台配置">
            <Space direction="vertical" style={{ width: '100%' }}>
              {(Object.entries(platformConfig) as [PlatformKey, PlatformSetting][]).map(([platform, config]) => {
                const cookieStatus = platformCookieStatus[platform];
                const updatedAt = cookieStatus?.updated_at
                  ? new Date(cookieStatus.updated_at * 1000).toLocaleString()
                  : '未配置';

                return (
                  <Card key={platform} size="small" title={PLATFORM_NAMES[platform]}>
                    <Row gutter={[16, 16]} align="middle">
                      <Col span={24}>
                        <Space wrap>
                          <Tag color={cookieStatus?.has_cookie ? 'green' : 'default'}>
                            {cookieStatus?.has_cookie ? '已配置 Cookie' : '未配置 Cookie'}
                          </Tag>
                          <Text type="secondary">
                            文件：{cookieStatus?.cookie_file || '未生成'}
                          </Text>
                          <Text type="secondary">
                            数量：{cookieStatus?.cookie_count ?? 0}
                          </Text>
                          <Text type="secondary">
                            格式：{cookieStatus?.format || '未知'}
                          </Text>
                          <Text type="secondary">
                            更新时间：{updatedAt}
                          </Text>
                        </Space>
                      </Col>
                      <Col span={6}>
                        <Switch
                          checked={config.enabled}
                          onChange={(checked) => {
                            updatePlatformField(platform, 'enabled', checked);
                          }}
                        />
                        <Text style={{ marginLeft: '8px' }}>
                          {config.enabled ? '已启用' : '已禁用'}
                        </Text>
                      </Col>
                      <Col span={9}>
                        <Text>每次请求最大帖子数：</Text>
                        <Input
                          type="number"
                          value={config.max_posts_per_request}
                          onChange={(e) => {
                            updatePlatformField(
                              platform,
                              'max_posts_per_request',
                              parseInt(e.target.value, 10) || 50
                            );
                          }}
                          style={{ width: '80px', marginLeft: '8px' }}
                          min={10}
                          max={200}
                        />
                      </Col>
                      <Col span={9}>
                        <Text>请求延迟（秒）：</Text>
                        <Input
                          type="number"
                          value={config.request_delay}
                          onChange={(e) => {
                            updatePlatformField(
                              platform,
                              'request_delay',
                              parseFloat(e.target.value) || 1
                            );
                          }}
                          style={{ width: '80px', marginLeft: '8px' }}
                          min={0.5}
                          max={10}
                          step={0.5}
                        />
                      </Col>
                      <Col span={24}>
                        <TextArea
                          rows={4}
                          placeholder={`粘贴${PLATFORM_NAMES[platform]} Cookie，支持整串 Cookie 或 Cookie JSON 数组`}
                          value={cookieInputs[platform]}
                          onChange={(e) =>
                            setCookieInputs(prev => ({
                              ...prev,
                              [platform]: e.target.value,
                            }))
                          }
                        />
                      </Col>
                      <Col span={24}>
                        <Space>
                          <Button
                            onClick={() => handlePlatformCookieSave(platform)}
                            loading={cookieSavingPlatform === platform}
                          >
                            更新 Cookie
                          </Button>
                          <Text type="secondary">
                            可直接粘贴浏览器整串 Cookie，或粘贴导出的 Cookie JSON。
                          </Text>
                        </Space>
                      </Col>
                    </Row>
                  </Card>
                );
              })}
              
              <Button type="primary" onClick={handlePlatformConfigSave} loading={loading}>
                <SaveOutlined /> 保存平台配置
              </Button>
            </Space>
          </Card>
        </TabPane>

        <TabPane 
          tab={
            <span>
              <ApiOutlined />
              模型配置
            </span>
          } 
          key="3"
        >
          <Card title="情感分析模型配置">
            <Form
              form={modelForm}
              layout="vertical"
              onFinish={handleModelConfigSave}
              initialValues={{
                model_name: 'bert-base-chinese',
                batch_size: 32,
                max_length: 128,
                confidence_threshold: 0.6,
                enable_gpu: true,
                model_version: '1.0.0'
              }}
            >
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="模型名称"
                    name="model_name"
                    rules={[{ required: true, message: '请选择模型' }]}
                  >
                    <Select>
                      <Option value="lxyuan/distilbert-base-multilingual-cased-sentiments-student">DistilBERT多语言情感版 (推荐)</Option>
                      <Option value="bert-base-chinese">BERT中文基础版</Option>
                      <Option value="bert-base-chinese-sentiment">BERT中文情感版</Option>
                      <Option value="roberta-base-chinese">RoBERTa中文基础版</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="模型版本"
                    name="model_version"
                  >
                    <Input disabled />
                  </Form.Item>
                </Col>
              </Row>
              
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="批处理大小"
                    name="batch_size"
                    rules={[{ required: true, message: '请输入批处理大小' }]}
                  >
                    <Input type="number" min={8} max={128} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="最大序列长度"
                    name="max_length"
                    rules={[{ required: true, message: '请输入最大序列长度' }]}
                  >
                    <Input type="number" min={64} max={512} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="置信度阈值"
                    name="confidence_threshold"
                    rules={[{ required: true, message: '请输入置信度阈值' }]}
                  >
                    <Input type="number" min={0.1} max={1.0} step={0.1} />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="启用GPU加速"
                    name="enable_gpu"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="自动模型更新"
                    name="auto_update"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading}>
                  <SaveOutlined /> 保存模型配置
                </Button>
              </Form.Item>
            </Form>
          </Card>

          <Card title="大语言模型配置" style={{ marginTop: '16px' }}>
            <Form
              form={llmForm}
              layout="vertical"
              onFinish={handleLLMConfigSave}
              initialValues={{
                provider: 'openai',
                model: 'gpt-3.5-turbo',
                api_base: 'https://api.openai.com/v1',
                max_tokens: 1000,
                temperature: 0.7,
                top_p: 0.9,
                frequency_penalty: 0.0,
                presence_penalty: 0.0
              }}
            >
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="提供商"
                    name="provider"
                    rules={[{ required: true, message: '请选择提供商' }]}
                  >
                    <Select>
                      <Option value="openai">OpenAI</Option>
                      <Option value="azure">Azure OpenAI</Option>
                      <Option value="claude">Claude</Option>
                      <Option value="custom">自定义</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="模型名称"
                    name="model"
                    rules={[{ required: true, message: '请选择模型' }]}
                  >
                    <Select>
                      <Option value="gpt-3.5-turbo">GPT-3.5 Turbo</Option>
                      <Option value="gpt-4">GPT-4</Option>
                      <Option value="gpt-4-turbo">GPT-4 Turbo</Option>
                      <Option value="claude-3-sonnet">Claude 3 Sonnet</Option>
                    </Select>
                  </Form.Item>
                </Col>
              </Row>
              
              <Form.Item
                label="API密钥"
                name="api_key"
                rules={[{ required: true, message: '请输入API密钥' }]}
              >
                <Input.Password placeholder="请输入您的API密钥" />
              </Form.Item>
              
              <Form.Item
                label="API基础地址"
                name="api_base"
              >
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>

              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="最大令牌数"
                    name="max_tokens"
                    rules={[{ required: true, message: '请输入最大令牌数' }]}
                  >
                    <Input type="number" min={100} max={8000} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="温度"
                    name="temperature"
                    rules={[{ required: true, message: '请输入温度值' }]}
                  >
                    <Input type="number" min={0.0} max={2.0} step={0.1} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="Top P"
                    name="top_p"
                    rules={[{ required: true, message: '请输入Top P值' }]}
                  >
                    <Input type="number" min={0.0} max={1.0} step={0.1} />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading}>
                  <SaveOutlined /> 保存大模型配置
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>

        <TabPane 
          tab={
            <span>
              <UserOutlined />
              用户管理
            </span>
          } 
          key="4"
        >
          <Card 
            title="用户管理"
            extra={
              <Button type="primary" onClick={() => setUserModalVisible(true)}>
                新增用户
              </Button>
            }
          >
            <Table
              columns={userColumns}
              dataSource={users}
              rowKey="id"
              pagination={{
                pageSize: 10,
                showSizeChanger: true,
                showQuickJumper: true
              }}
            />
          </Card>
        </TabPane>

        <TabPane 
          tab={
            <span>
              <SecurityScanOutlined />
              安全设置
            </span>
          } 
          key="5"
        >
          <Card title="安全设置">
            <Form
              layout="vertical"
              initialValues={{
                enable_login_captcha: true,
                enable_2fa: false,
                password_min_length: 8,
                password_complexity: 'medium',
                login_attempt_limit: 5,
                session_timeout: 3600,
                enable_audit_log: true
              }}
            >
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="启用登录验证码"
                    name="enable_login_captcha"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="启用双因素认证"
                    name="enable_2fa"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
              
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="密码最小长度"
                    name="password_min_length"
                    rules={[{ required: true, message: '请输入密码最小长度' }]}
                  >
                    <Input type="number" min={6} max={32} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="密码复杂度"
                    name="password_complexity"
                    rules={[{ required: true, message: '请选择密码复杂度' }]}
                  >
                    <Select>
                      <Option value="low">低（仅字母）</Option>
                      <Option value="medium">中（字母+数字）</Option>
                      <Option value="high">高（字母+数字+特殊字符）</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    label="登录尝试次数限制"
                    name="login_attempt_limit"
                    rules={[{ required: true, message: '请输入登录尝试次数限制' }]}
                  >
                    <Input type="number" min={3} max={10} />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="会话超时时间（秒）"
                    name="session_timeout"
                    rules={[{ required: true, message: '请输入会话超时时间' }]}
                  >
                    <Input type="number" min={600} max={86400} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="启用审计日志"
                    name="enable_audit_log"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading}>
                  <SaveOutlined /> 保存安全设置
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>
      </Tabs>

      {/* 用户编辑模态框 */}
      <Modal
        title={editingUser ? '编辑用户' : '新增用户'}
        open={userModalVisible}
        onCancel={() => {
          setUserModalVisible(false);
          userForm.resetFields();
          setEditingUser(null);
        }}
        onOk={() => userForm.submit()}
      >
        <Form
          form={userForm}
          layout="vertical"
          onFinish={handleUserSave}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input />
          </Form.Item>
          
          <Form.Item
            label="邮箱"
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效的邮箱地址' }
            ]}
          >
            <Input />
          </Form.Item>
          
          <Form.Item
            label="角色"
            name="role"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            <Select>
              <Option value="user">普通用户</Option>
              <Option value="admin">管理员</Option>
            </Select>
          </Form.Item>
          
          <Form.Item
            label="状态"
            name="status"
            rules={[{ required: true, message: '请选择状态' }]}
          >
            <Select>
              <Option value="active">活跃</Option>
              <Option value="inactive">未激活</Option>
            </Select>
          </Form.Item>
          
          {!editingUser && (
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default SettingsPage;
