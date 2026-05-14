/**
 * 创作工作台 — 首页
 * 深空科技感全屏设计
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PlusOutlined,
  FolderOpenOutlined,
  EditOutlined,
  DeleteOutlined,
  AppstoreOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { Modal, Input, message } from 'antd';
import { useProjectStore } from '../stores/projectStore';
import type { Project } from '../services/ipc';

/* ─── 颜色常量 ─── */
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';
const BG_DEEP = '#060a17';

/* ─── CSS 注入 ─── */
const injectHomeStyles = () => {
  const id = 'homepage-sci-fi';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes homeFloat {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(-12px); }
    }
    @keyframes homePulse {
      0%, 100% { opacity: 0.3; transform: scale(1); }
      50% { opacity: 0.6; transform: scale(1.05); }
    }
    @keyframes gridScroll {
      0% { background-position: 0 0; }
      100% { background-position: 60px 60px; }
    }
    @keyframes titleGlow {
      0%, 100% { filter: drop-shadow(0 0 20px rgba(0,212,255,0.3)) drop-shadow(0 0 40px rgba(0,212,255,0.1)); }
      50% { filter: drop-shadow(0 0 30px rgba(0,212,255,0.6)) drop-shadow(0 0 60px rgba(0,212,255,0.2)); }
    }
    @keyframes borderFlow {
      0% { background-position: 0% 50%; }
      50% { background-position: 100% 50%; }
      100% { background-position: 0% 50%; }
    }
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .home-card {
      animation: fadeInUp 0.6s ease forwards;
      opacity: 0;
    }
    .home-card:nth-child(1) { animation-delay: 0.1s; }
    .home-card:nth-child(2) { animation-delay: 0.25s; }
    .home-card:nth-child(3) { animation-delay: 0.4s; }

    .home-grid-bg {
      background-image:
        linear-gradient(rgba(0,212,255,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,212,255,0.04) 1px, transparent 1px);
      background-size: 60px 60px;
      animation: gridScroll 20s linear infinite;
    }

    .home-recent-item {
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      cursor: pointer;
    }
    .home-recent-item:hover {
      transform: translateY(-2px);
      border-color: ${CYAN}44 !important;
      box-shadow: 0 4px 24px rgba(0,212,255,0.12);
    }
  `;
  document.head.appendChild(style);
};

/* ─── 格式化时间 ─── */
const fmtDate = (iso: string) => {
  try {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  } catch { return iso; }
};

/* ─── 首页组件 ─── */
const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { projects, loadProjects, createProject, openProject, deleteProject, renameProject } = useProjectStore();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [renamingProject, setRenamingProject] = useState<Project | null>(null);
  const [renameName, setRenameName] = useState('');

  useEffect(() => { injectHomeStyles(); loadProjects(); }, []);

  /* 创建项目 */
  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const p = await createProject(newName.trim(), '');
      setCreating(false);
      setNewName('');
      navigate(`/workspace/${p.id}`);
    } catch (e: any) {
      message.error(e?.message || '创建失败');
    }
  };

  /* 打开已有项目 → 进入工作区 */
  const handleOpen = async (p: Project) => {
    try {
      await openProject(p.id);
      navigate(`/workspace/${p.id}`);
    } catch (e: any) {
      message.error(e?.message || '打开失败');
    }
  };

  /* 打开文件夹（浏览已有项目） */
  const handleOpenFolder = async () => {
    try {
      let folderPath: string | undefined;
      if (window.electronAPI?.dialog?.openFolder) {
        const result = await window.electronAPI.dialog.openFolder();
        folderPath = result?.data;
      }
      if (!folderPath) {
        // 无 Electron API 或用户取消，刷新列表展示已有项目
        await loadProjects();
        return;
      }
      // 查找该路径是否已有项目
      const existing = projects.find(p => p.path === folderPath);
      if (existing) {
        await handleOpen(existing);
      } else {
        // 不在此路径下创建项目，提示用户使用"新建项目"
        message.info('该文件夹尚未创建项目，请使用「新建项目」');
        // 刷新列表（可能在外部新增了项目文件）
        await loadProjects();
      }
    } catch (e: any) {
      message.error(e?.message || '打开文件夹失败');
    }
  };

  /* 删除项目 */
  const handleDelete = async (e: React.MouseEvent, p: Project) => {
    e.stopPropagation();
    try {
      await deleteProject(p.id, false);
    } catch (err: any) {
      message.error(err?.message || '删除失败');
    }
  };

  /* 打开重命名对话框 */
  const handleRenameOpen = (e: React.MouseEvent, p: Project) => {
    e.stopPropagation();
    setRenamingProject(p);
    setRenameName(p.name);
  };

  /* 确认重命名 */
  const handleRenameConfirm = async () => {
    if (!renamingProject || !renameName.trim()) return;
    try {
      await renameProject(renamingProject.id, renameName.trim());
      setRenamingProject(null);
      setRenameName('');
      message.success('重命名成功');
    } catch (err: any) {
      message.error(err?.message || '重命名失败');
    }
  };

  return (
    <div
      className="home-grid-bg"
      style={{
        minHeight: '100vh',
        background: BG_DEEP,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'auto',
      }}
    >
      {/* ─── 装饰性光晕 ─── */}
      <div style={{
        position: 'absolute', top: '-20%', left: '-10%', width: '60%', height: '60%',
        background: `radial-gradient(ellipse, rgba(0,212,255,0.08) 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', bottom: '-20%', right: '-10%', width: '60%', height: '60%',
        background: `radial-gradient(ellipse, rgba(124,58,237,0.08) 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* ─── 顶部导航栏 ─── */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 48px', borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            fontSize: 22, fontWeight: 800, letterSpacing: 4,
            background: `linear-gradient(135deg, ${CYAN} 0%, ${PURPLE} 100%)`,
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            fontFamily: "'Orbitron', sans-serif",
          }}>DRAMA CLIP</span>
          <span style={{
            fontSize: 11, color: '#4a5a7a', fontFamily: "'Orbitron', monospace",
            letterSpacing: 2, borderLeft: '1px solid #1e2540', paddingLeft: 12,
          }}>v1.0.0</span>
        </div>
        <button
          onClick={() => navigate('/settings')}
          style={{
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 8, padding: '6px 20px', color: '#7a8aa0', cursor: 'pointer',
            fontSize: 13, transition: 'all 0.2s', letterSpacing: 1,
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = `${CYAN}44`; e.currentTarget.style.color = CYAN; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = '#7a8aa0'; }}
        >
          系统设置
        </button>
      </header>

      {/* ─── 主内容区 ─── */}
      <main style={{
        flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        padding: '60px 48px 40px',
      }}>
        {/* ── Hero 标题区 ── */}
        <div style={{ textAlign: 'center', marginBottom: 56, animation: 'titleGlow 4s ease-in-out infinite' }}>
          <h1 style={{
            fontSize: 64, fontWeight: 900, margin: 0, letterSpacing: 8,
            background: `linear-gradient(135deg, #ffffff 0%, ${CYAN} 40%, ${PURPLE} 70%, ${CYAN} 100%)`,
            backgroundSize: '200% 200%',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            fontFamily: "'Orbitron', sans-serif",
            lineHeight: 1.2,
          }}>
            DRAMA CLIP
          </h1>
          <p style={{
            color: '#4a5a7a', fontSize: 16, letterSpacing: 6, marginTop: 12,
            fontFamily: "'Orbitron', monospace",
          }}>
            AI · 智能剪辑工作台
          </p>
        </div>

        {/* ── 三张 Action 卡片 ── */}
        <div style={{
          display: 'flex', gap: 24, marginBottom: 60,
          flexWrap: 'wrap', justifyContent: 'center',
        }}>
          {/* 新建项目 */}
          <div className="home-card" onClick={() => setCreating(true)}
            style={{
              width: 240, padding: '36px 28px', borderRadius: 16,
              background: 'linear-gradient(135deg, rgba(0,212,255,0.08) 0%, rgba(0,212,255,0.02) 100%)',
              border: `1px solid ${CYAN}22`, cursor: 'pointer',
              backdropFilter: 'blur(12px)',
              textAlign: 'center', transition: 'all 0.3s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = `${CYAN}66`;
              e.currentTarget.style.boxShadow = `0 0 30px ${CYAN}22, inset 0 0 30px ${CYAN}11`;
              e.currentTarget.style.transform = 'translateY(-4px)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = `${CYAN}22`;
              e.currentTarget.style.boxShadow = 'none';
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            <div style={{
              width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
              background: `linear-gradient(135deg, ${CYAN}22, ${CYAN}44)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 26, color: CYAN,
            }}><PlusOutlined /></div>
            <h3 style={{ margin: '0 0 8px', color: '#e0e6ed', fontSize: 18, fontWeight: 600 }}>新建项目</h3>
            <p style={{ margin: 0, color: '#5a6a8a', fontSize: 13 }}>创建一个新的剪辑项目</p>
          </div>

          {/* 打开项目 */}
          <div className="home-card"
            onClick={handleOpenFolder}
            style={{
              width: 240, padding: '36px 28px', borderRadius: 16,
              background: 'linear-gradient(135deg, rgba(124,58,237,0.08) 0%, rgba(124,58,237,0.02) 100%)',
              border: `1px solid ${PURPLE}22`, cursor: 'pointer',
              backdropFilter: 'blur(12px)',
              textAlign: 'center', transition: 'all 0.3s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = `${PURPLE}66`;
              e.currentTarget.style.boxShadow = `0 0 30px ${PURPLE}22, inset 0 0 30px ${PURPLE}11`;
              e.currentTarget.style.transform = 'translateY(-4px)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = `${PURPLE}22`;
              e.currentTarget.style.boxShadow = 'none';
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            <div style={{
              width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
              background: `linear-gradient(135deg, ${PURPLE}22, ${PURPLE}44)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 26, color: PURPLE,
            }}><FolderOpenOutlined /></div>
            <h3 style={{ margin: '0 0 8px', color: '#e0e6ed', fontSize: 18, fontWeight: 600 }}>打开项目</h3>
            <p style={{ margin: 0, color: '#5a6a8a', fontSize: 13 }}>继续未完成的创作</p>
          </div>

          {/* 从模板创建 */}
          <div className="home-card"
            style={{
              width: 240, padding: '36px 28px', borderRadius: 16,
              background: 'linear-gradient(135deg, rgba(16,185,129,0.08) 0%, rgba(16,185,129,0.02) 100%)',
              border: '1px solid rgba(16,185,129,0.15)', cursor: 'pointer',
              backdropFilter: 'blur(12px)',
              textAlign: 'center', transition: 'all 0.3s',
              opacity: 0.5, pointerEvents: 'none',
            }}
          >
            <div style={{
              width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
              background: 'linear-gradient(135deg, rgba(16,185,129,0.22), rgba(16,185,129,0.44))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 26, color: '#10b981',
            }}><AppstoreOutlined /></div>
            <h3 style={{ margin: '0 0 8px', color: '#e0e6ed', fontSize: 18, fontWeight: 600 }}>从模板创建</h3>
            <p style={{ margin: 0, color: '#5a6a8a', fontSize: 13 }}>即将上线</p>
          </div>
        </div>

        {/* ── 最近项目 ── */}
        {projects.length > 0 && (
          <div style={{ width: '100%', maxWidth: 800 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16,
              color: '#4a5a7a', fontSize: 13, letterSpacing: 2,
              fontFamily: "'Orbitron', monospace",
            }}>
              <span style={{ width: 20, height: 1, background: `linear-gradient(90deg, ${CYAN}66, transparent)` }} />
              最近项目
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.04))' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {projects.slice(0, 8).map((p) => (
                <div key={p.id} className="home-recent-item" onClick={() => handleOpen(p)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '14px 20px', borderRadius: 12,
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.04)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: 10,
                      background: `linear-gradient(135deg, ${CYAN}22, ${CYAN}11)`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: CYAN, fontSize: 16,
                    }}>
                      <VideoIcon />
                    </div>
                    <div>
                      <div style={{ color: '#c8d0dc', fontSize: 15, fontWeight: 500 }}>{p.name}</div>
                      <div style={{ color: '#4a5a7a', fontSize: 12, display: 'flex', gap: 12 }}>
                        <span>{p.episode_count ?? 0} 个视频</span>
                        <span>创建于 {fmtDate(p.created_at ?? '')}</span>
                      </div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                      onClick={(e) => handleRenameOpen(e, p)}
                      style={{
                        background: 'transparent', border: 'none', color: '#3a4a6a',
                        cursor: 'pointer', padding: 4, borderRadius: 6, fontSize: 14,
                        transition: 'all 0.2s',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.color = CYAN; e.currentTarget.style.background = `${CYAN}11`; }}
                      onMouseLeave={e => { e.currentTarget.style.color = '#3a4a6a'; e.currentTarget.style.background = 'transparent'; }}
                    ><EditOutlined /></button>
                    <button
                      onClick={(e) => handleDelete(e, p)}
                      style={{
                        background: 'transparent', border: 'none', color: '#3a4a6a',
                        cursor: 'pointer', padding: 4, borderRadius: 6, fontSize: 14,
                        transition: 'all 0.2s',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.color = '#ff4d4f'; e.currentTarget.style.background = 'rgba(255,77,79,0.1)'; }}
                      onMouseLeave={e => { e.currentTarget.style.color = '#3a4a6a'; e.currentTarget.style.background = 'transparent'; }}
                    ><DeleteOutlined /></button>
                    <RightOutlined style={{ color: '#3a4a6a', fontSize: 12 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* ─── 新建项目对话框 ─── */}
      <Modal
        title={null}
        open={creating}
        onCancel={() => setCreating(false)}
        footer={null}
        width={420}
        maskClosable={false}
        destroyOnClose
        styles={{
          content: {
            background: '#0d1128',
            borderRadius: 16,
            border: `1px solid ${CYAN}22`,
            boxShadow: `0 0 40px rgba(0,0,0,0.6)`,
            padding: 32,
          },
        }}
      >
        <h2 style={{ margin: '0 0 20px', color: '#e0e6ed', fontSize: 20, fontWeight: 600 }}>
          新建项目
        </h2>
        <Input
          placeholder="输入项目名称..."
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onPressEnter={handleCreate}
          size="large"
          variant="borderless"
          style={{
            background: 'rgba(255,255,255,0.04)', borderRadius: 10,
            color: '#e0e6ed', fontSize: 16, padding: '12px 16px',
            border: '1px solid rgba(255,255,255,0.08)',
          }}
          autoFocus
        />
        <div style={{ display: 'flex', gap: 12, marginTop: 20, justifyContent: 'flex-end' }}>
          <button
            onClick={() => setCreating(false)}
            style={{
              padding: '8px 24px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent', color: '#7a8aa0', cursor: 'pointer',
              fontSize: 14, transition: 'all 0.2s',
            }}
          >取消</button>
          <button
            onClick={handleCreate}
            disabled={!newName.trim()}
            style={{
              padding: '8px 24px', borderRadius: 8, border: 'none',
              background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
              color: '#fff', cursor: newName.trim() ? 'pointer' : 'not-allowed',
              fontSize: 14, fontWeight: 600,
              opacity: newName.trim() ? 1 : 0.5,
              transition: 'all 0.2s',
              boxShadow: newName.trim() ? `0 0 20px ${CYAN}44` : 'none',
            }}
          >创建并进入</button>
        </div>
      </Modal>

      {/* ─── 重命名项目对话框 ─── */}
      <Modal
        title={null}
        open={!!renamingProject}
        onCancel={() => { setRenamingProject(null); setRenameName(''); }}
        footer={null}
        width={420}
        style={{ background: 'transparent' }}
        modalRender={() => (
          <div style={{
            background: '#0d1128', borderRadius: 16, border: `1px solid ${CYAN}22`,
            padding: 32, boxShadow: `0 0 40px rgba(0,0,0,0.6)`,
          }}>
            <h2 style={{ margin: '0 0 20px', color: '#e0e6ed', fontSize: 20, fontWeight: 600 }}>
              重命名项目
            </h2>
            <Input
              placeholder="输入新名称..."
              value={renameName}
              onChange={e => setRenameName(e.target.value)}
              onPressEnter={handleRenameConfirm}
              size="large"
              variant="borderless"
              style={{
                background: 'rgba(255,255,255,0.04)', borderRadius: 10,
                color: '#e0e6ed', fontSize: 16, padding: '12px 16px',
                border: '1px solid rgba(255,255,255,0.08)',
              }}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 12, marginTop: 20, justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setRenamingProject(null); setRenameName(''); }}
                style={{
                  padding: '8px 24px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)',
                  background: 'transparent', color: '#7a8aa0', cursor: 'pointer',
                  fontSize: 14, transition: 'all 0.2s',
                }}
              >取消</button>
              <button
                onClick={handleRenameConfirm}
                disabled={!renameName.trim()}
                style={{
                  padding: '8px 24px', borderRadius: 8, border: 'none',
                  background: `linear-gradient(135deg, ${CYAN}, ${PURPLE})`,
                  color: '#fff', cursor: renameName.trim() ? 'pointer' : 'not-allowed',
                  fontSize: 14, fontWeight: 600,
                  opacity: renameName.trim() ? 1 : 0.5,
                  transition: 'all 0.2s',
                  boxShadow: renameName.trim() ? `0 0 20px ${CYAN}44` : 'none',
                }}
              >确认重命名</button>
            </div>
          </div>
        )}
      />
    </div>
  );
};

/* ─── 小图标 ─── */
const VideoIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="23 7 16 12 23 17 23 7" />
    <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
  </svg>
);

export default HomePage;
