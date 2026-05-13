/**
 * 项目列表组件
 * 深色科技感风格：暗色背景渐变卡片容器，loading 带 cyan 辉光
 */

import React from 'react';
import { Row, Col, Spin, Empty, Typography } from 'antd';
import { FolderOutlined } from '@ant-design/icons';
import { ProjectCard } from './ProjectCard';
import type { Project } from '../../services/ipc';

const { Text } = Typography;

interface ProjectListProps {
  projects: Project[];
  isLoading: boolean;
  onOpen: (project: Project) => void;
  onDelete: (project: Project) => void;
}

export const ProjectList: React.FC<ProjectListProps> = ({
  projects,
  isLoading,
  onOpen,
  onDelete,
}) => {
  // 深色科技感背景渐变
  const darkBgStyle = {
    background: 'linear-gradient(135deg, #0a0e1a 0%, #131829 50%, #0d1225 100%)',
    borderRadius: 12,
  };

  if (isLoading) {
    return (
      <div
        style={{
          ...darkBgStyle,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: 300,
        }}
      >
        <Spin
          size="large"
          style={{
            filter: 'drop-shadow(0 0 8px rgba(0, 212, 255, 0.6))',
          }}
        />
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <Empty
        image={
          <FolderOutlined
            style={{
              fontSize: 64,
              filter: 'drop-shadow(0 0 12px rgba(124, 58, 237, 0.5))',
              opacity: 0.6,
            }}
          />
        }
        description={
          <>
            <Text strong style={{ color: '#00d4ff' }}>暂无项目</Text>
            <br />
            <Text style={{ color: 'rgba(255,255,255,0.45)' }}>
              点击「新建项目」按钮创建您的第一个项目
            </Text>
          </>
        }
        style={{ padding: '80px 0', ...darkBgStyle }}
      />
    );
  }

  return (
    <Row
      gutter={[16, 16]}
      style={{ padding: 16, ...darkBgStyle, minHeight: 400 }}
    >
      {projects.map((project) => (
        <Col xs={24} sm={12} lg={8} xl={6} key={project.id}>
          <ProjectCard
            project={project}
            onOpen={onOpen}
            onDelete={onDelete}
          />
        </Col>
      ))}
    </Row>
  );
};

export default ProjectList;
