/**
 * 项目管理页面（深色科技感主题）
 */

import React, { useEffect, useState } from 'react';
import { Button, Modal, Form, Input, Typography, Space, message, Layout, Card, List, Tag, Empty } from 'antd';
import {
  PlusOutlined,
  ImportOutlined,
  ArrowLeftOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { ProjectList } from '../components/project/ProjectList';
import { FileDropZone } from '../components/common/FileDropZone';
import { useProjectStore } from '../stores/projectStore';
import type { Project } from '../services/ipc';

const { Content } = Layout;
const { Title } = Typography;

// 深色科技感样式常量
const DARK_BG = '#0a0e1a';
const SURFACE = '#131829';
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

const projectPageStyles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: DARK_BG,
    minHeight: '100vh',
    padding: 24,
  },
  toolbar: {
    marginBottom: 24,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  glowButton: {
    background: `linear-gradient(135deg, ${CYAN}, #00a8cc)`,
    border: 'none',
    borderRadius: 8,
    color: '#fff',
    fontWeight: 600,
    boxShadow: `0 0 16px ${CYAN}40, 0 0 32px ${CYAN}20`,
    transition: 'all 0.3s ease',
  },
  glowButtonHover: {
    boxShadow: `0 0 24px ${CYAN}60, 0 0 48px ${CYAN}30`,
    transform: 'translateY(-1px)',
  },
  surfaceCard: {
    backgroundColor: SURFACE,
    border: `1px solid ${CYAN}30`,
    borderRadius: 12,
    transition: 'all 0.3s ease',
    boxShadow: `0 4px 24px rgba(0, 0, 0, 0.4), inset 0 1px 0 ${CYAN}10`,
  },
  surfaceCardHover: {
    borderColor: CYAN,
    boxShadow: `0 0 20px ${CYAN}30, 0 4px 24px rgba(0, 0, 0, 0.5), inset 0 1px 0 ${CYAN}20`,
  },
  darkTitle: {
    color: '#e0e6ed',
    textShadow: `0 0 20px ${CYAN}40`,
  },
  darkText: {
    color: '#b0bac9',
  },
  darkInput: {
    backgroundColor: `${SURFACE}ee`,
    border: `1px solid ${CYAN}20`,
    borderRadius: 8,
    color: '#e0e6ed',
  },
  darkTag: {
    backgroundColor: `${CYAN}15`,
    borderColor: `${CYAN}40`,
    color: CYAN,
  },
  importButton: {
    background: `linear-gradient(135deg, ${PURPLE}, #6d28d9)`,
    border: 'none',
    borderRadius: 8,
    color: '#fff',
    fontWeight: 600,
    boxShadow: `0 0 16px ${PURPLE}40, 0 0 32px ${PURPLE}20`,
  },
};

export const ProjectPage: React.FC = () => {
  const {
    projects,
    currentProject,
    currentVideos,
    isLoading,
    error,
    loadProjects,
    createProject,
    openProject,
    deleteProject,
    importVideos,
    setCurrentProject,
    clearError,
  } = useProjectStore();

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [cardHovered, setCardHovered] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (error) {
      message.error(error);
      clearError();
    }
  }, [error, clearError]);

  const handleCreateProject = async () => {
    try {
      const values = await form.validateFields();
      await createProject(values.name, values.path || '');
      setCreateDialogOpen(false);
      form.resetFields();
      message.success('项目创建成功');
    } catch {
      // validation or store error
    }
  };

  const handleOpenProject = async (project: Project) => {
    if (!project) return;
    try {
      await openProject(project.id);
    } catch {
      // handled by store
    }
  };

  const handleDeleteProject = (project: Project) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个项目吗？此操作不可撤销。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteProject(project.id);
          message.success('项目已删除');
        } catch {
          // handled by store
        }
      },
    });
  };

  const handleImportVideos = async (paths: string[]) => {
    if (!currentProject || paths.length === 0) return;
    try {
      await importVideos(currentProject.id, paths);
      setImportDialogOpen(false);
      message.success(`已导入  个视频文件`);
    } catch {
      // handled by store
    }
  };

  const handleBack = () => {
    setCurrentProject(null);
  };

  // ===== 项目详情视图 =====
  if (currentProject) {
    return (
      <Content style={projectPageStyles.container}>
        {/* 顶部工具栏 */}
        <div style={projectPageStyles.toolbar}>
          <Space>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={handleBack}
              style={{ backgroundColor: SURFACE, color: CYAN, borderColor: `${CYAN}40` }}
            >
              返回
            </Button>
            <Title level={4} style={{ ...projectPageStyles.darkTitle, margin: 0 }}>{currentProject.name}</Title>
            <Tag style={projectPageStyles.darkTag}>
              {currentProject.status === 'ready' ? '就绪' : '空闲'}
            </Tag>
          </Space>
          <Button icon={<ImportOutlined />} onClick={() => setImportDialogOpen(true)} style={projectPageStyles.importButton}>
            导入视频
          </Button>
        </div>

        {/* 视频列表 */}
        <Card
          title={<Space><VideoCameraOutlined style={{ color: CYAN }} />视频列表</Space>}
          style={projectPageStyles.surfaceCard}
        >
          {currentVideos.length === 0 ? (
            <Empty description="暂无视频，请导入视频文件" />
          ) : (
            <List
              dataSource={currentVideos}
              renderItem={(video) => (
                <List.Item
                  style={{
                    backgroundColor: `${SURFACE}80`,
                    borderBottom: `1px solid ${CYAN}15`,
                    color: projectPageStyles.darkText.color,
                  }}
                >
                  <List.Item.Meta
                    avatar={<VideoCameraOutlined style={{ fontSize: 24, color: CYAN }} />}
                    title={<span style={projectPageStyles.darkText}>{video.name}</span>}
                    description={<span style={{ ...projectPageStyles.darkText, fontSize: 12 }}>大小: --</span>}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>

        {/* 导入视频对话框 */}
        <Modal
          title={<span style={projectPageStyles.darkTitle}>导入视频文件</span>}
          open={importDialogOpen}
          onCancel={() => setImportDialogOpen(false)}
          footer={null}
          width={600}
          bodyStyle={{ backgroundColor: SURFACE }}
        >
          <FileDropZone onFilesSelected={handleImportVideos} />
        </Modal>
      </Content>
    );
  }

  // ===== 项目列表视图 =====
  return (
    <Content style={projectPageStyles.container}>
      {/* 顶部工具栏 */}
      <div style={projectPageStyles.toolbar}>
        <Title level={4} style={projectPageStyles.darkTitle}>项目列表</Title>
        <Button
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setCreateDialogOpen(true);
          }}
          style={projectPageStyles.glowButton}
        >
          新建项目
        </Button>
      </div>

      {/* 项目列表 */}
      <Card style={projectPageStyles.surfaceCard}>
        <ProjectList
          projects={projects}
          isLoading={isLoading}
          onOpen={handleOpenProject}
          onDelete={handleDeleteProject}
        />
      </Card>

      {/* 创建项目对话框 */}
      <Modal
        title={<span style={projectPageStyles.darkTitle}>新建项目</span>}
        open={createDialogOpen}
        onOk={handleCreateProject}
        onCancel={() => setCreateDialogOpen(false)}
        okText={<span style={{ color: CYAN }}>创建</span>}
        cancelText={<span style={projectPageStyles.darkText}>取消</span>}
        okButtonProps={{ style: { ...projectPageStyles.glowButton, background: 'transparent', boxShadow: 'none' } }}
        cancelButtonProps={{ style: { color: projectPageStyles.darkText.color } }}
      >
        <div style={{ padding: '12px 0' }}>
          <Form form={form} layout="vertical">
            <Form.Item
              name="name"
              label={<span style={projectPageStyles.darkText}>项目名称</span>}
              rules={[{ required: true, message: '请输入项目名称' }]}
            >
              <Input placeholder="输入项目名称" style={projectPageStyles.darkInput} />
            </Form.Item>
            <Form.Item
              name="path"
              label={<span style={projectPageStyles.darkText}>存储路径</span>}
              extra={<span style={projectPageStyles.darkText}>留空将在用户目录下创建项目</span>}
            >
              <Input placeholder="留空则使用默认路径" style={projectPageStyles.darkInput} />
            </Form.Item>
          </Form>
        </div>
      </Modal>
    </Content>
  );
};

export default ProjectPage;
