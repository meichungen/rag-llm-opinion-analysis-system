import React, { useState, useEffect } from 'react';
import { Layout, Menu, theme, Button, Drawer, Badge, Progress, Tooltip, Space } from 'antd';
import {
  HomeOutlined,
  SearchOutlined,
  BarChartOutlined,
  RobotOutlined,
  SettingOutlined,
  MenuUnfoldOutlined,
  MenuFoldOutlined,
  FireOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import type { MenuProps } from 'antd';
import api, { endpoints } from '../services/api';

const { Header, Content, Footer, Sider } = Layout;

type MenuItem = Required<MenuProps>['items'][number];

function getItem(
  label: React.ReactNode,
  key: React.Key,
  icon?: React.ReactNode,
  children?: MenuItem[],
): MenuItem {
  return {
    key,
    icon,
    children,
    label,
  } as MenuItem;
}

const items: MenuItem[] = [
  getItem('首页', '/', <HomeOutlined />),
  getItem('热点追踪', '/hot-topics', <FireOutlined />),
  getItem('任务管理', '/tasks', <SearchOutlined />),
  getItem('数据分析', '/analysis', <BarChartOutlined />),
  getItem('智能问答', '/qa', <RobotOutlined />),
  getItem('系统设置', '/settings', <SettingOutlined />),
];

const MainLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [activeTask, setActiveTask] = useState<any>(null);
  const [siteName, setSiteName] = useState('社交媒体分析');
  const navigate = useNavigate();
  const location = useLocation();
  const showGlobalTaskProgress = location.pathname !== '/tasks';
  
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();

  // 获取系统配置
  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const response = await api.get(endpoints.settings);
        if (response.data && response.data.system) {
          const { site_name } = response.data.system;
          if (site_name) {
            setSiteName(site_name);
            document.title = site_name;
          }
        }
      } catch (e) {
        console.error("Failed to fetch settings", e);
      }
    };
    fetchSettings();
  }, []);

  // Poll for active tasks
  useEffect(() => {
    const checkTasks = async () => {
      try {
        const response = await api.get(endpoints.tasks, { params: { limit: 5 } });
        if (response.data && response.data.tasks) {
          const running = response.data.tasks.find((t: any) => t.status === 'running');
          setActiveTask(running || null);
        }
      } catch (e) {
        console.error("Failed to check active tasks", e);
      }
    };

    checkTasks();
    const interval = setInterval(checkTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleMenuClick: MenuProps['onClick'] = (e) => {
    navigate(e.key);
    setMobileDrawerOpen(false);
  };

  const MenuContent = (
    <>
      <div className="logo">
        {!collapsed && siteName}
        {collapsed && (siteName.length > 3 ? siteName.substring(0, 3) : siteName)}
      </div>
      <Menu
        theme="dark"
        selectedKeys={[location.pathname]}
        mode="inline"
        items={items}
        onClick={handleMenuClick}
      />
    </>
  );

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider 
        trigger={null}
        collapsible 
        collapsed={collapsed}
        breakpoint="lg"
        collapsedWidth="80"
        onBreakpoint={(broken) => {
          if (broken) {
            setCollapsed(true);
          }
        }}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
          boxShadow: '2px 0 8px 0 rgba(29,35,41,0.05)'
        }}
        className="desktop-sider"
      >
        {MenuContent}
      </Sider>

      <Drawer
        placement="left"
        onClose={() => setMobileDrawerOpen(false)}
        open={mobileDrawerOpen}
        styles={{ body: { padding: 0, background: '#001529' } }}
        width={250}
      >
        {MenuContent}
      </Drawer>
      
      <Layout style={{ 
        marginLeft: collapsed ? 80 : 200, 
        transition: 'all 0.2s',
      }} className="site-layout">
        <Header style={{ 
          padding: 0, 
          background: colorBgContainer, 
          boxShadow: '0 1px 4px rgba(0,21,41,0.08)',
          display: 'flex',
          alignItems: 'center',
          position: 'sticky',
          top: 0,
          zIndex: 99,
          width: '100%',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
              style={{
                fontSize: '16px',
                width: 64,
                height: 64,
              }}
              className="trigger-btn desktop-trigger"
            />
            <Button
               type="text"
               icon={<MenuUnfoldOutlined />}
               onClick={() => setMobileDrawerOpen(true)}
               style={{
                 fontSize: '16px',
                 width: 64,
                 height: 64,
               }}
               className="trigger-btn mobile-trigger"
             />

            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#1890ff', marginLeft: 8 }}>
              社交媒体分析系统
            </h2>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', paddingRight: 24 }}>
            {activeTask && showGlobalTaskProgress && (
              <div style={{ marginRight: 24, width: 200, display: 'flex', alignItems: 'center' }}>
                <Tooltip title={`正在执行: ${activeTask.keyword} (${activeTask.platform})`}>
                  <div style={{ width: '100%' }}>
                    <div style={{ fontSize: '12px', display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={{ color: '#888' }}><SyncOutlined spin /> 任务进行中</span>
                      <span>{activeTask.progress}%</span>
                    </div>
                    <Progress percent={activeTask.progress} size="small" showInfo={false} strokeColor="#1890ff" />
                  </div>
                </Tooltip>
              </div>
            )}
            
            <Space size="middle">
              <Badge dot={!!activeTask}>
                <Button type="text" icon={<SettingOutlined />} onClick={() => navigate('/settings')} />
              </Badge>
            </Space>
          </div>
        </Header>
        
        <Content style={{ margin: '16px', overflow: 'initial' }}>
          <div
            style={{
              padding: 24,
              background: colorBgContainer,
              borderRadius: borderRadiusLG,
              minHeight: 'calc(100vh - 64px - 32px - 70px)',
              boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
            }}
          >
            <Outlet />
          </div>
        </Content>
        
        <Footer style={{ textAlign: 'center', color: '#999' }}>
          社交媒体热点话题发现与情感分析系统 ©2025 Created by meichungen
        </Footer>
      </Layout>
    </Layout>
  );
};

export default MainLayout;
