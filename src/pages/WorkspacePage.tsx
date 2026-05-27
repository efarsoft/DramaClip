/**
 * 项目工作区 — 步骤化智能剪辑工作流
 *
 * 顶部水平步骤条 + 内容面板切换 + 底部状态
 */

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Tooltip, message } from 'antd';
import {
  HomeOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../stores/projectStore';
import { useUiStore } from '../stores/uiStore';
import { useTaskQueueStore } from '../stores/taskQueueStore';

import ImportPanel from './workspace/ImportPanel';
import AnalyzePanel from './workspace/AnalyzePanel';
import RecommendPanel from './workspace/RecommendPanel';
import EditPanel from './workspace/EditPanel';
import ExportPanel from './workspace/ExportPanel';

/* ─── 颜色常量 ─── */
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';
const BG_DEEP = '#060a17';

/* ─── 步骤定义 ─── */
const STEPS = [
  { key: 'import', label: '导入视频', icon: '📁', desc: '导入视频素材' },
  { key: 'analyze', label: 'AI 分析', icon: '🤖', desc: '智能分析内容' },
  { key: 'recommend', label: '方案推荐', icon: '✨', desc: '选择剪辑方案' },
  { key: 'export', label: '导出发布', icon: '🚀', desc: '输出成品' },
] as const;

type StepKey = (typeof STEPS)[number]['key'];

/* ─── CSS 注入 ─── */
const injectStyles = () => {
  const id = 'workspace-styles';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes stepGlow {
      0%, 100% { box-shadow: 0 0 8px rgba(0,212,255,0.2); }
      50% { box-shadow: 0 0 20px rgba(0,212,255,0.4); }
    }
    .workspace-step-active {
      animation: stepGlow 2s ease-in-out infinite;
    }
    @keyframes fadeSlideIn {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .workspace-panel {
      animation: fadeSlideIn 0.35s ease forwards;
    }
  `;
  document.head.appendChild(style);
};

/* ─── 工作区组件 ─── */
const WorkspacePage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { currentProject, openProject, loadProjects } = useProjectStore();
  const { backendStatus } = useUiStore();
  const { isRunning } = useTaskQueueStore();

  const [currentStep, setCurrentStep] = useState<StepKey>('import');

  useEffect(() => { injectStyles(); }, []);

  /* 打开项目 */
  useEffect(() => {
    if (projectId) {
      openProject(projectId).then((p) => {
        if (p.status === 'analyzing') {
          setCurrentStep('analyze');
        } else if (p.status === 'ready' || p.status === 'clipping') {
          setCurrentStep('recommend');
        } else if (p.status === 'exporting') {
          setCurrentStep('export');
        } else if (p.episode_count && p.episode_count > 0) {
          // Idle项目有导入视频时，应当默认停在导入/勾选视频的第一步，而非直接跳过选择视频阶段
          setCurrentStep('import');
        } else {
          setCurrentStep('import');
        }
      }).catch(() => {
        message.error('无法打开项目');
        navigate('/');
      });
    }
  }, [projectId]);

  /* 下一步 */
  const goNext = () => {
    const idx = STEPS.findIndex(s => s.key === currentStep);
    if (idx < STEPS.length - 1) {
      setCurrentStep(STEPS[idx + 1].key);
    }
  };

  /* 上一步 */
  const goPrev = () => {
    const idx = STEPS.findIndex(s => s.key === currentStep);
    if (idx > 0) {
      setCurrentStep(STEPS[idx - 1].key);
    }
  };

  const currentIdx = STEPS.findIndex(s => s.key === currentStep);

  /* ─── 渲染当前面板 ─── */
  const renderPanel = () => {
    switch (currentStep) {
      case 'import':
        return <ImportPanel onNext={goNext} />;
      case 'analyze':
        return <AnalyzePanel onNext={goNext} />;
      case 'recommend':
        return <RecommendPanel onNext={goNext} />;
      case 'export':
        return <ExportPanel onComplete={() => navigate('/')} />;
      default:
        return <ImportPanel onNext={goNext} />;
    }
  };

  const isCompleted = (idx: number) => idx < currentIdx;
  const isActive = (idx: number) => idx === currentIdx;
  const isPending = (idx: number) => idx > currentIdx && idx > 0;

  return (
    <div style={{
      height: '100vh', background: BG_DEEP,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* ─── 顶部导航栏 ─── */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 32px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        background: 'rgba(6,10,23,0.95)',
        backdropFilter: 'blur(12px)',
        position: 'sticky', top: 0, zIndex: 100,
      }}>
        {/* 左侧：返回 + Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Tooltip title="返回工作台">
            <Button
              type="text"
              icon={<HomeOutlined />}
              onClick={() => navigate('/')}
              style={{ color: '#4a5a7a', fontSize: 18 }}
            />
          </Tooltip>
          <span style={{
            fontSize: 16, fontWeight: 700, letterSpacing: 3,
            background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            fontFamily: "'Orbitron', sans-serif",
          }}>
            DRAMA CLIP
          </span>
          {currentProject && (
            <span style={{
              color: '#4a5a7a', fontSize: 13, fontFamily: "'Orbitron', monospace",
              letterSpacing: 1, borderLeft: '1px solid #1e2540', paddingLeft: 12,
            }}>
              {currentProject.name}
            </span>
          )}
        </div>

        {/* 右侧：设置 + 后端状态 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: backendStatus === 'ready' ? '#10b981' : backendStatus === 'error' ? '#ef4444' : '#f59e0b',
            boxShadow: `0 0 8px ${backendStatus === 'ready' ? '#10b981' : backendStatus === 'error' ? '#ef4444' : '#f59e0b'}66`,
          }} />
          <span style={{ color: '#4a5a7a', fontSize: 12 }}>
            {backendStatus === 'ready' ? '已连接' : backendStatus === 'error' ? '异常' : '连接中'}
          </span>
          <Button
            type="text"
            icon={<SettingOutlined />}
            onClick={() => navigate('/settings')}
            style={{ color: '#4a5a7a', fontSize: 16 }}
          />
        </div>
      </header>

      {/* ─── 水平步骤条 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '20px 32px', gap: 0,
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        background: 'rgba(255,255,255,0.01)',
      }}>
        {STEPS.map((step, idx) => {
          const completed = isCompleted(idx);
          const active = isActive(idx);
          const pending = isPending(idx);

          return (
            <React.Fragment key={step.key}>
              {/* 步骤项 */}
              <div
                onClick={() => {
                  // 只允许点击已完成和当前步骤
                  if (completed || active) setCurrentStep(step.key);
                }}
                className={active ? 'workspace-step-active' : ''}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 20px', borderRadius: 12,
                  cursor: (completed || active) ? 'pointer' : 'default',
                  background: active ? `linear-gradient(135deg, ${CYAN}11, ${PURPLE}11)` : 'transparent',
                  border: active ? `1px solid ${CYAN}33` : '1px solid transparent',
                  transition: 'all 0.3s',
                  opacity: pending ? 0.35 : 1,
                }}
              >
                {/* 步骤编号/图标 */}
                <div style={{
                  width: 32, height: 32, borderRadius: 10,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 14,
                  background: completed
                    ? `linear-gradient(135deg, ${CYAN}, ${PURPLE})`
                    : active
                      ? `rgba(255,255,255,0.08)`
                      : 'rgba(255,255,255,0.03)',
                  color: completed ? '#fff' : active ? CYAN : '#3a4a6a',
                  fontWeight: 700,
                  fontFamily: "'JetBrains Mono', monospace",
                  border: active ? `1px solid ${CYAN}44` : '1px solid transparent',
                }}>
                  {completed ? '✓' : (idx + 1)}
                </div>

                {/* 标签 */}
                <div>
                  <div style={{
                    color: completed ? CYAN : active ? '#e0e6ed' : '#3a4a6a',
                    fontSize: 14, fontWeight: active ? 600 : 400,
                    letterSpacing: 0.5,
                    transition: 'color 0.3s',
                  }}>
                    {step.icon} {step.label}
                  </div>
                  <div style={{
                    color: '#3a4a6a', fontSize: 11, marginTop: 1,
                  }}>
                    {step.desc}
                  </div>
                </div>
              </div>

              {/* 连接线 */}
              {idx < STEPS.length - 1 && (
                <div style={{
                  flex: 1, maxWidth: 48, height: 2, margin: '0 4px',
                  borderRadius: 1,
                  background: completed
                    ? `linear-gradient(90deg, ${CYAN}66, ${PURPLE}66)`
                    : 'rgba(255,255,255,0.06)',
                  transition: 'all 0.5s',
                }} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* ─── 主面板区 ─── */}
      <main style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        overflow: 'auto', position: 'relative', minHeight: 0,
      }}>
        <div className="workspace-panel" style={{ flex: 1 }}>
          {renderPanel()}
        </div>
      </main>

      {/* ─── 底部导航 ─── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 32px',
        borderTop: '1px solid rgba(255,255,255,0.04)',
        background: 'rgba(6,10,23,0.95)',
        backdropFilter: 'blur(12px)',
      }}>
        <Button
          onClick={goPrev}
          disabled={currentIdx === 0}
          style={{
            borderRadius: 8, height: 38, padding: '0 20px',
            borderColor: 'rgba(255,255,255,0.1)', color: currentIdx > 0 ? '#c8d0dc' : '#3a4a6a',
            background: 'transparent',
          }}
        >
          上一步
        </Button>

        <span style={{ color: '#3a4a6a', fontSize: 12, fontFamily: "'JetBrains Mono', monospace" }}>
          Step {currentIdx + 1} / {STEPS.length}
        </span>

        {currentStep !== 'export' && (
          <Button
            onClick={goNext}
            disabled={currentStep === 'analyze' && isRunning}
            style={{
              borderRadius: 8, height: 38, padding: '0 24px',
              background: (currentStep === 'analyze' && isRunning) ? 'rgba(255,255,255,0.03)' : `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
              border: (currentStep === 'analyze' && isRunning) ? '1px solid rgba(255,255,255,0.05)' : 'none',
              color: (currentStep === 'analyze' && isRunning) ? '#4a5a7a' : '#fff',
              fontWeight: 600,
              boxShadow: (currentStep === 'analyze' && isRunning) ? 'none' : `0 0 16px ${CYAN}22`,
              cursor: (currentStep === 'analyze' && isRunning) ? 'not-allowed' : 'pointer',
            }}
          >
            下一步
          </Button>
        )}
      </div>
    </div>
  );
};

export default WorkspacePage;
