/**
 * 导入视频面板 — 项目工作区 Step 1
 */

import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Button, message, Typography, Empty, Space, List } from 'antd';
import {
  InboxOutlined,
  FolderOpenOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';

const { Dragger } = Upload;
const { Title, Text } = Typography;

const CYAN = '#00d4ff';

interface Props {
  onNext: () => void;
}

const ImportPanel: React.FC<Props> = ({ onNext }) => {
  const { currentProject, importVideos, loadProjects } = useProjectStore();
  const navigate = useNavigate();
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(false);

  /* 文件拖拽导入 */
  const handleDrop = useCallback(async (files: File[]) => {
    if (!currentProject) return;
    if (files.length === 0) return;

    setImporting(true);
    try {
      const paths = files.map(f => f.path || f.name);
      const result = await importVideos(currentProject.id, paths);
      if (result.length > 0) {
        message.success(`成功导入 ${result.length} 个视频`);
        setImported(true);
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    } finally {
      setImporting(false);
    }
  }, [currentProject, importVideos]);

  /* 打开文件夹选择 */
  const handleOpenFolder = async () => {
    if (!currentProject) return;
    try {
      // 调用 Electron IPC 打开文件对话框
      if (window.electronAPI?.dialog?.openFile) {
        const result = await window.electronAPI.dialog.openFile({
          properties: ['openFile', 'multiSelections'],
          filters: [{ name: '视频文件', extensions: ['mp4', 'mov', 'avi', 'mkv', 'wmv'] }],
        });
        if (result.success && result.data && result.data.length > 0) {
          const videos = await importVideos(currentProject.id, result.data);
          if (videos.length > 0) {
            message.success(`成功导入 ${videos.length} 个视频`);
            setImported(true);
          }
        }
      } else {
        message.info('开发环境：请通过拖拽导入视频');
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败');
    }
  };

  /* 无项目 */
  if (!currentProject) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: '#6b7b9d' }}>
              请先选择或创建一个项目
              <br />
              <Button type="link" onClick={() => navigate('/')} style={{ color: CYAN, marginTop: 8 }}>
                返回工作台
              </Button>
            </span>
          }
        />
      </div>
    );
  }

  const videos = currentProject?.episode_count ?? 0;

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '40px 24px' }}>
      {/* 项目名称 */}
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <Title level={3} style={{ color: '#e0e6ed', margin: 0 }}>
          📁 {currentProject.name}
        </Title>
        <Text type="secondary" style={{ fontSize: 13, color: '#4a5a7a' }}>
          将视频素材导入到项目中
        </Text>
      </div>

      {/* 拖拽上传 */}
      <Dragger
        accept=".mp4,.mov,.avi,.mkv,.wmv"
        multiple
        showUploadList={false}
        disabled={importing}
        beforeUpload={(file) => {
          handleDrop([file as any]);
          return false;
        }}
        style={{
          background: 'rgba(0,212,255,0.03)',
          border: `2px dashed ${CYAN}33`,
          borderRadius: 16,
          padding: 40,
          transition: 'all 0.3s',
        }}
      >
        <p style={{ fontSize: 48, color: CYAN, margin: 0 }}><InboxOutlined /></p>
        <p style={{ color: '#c8d0dc', fontSize: 16, fontWeight: 500, margin: '12px 0 4px' }}>
          拖拽视频文件到此处
        </p>
        <p style={{ color: '#4a5a7a', fontSize: 13, margin: 0 }}>
          支持 MP4 / MOV / AVI / MKV / WMV
        </p>
      </Dragger>

      {/* 操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 24 }}>
        <Button
          icon={<FolderOpenOutlined />}
          onClick={handleOpenFolder}
          disabled={importing}
          style={{
            height: 44, borderRadius: 10, padding: '0 24px',
            borderColor: `${CYAN}44`, color: CYAN,
            background: 'transparent',
          }}
        >
          从文件夹选择
        </Button>
      </div>

      {/* 导入状态 */}
      {importing && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text style={{ color: CYAN }}>导入中...</Text>
        </div>
      )}

      {/* 已导入提示 */}
      {imported && (
        <div style={{
          textAlign: 'center', marginTop: 32, padding: 20,
          borderRadius: 12, background: 'rgba(0,212,255,0.06)',
          border: `1px solid ${CYAN}22`,
        }}>
          <CheckCircleOutlined style={{ fontSize: 32, color: '#10b981' }} />
          <Title level={4} style={{ color: '#e0e6ed', margin: '8px 0 4px' }}>导入完成</Title>
          <Text style={{ color: '#4a5a7a' }}>共 {videos} 个视频已就绪</Text>
          <br />
          <Button
            type="primary"
            size="large"
            onClick={onNext}
            style={{
              marginTop: 16, height: 44, borderRadius: 10, padding: '0 32px',
              background: `linear-gradient(135deg, ${CYAN}, #7c3aed)`,
              border: 'none', fontWeight: 600, letterSpacing: 1,
              boxShadow: `0 0 20px ${CYAN}33`,
            }}
          >
            <Space>
              开始 AI 分析
              <PlayCircleOutlined />
            </Space>
          </Button>
        </div>
      )}
    </div>
  );
};

export default ImportPanel;
