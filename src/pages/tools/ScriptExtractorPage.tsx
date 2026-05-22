/**
 * 页面：台词/文案提取小工具
 * 专门针对短剧二次剪辑与改写的 AI 台词提取及洗稿一键创作工具
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  CopyOutlined,
  DownloadOutlined,
  ThunderboltOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  VideoCameraOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { Progress, Radio, message, Tooltip } from 'antd';
import { toolsApi } from '../../services/ipc';
import type { TranscribeSegment, TranscribeResult } from '../../services/ipc';

/* ─── 霓虹主题色定义 ─── */
const PINK = '#ec4899';
const CYAN = '#00d4ff';
const PURPLE = '#7c3aed';

/* ─── CSS 样式注入 ─── */
const injectExtractorStyles = () => {
  const id = 'script-extractor-sci-fi-styles';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes extractorGlow {
      0%, 100% { border-color: ${PINK}22; box-shadow: 0 0 15px rgba(236,72,153,0.05); }
      50% { border-color: ${PINK}66; box-shadow: 0 0 25px rgba(236,72,153,0.2), inset 0 0 15px rgba(236,72,153,0.05); }
    }
    @keyframes textStreamGlow {
      0%, 100% { border-color: ${CYAN}33; }
      50% { border-color: ${CYAN}aa; box-shadow: 0 0 15px rgba(0,212,255,0.15); }
    }
    @keyframes pulseSoft {
      0%, 100% { opacity: 0.8; }
      50% { opacity: 0.4; }
    }
    .extractor-dropzone {
      border: 2px dashed ${PINK}33;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .extractor-dropzone.active {
      border-color: ${PINK};
      background: rgba(236, 72, 153, 0.08) !important;
      box-shadow: 0 0 30px rgba(236, 72, 153, 0.25), inset 0 0 20px rgba(236, 72, 153, 0.1);
      transform: scale(1.01);
    }
    .cyber-btn-pink {
      background: linear-gradient(135deg, ${PINK}dd 0%, ${PURPLE}dd 100%);
      border: 1px solid ${PINK}aa;
      color: #fff;
      font-weight: 600;
      letter-spacing: 2px;
      transition: all 0.25s;
      cursor: pointer;
      box-shadow: 0 4px 15px rgba(236, 72, 153, 0.2);
    }
    .cyber-btn-pink:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 6px 25px rgba(236, 72, 153, 0.45);
      border-color: ${PINK};
      background: linear-gradient(135deg, ${PINK} 0%, ${PURPLE} 100%);
    }
    .cyber-btn-pink:active:not(:disabled) {
      transform: translateY(0);
    }
    .style-card {
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.02);
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .style-card.selected {
      border-color: ${PINK}aa !important;
      background: rgba(236, 72, 153, 0.06) !important;
      box-shadow: 0 0 15px rgba(236, 72, 153, 0.15);
    }
    .style-card:hover:not(.selected) {
      border-color: rgba(255, 255, 255, 0.15);
      background: rgba(255, 255, 255, 0.04);
    }
    /* 美化原生滚动条 */
    .custom-scroll::-webkit-scrollbar {
      width: 6px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: rgba(255, 255, 255, 0.01);
      border-radius: 3px;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 3px;
    }
    .custom-scroll::-webkit-scrollbar-thumb:hover {
      background: rgba(0, 212, 255, 0.2);
    }
  `;
  document.head.appendChild(style);
};

/* ─── 辅助函数：时间秒数格式化 ─── */
function formatTimeSRT(seconds: number): string {
  const hr = Math.floor(seconds / 3600);
  const min = Math.floor((seconds % 3600) / 60);
  const sec = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(hr).padStart(2, '0')}:${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function formatTimeLabel(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${ms}`;
}

const ScriptExtractorPage: React.FC = () => {
  const navigate = useNavigate();
  
  // 核心交互状态
  const [videoPath, setVideoPath] = useState('');
  const [videoName, setVideoName] = useState('');
  const [engineMode, setEngineMode] = useState<'fast' | 'precise'>('fast');
  const [isDragActive, setIsDragActive] = useState(false);
  
  // 运行状态与任务进度
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle');
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  
  // 识别与改写结果
  const [transcribeResult, setTranscribeResult] = useState<TranscribeResult | null>(null);
  const [selectedStyle, setSelectedStyle] = useState<'rewriter' | 'shocking' | 'suspense' | 'emotional'>('rewriter');
  const [rewriting, setRewriting] = useState(false);
  const [rewrittenText, setRewrittenText] = useState('');

  // 轮询定时器引用
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    injectExtractorStyles();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // 1. 选择本地视频文件
  const handleSelectFile = async () => {
    try {
      if (!window.electronAPI?.dialog?.openFile) {
        message.warning('开发模式：无法调用原生文件对话框');
        // Dev Mock
        setVideoPath('D:\\DramaClip\\demo\\short_drama_episode1.mp4');
        setVideoName('short_drama_episode1.mp4');
        return;
      }
      
      const res = await window.electronAPI.dialog.openFile({
        title: '选择短剧视频文件',
        filters: [
          { name: '视频文件', extensions: ['mp4', 'mkv', 'avi', 'mov', 'flv', 'webm'] }
        ],
        properties: ['openFile']
      });

      if (res.success && res.data && res.data.length > 0) {
        const filePath = res.data[0];
        setVideoPath(filePath);
        // 提炼出文件名
        const sep = filePath.includes('\\') ? '\\' : '/';
        const name = filePath.split(sep).pop() || '';
        setVideoName(name);
        setTranscribeResult(null);
        setRewrittenText('');
        setStatus('idle');
        setProgress(0);
      }
    } catch (err: any) {
      message.error(`打开文件失败: ${err.message}`);
    }
  };

  // 2. 拖拽文件支持
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragActive(true);
    } else if (e.type === 'dragleave') {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      const ext = file.name.split('.').pop()?.toLowerCase();
      const videoExtensions = ['mp4', 'mkv', 'avi', 'mov', 'flv', 'webm'];
      
      if (ext && videoExtensions.includes(ext)) {
        // 在 Electron 环境下，file.path 包含了完整绝对路径
        const path = (file as any).path || file.name;
        setVideoPath(path);
        setVideoName(file.name);
        setTranscribeResult(null);
        setRewrittenText('');
        setStatus('idle');
        setProgress(0);
        message.success(`成功载入视频：${file.name}`);
      } else {
        message.error('不支持的文件格式，请拖放视频文件（MP4、MKV、AVI等）');
      }
    }
  };

  // 3. 开始转写任务
  const handleStartTranscribe = async () => {
    if (!videoPath) return;
    setStatus('running');
    setProgress(5);
    setStatusMsg('正在初始化任务...');
    setErrorMessage('');
    setTranscribeResult(null);
    setRewrittenText('');

    try {
      const res = await toolsApi.transcribe(videoPath, engineMode);
      if (res && res.task_id) {
        setTaskId(res.task_id);
        // 开启轮询
        startPolling(res.task_id);
      } else {
        throw new Error('未返回有效的任务ID');
      }
    } catch (err: any) {
      console.error(err);
      setStatus('failed');
      setErrorMessage(err.message || '转写服务请求异常');
      message.error('台词提取提取失败');
    }
  };

  // 4. 轮询任务进度
  const startPolling = (tid: string) => {
    if (timerRef.current) clearInterval(timerRef.current);
    
    timerRef.current = setInterval(async () => {
      try {
        const task = await toolsApi.getProgress(tid);
        if (!task) return;
        
        setProgress(task.progress);
        setStatusMsg(task.message || '识别中...');

        if (task.status === 'completed') {
          if (timerRef.current) clearInterval(timerRef.current);
          setStatus('completed');
          setTranscribeResult(task.results || null);
          message.success('台词提取完成！');
        } else if (task.status === 'failed') {
          if (timerRef.current) clearInterval(timerRef.current);
          setStatus('failed');
          setErrorMessage(task.error || '语音识别失败');
          message.error('台词提取失败，请重试');
        }
      } catch (err) {
        // 忽略单次网络通信抖动
        console.warn('Polling error:', err);
      }
    }, 1000);
  };

  // 5. 复制 SRT
  const handleCopySRT = () => {
    if (!transcribeResult?.segments) return;
    try {
      const srtContent = convertToSRTString(transcribeResult.segments);
      navigator.clipboard.writeText(srtContent);
      message.success('SRT 格式字幕已复制到剪贴板！');
    } catch {
      message.error('复制失败');
    }
  };

  // 6. 导出 SRT 文件
  const handleExportSRT = () => {
    if (!transcribeResult?.segments) return;
    const srtContent = convertToSRTString(transcribeResult.segments);
    const fileName = `${videoName.substring(0, videoName.lastIndexOf('.')) || 'subtitles'}.srt`;
    downloadTextFile(srtContent, fileName);
    message.success('SRT 字幕导出成功');
  };

  // 7. 复制完整文案
  const handleCopyProse = () => {
    if (!transcribeResult?.prose) return;
    try {
      navigator.clipboard.writeText(transcribeResult.prose);
      message.success('完整文案已复制到剪贴板！');
    } catch {
      message.error('复制失败');
    }
  };

  // 8. 导出 TXT 文案
  const handleExportProse = () => {
    if (!transcribeResult?.prose) return;
    const fileName = `${videoName.substring(0, videoName.lastIndexOf('.')) || 'script'}_文案.txt`;
    downloadTextFile(transcribeResult.prose, fileName);
    message.success('文案 TXT 导出成功');
  };

  // 9. 一键 AI 改写洗稿
  const handleAIRewrite = async () => {
    if (!transcribeResult?.prose) return;
    setRewriting(true);
    setRewrittenText('');

    try {
      const res = await toolsApi.rewrite(transcribeResult.prose, selectedStyle);
      if (res && res.rewritten) {
        setRewrittenText(res.rewritten);
        message.success('AI 二创改写成功！');
      } else {
        throw new Error('AI 返回数据异常');
      }
    } catch (err: any) {
      message.error(`改写失败: ${err.message || err}`);
    } finally {
      setRewriting(false);
    }
  };

  // 10. 复制改写后的文本
  const handleCopyRewritten = () => {
    if (!rewrittenText) return;
    try {
      navigator.clipboard.writeText(rewrittenText);
      message.success('改写文案已复制！');
    } catch {
      message.error('复制失败');
    }
  };

  // 辅助：生成标准 SRT 格式
  const convertToSRTString = (segments: TranscribeSegment[]): string => {
    return segments
      .map((seg, idx) => {
        const start = formatTimeSRT(seg.start);
        const end = formatTimeSRT(seg.end);
        return `${idx + 1}\n${start} --> ${end}\n${seg.text}\n`;
      })
      .join('\n');
  };

  // 辅助：浏览器无阻下载文本文件
  const downloadTextFile = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div
      style={{
        padding: '24px 40px',
        color: '#e0e6ed',
        minHeight: 'calc(100vh - 36px)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* ─── 顶部返回与发光标题 ─── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button
            onClick={() => navigate('/')}
            style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: 8,
              width: 38,
              height: 38,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#a0aed0',
              cursor: 'pointer',
              transition: 'all 0.25s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = `${PINK}44`;
              e.currentTarget.style.color = PINK;
              e.currentTarget.style.boxShadow = `0 0 10px ${PINK}22`;
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
              e.currentTarget.style.color = '#a0aed0';
              e.currentTarget.style.boxShadow = 'none';
            }}
          >
            <ArrowLeftOutlined style={{ fontSize: 16 }} />
          </button>
          <div>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 700,
                margin: 0,
                letterSpacing: 2,
                background: `linear-gradient(135deg, #fff 0%, ${PINK} 100%)`,
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                fontFamily: "'Orbitron', sans-serif",
                textShadow: `0 0 20px ${PINK}22`,
              }}
            >
              台词/文案提取小工具
            </h1>
            <span style={{ fontSize: 12, color: '#5a6a8a', marginTop: 2, display: 'inline-block' }}>
              高灵敏语音识别，支持秒级音频转写字幕、段落重新排版和 AI 一键爆款二创洗稿。
            </span>
          </div>
        </div>
      </div>

      {/* ─── 核心面板区域 ─── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 24 }}>
        {/* 第一阶段：未提取 / idle 状态：拖放上传视频 */}
        {status === 'idle' && (
          <div
            className={`extractor-dropzone ${isDragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            style={{
              padding: '48px 32px',
              borderRadius: 16,
              background: 'rgba(255, 255, 255, 0.01)',
              backdropFilter: 'blur(12px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 280,
              cursor: 'pointer',
            }}
            onClick={handleSelectFile}
          >
            <div
              style={{
                width: 68,
                height: 68,
                borderRadius: 20,
                background: `linear-gradient(135deg, ${PINK}11, ${PINK}33)`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: PINK,
                fontSize: 28,
                marginBottom: 20,
                boxShadow: `0 0 20px ${PINK}11`,
              }}
            >
              <VideoCameraOutlined />
            </div>
            
            {videoPath ? (
              <div style={{ textAlign: 'center', maxWidth: 600 }}>
                <h3 style={{ color: '#e0e6ed', fontSize: 16, marginBottom: 8, fontWeight: 600 }}>已选择视频文件</h3>
                <p style={{ color: CYAN, fontFamily: 'monospace', wordBreak: 'break-all', fontSize: 13, background: 'rgba(0,212,255,0.04)', padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(0,212,255,0.1)' }}>
                  {videoPath}
                </p>
                <p style={{ color: '#5a6a8a', fontSize: 12, marginTop: 12 }}>
                  点击此区域可更换视频文件，或直接拖放新视频覆盖
                </p>
              </div>
            ) : (
              <div style={{ textAlign: 'center' }}>
                <h3 style={{ color: '#c8d0dc', fontSize: 16, marginBottom: 8, fontWeight: 600 }}>
                  点击或拖拽视频到此处
                </h3>
                <p style={{ color: '#5a6a8a', fontSize: 13, margin: 0 }}>
                  支持常见格式：MP4, MKV, AVI, MOV, FLV 等格式
                </p>
              </div>
            )}
          </div>
        )}

        {/* 核心配置选择（当已载入视频且未在进行中时显示） */}
        {videoPath && status !== 'running' && status !== 'completed' && (
          <div
            style={{
              padding: '24px 32px',
              borderRadius: 16,
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.04)',
              backdropFilter: 'blur(12px)',
            }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#c8d0dc', marginBottom: 8 }}>选择识别引擎</div>
                <Radio.Group
                  value={engineMode}
                  onChange={e => setEngineMode(e.target.value)}
                  style={{ display: 'flex', gap: 16 }}
                >
                  <Radio value="fast" className="cyber-radio">
                    <Tooltip title="基于 SenseVoice 模型，速度极快（通常1分钟视频仅需数秒），支持自动标点与高灵敏降噪分段，非常推荐二创文案改写使用。">
                      <span style={{ color: '#e0e6ed', cursor: 'pointer' }}>
                        ⚡ 极速引擎 <span style={{ color: CYAN, fontSize: 11, background: `${CYAN}11`, padding: '2px 6px', borderRadius: 4, marginLeft: 4 }}>SenseVoice</span>
                      </span>
                    </Tooltip>
                  </Radio>
                  <Radio value="precise" className="cyber-radio">
                    <Tooltip title="基于 OpenAI Whisper-large-v3，精度极高，支持多语种自动切换及带音效过滤。模型较大识别较慢。">
                      <span style={{ color: '#e0e6ed', cursor: 'pointer' }}>
                        🎯 精准引擎 <span style={{ color: PURPLE, fontSize: 11, background: `${PURPLE}22`, padding: '2px 6px', borderRadius: 4, marginLeft: 4 }}>Whisper V3</span>
                      </span>
                    </Tooltip>
                  </Radio>
                </Radio.Group>
              </div>

              <button
                className="cyber-btn-pink"
                onClick={handleStartTranscribe}
                style={{
                  padding: '12px 36px',
                  borderRadius: 10,
                  fontSize: 15,
                  minWidth: 160,
                }}
              >
                开始提取台词
              </button>
            </div>
          </div>
        )}

        {/* 第二阶段：running / 转写识别进度展示 */}
        {status === 'running' && (
          <div
            style={{
              padding: '60px 40px',
              borderRadius: 16,
              background: 'rgba(255, 255, 255, 0.02)',
              border: `1px solid ${PINK}33`,
              animation: 'extractorGlow 4s ease-in-out infinite',
              backdropFilter: 'blur(12px)',
              textAlign: 'center',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 280,
            }}
          >
            <div style={{ width: '100%', maxWidth: 500 }}>
              <div style={{ display: 'flex', justifyItems: 'center', justifyContent: 'center', marginBottom: 20 }}>
                <LoadingOutlined style={{ fontSize: 44, color: PINK }} />
              </div>
              <h3 style={{ color: '#e0e6ed', fontSize: 18, marginBottom: 8, fontWeight: 600 }}>
                正在提取台词字幕...
              </h3>
              <p style={{ color: '#8892a4', fontSize: 13, marginBottom: 24 }}>
                后台工作线程正通过 FFmpeg 智能截取无损音频流并派发给 ASR 引擎识别。
              </p>
              
              <Progress
                percent={progress}
                strokeColor={{
                  '0%': CYAN,
                  '50%': PURPLE,
                  '100%': PINK,
                }}
                trailColor="rgba(255, 255, 255, 0.05)"
                status="active"
                style={{ marginBottom: 12 }}
              />
              
              <div style={{ color: CYAN, fontSize: 13, fontFamily: 'monospace', letterSpacing: 1, animation: 'pulseSoft 2s infinite' }}>
                {statusMsg}
              </div>
            </div>
          </div>
        )}

        {/* 失败状态展示 */}
        {status === 'failed' && (
          <div
            style={{
              padding: '48px 32px',
              borderRadius: 16,
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 77, 79, 0.2)',
              backdropFilter: 'blur(12px)',
              textAlign: 'center',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 280,
            }}
          >
            <ExclamationCircleOutlined style={{ fontSize: 48, color: '#ff4d4f', marginBottom: 16 }} />
            <h3 style={{ color: '#ff4d4f', fontSize: 18, marginBottom: 8, fontWeight: 600 }}>识别遇到异常</h3>
            <p style={{ color: '#a0aed0', fontSize: 13, maxWidth: 500, wordBreak: 'break-all', fontFamily: 'monospace', background: 'rgba(255,77,79,0.05)', padding: '12px 20px', borderRadius: 8, border: '1px solid rgba(255,77,79,0.1)' }}>
              {errorMessage}
            </p>
            <div style={{ display: 'flex', gap: 16, marginTop: 24 }}>
              <button
                className="cyber-btn-pink"
                onClick={handleStartTranscribe}
                style={{ padding: '8px 24px', borderRadius: 8, fontSize: 14 }}
              >
                重新运行提取
              </button>
              <button
                onClick={() => { setStatus('idle'); setVideoPath(''); setVideoName(''); }}
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  padding: '8px 24px',
                  borderRadius: 8,
                  color: '#7a8aa0',
                  cursor: 'pointer',
                  fontSize: 14,
                  transition: 'all 0.2s',
                }}
              >
                更换视频文件
              </button>
            </div>
          </div>
        )}

        {/* 第三阶段：转写识别成功，呈现双栏结果 & AI 改写 */}
        {status === 'completed' && transcribeResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {/* 顶层视频名称 & 更换视频 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 24px',
                borderRadius: 12,
                background: 'rgba(255, 255, 255, 0.01)',
                border: '1px solid rgba(255, 255, 255, 0.03)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 16 }} />
                <span style={{ color: '#5a6a8a', fontSize: 13 }}>当前解析视频：</span>
                <span style={{ color: CYAN, fontWeight: 600, fontSize: 14 }}>{videoName}</span>
              </div>
              <button
                onClick={() => { setStatus('idle'); setVideoPath(''); setVideoName(''); setTranscribeResult(null); setRewrittenText(''); }}
                style={{
                  background: 'rgba(0, 212, 255, 0.05)',
                  border: `1px solid ${CYAN}33`,
                  borderRadius: 8,
                  padding: '4px 12px',
                  color: CYAN,
                  fontSize: 12,
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,212,255,0.12)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'rgba(0,212,255,0.05)'; }}
              >
                更换视频
              </button>
            </div>

            {/* 双栏面板 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, minHeight: 380 }}>
              {/* 左侧：字幕段落显示 (SRT) */}
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.01)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                  borderRadius: 16,
                  padding: 20,
                  display: 'flex',
                  flexDirection: 'column',
                  backdropFilter: 'blur(12px)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 12, height: 12, borderRadius: '50%', background: PINK, boxShadow: `0 0 8px ${PINK}` }} />
                    <h3 style={{ color: '#e0e6ed', fontSize: 15, margin: 0, fontWeight: 600 }}>字幕格式 (SRT Mode)</h3>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={handleCopySRT}
                      style={{
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 6,
                        padding: '4px 10px',
                        color: '#a0aed0',
                        fontSize: 12,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <CopyOutlined /> 复制 SRT
                    </button>
                    <button
                      onClick={handleExportSRT}
                      style={{
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 6,
                        padding: '4px 10px',
                        color: '#a0aed0',
                        fontSize: 12,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <DownloadOutlined /> 导出 SRT
                    </button>
                  </div>
                </div>

                {/* 字幕内容区域 */}
                <div
                  className="custom-scroll"
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    background: 'rgba(0, 0, 0, 0.2)',
                    border: '1px solid rgba(255, 255, 255, 0.03)',
                    borderRadius: 8,
                    padding: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                    maxHeight: 400,
                  }}
                >
                  {transcribeResult.segments.length > 0 ? (
                    transcribeResult.segments.map((seg, idx) => (
                      <div
                        key={seg.id || idx}
                        style={{
                          padding: '8px 12px',
                          background: 'rgba(255, 255, 255, 0.01)',
                          borderLeft: `2px solid ${PINK}33`,
                          borderRadius: '0 6px 6px 0',
                          fontSize: 13,
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', color: '#5a6a8a', fontSize: 11, marginBottom: 4, fontFamily: 'monospace' }}>
                          <span>#{idx + 1}</span>
                          <span>{formatTimeLabel(seg.start)} → {formatTimeLabel(seg.end)}</span>
                        </div>
                        <div style={{ color: '#c8d0dc', lineHeight: 1.4 }}>{seg.text}</div>
                      </div>
                    ))
                  ) : (
                    <div style={{ textAlign: 'center', color: '#5a6a8a', padding: 40 }}>未提取到字幕段落</div>
                  )}
                </div>
              </div>

              {/* 右侧：完整段落聚合文案 (Prose) */}
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.01)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                  borderRadius: 16,
                  padding: 20,
                  display: 'flex',
                  flexDirection: 'column',
                  backdropFilter: 'blur(12px)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 12, height: 12, borderRadius: '50%', background: CYAN, boxShadow: `0 0 8px ${CYAN}` }} />
                    <h3 style={{ color: '#e0e6ed', fontSize: 15, margin: 0, fontWeight: 600 }}>段落聚合文案 (Prose Mode)</h3>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={handleCopyProse}
                      style={{
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 6,
                        padding: '4px 10px',
                        color: '#a0aed0',
                        fontSize: 12,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <CopyOutlined /> 复制文案
                    </button>
                    <button
                      onClick={handleExportProse}
                      style={{
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 6,
                        padding: '4px 10px',
                        color: '#a0aed0',
                        fontSize: 12,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <DownloadOutlined /> 导出 TXT
                    </button>
                  </div>
                </div>

                {/* 聚合大段文案 */}
                <div
                  className="custom-scroll"
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    background: 'rgba(0, 0, 0, 0.2)',
                    border: '1px solid rgba(255, 255, 255, 0.03)',
                    borderRadius: 8,
                    padding: 16,
                    fontSize: 14,
                    color: '#c8d0dc',
                    lineHeight: 1.6,
                    whiteSpace: 'pre-wrap',
                    textAlign: 'justify',
                    maxHeight: 400,
                  }}
                >
                  {transcribeResult.prose || '未提取到文案'}
                </div>
              </div>
            </div>

            {/* 下部：AI 二创爆款改写面板 */}
            <div
              style={{
                padding: '24px 32px',
                borderRadius: 16,
                background: 'linear-gradient(135deg, rgba(236,72,153,0.03) 0%, rgba(124,58,237,0.03) 100%)',
                border: '1px solid rgba(236, 72, 153, 0.1)',
                backdropFilter: 'blur(12px)',
                marginTop: 8,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
                <ThunderboltOutlined style={{ color: PINK, fontSize: 18, filter: `drop-shadow(0 0 6px ${PINK})` }} />
                <h3 style={{ color: '#e0e6ed', fontSize: 16, margin: 0, fontWeight: 600 }}>AI 爆款二创洗稿改写</h3>
              </div>

              {/* 风格选项 */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 16,
                  marginBottom: 24,
                }}
              >
                {/* 冲突爆发 */}
                <div
                  className={`style-card ${selectedStyle === 'shocking' ? 'selected' : ''}`}
                  onClick={() => setSelectedStyle('shocking')}
                  style={{ padding: '14px 18px', borderRadius: 10, cursor: 'pointer' }}
                >
                  <div style={{ color: PINK, fontWeight: 600, fontSize: 14, marginBottom: 4 }}>⚡ 冲突爆发</div>
                  <div style={{ color: '#5a6a8a', fontSize: 11, lineHeight: 1.3 }}>抓黄金前3秒，加强主干冲突，解说话术凌厉抓眼球。</div>
                </div>

                {/* 悬疑拉满 */}
                <div
                  className={`style-card ${selectedStyle === 'suspense' ? 'selected' : ''}`}
                  onClick={() => setSelectedStyle('suspense')}
                  style={{ padding: '14px 18px', borderRadius: 10, cursor: 'pointer' }}
                >
                  <div style={{ color: CYAN, fontWeight: 600, fontSize: 14, marginBottom: 4 }}>🕵️ 悬疑拉满</div>
                  <div style={{ color: '#5a6a8a', fontSize: 11, lineHeight: 1.3 }}>层层勾引好奇心，增加情节反转，结尾具有高能戏剧性。</div>
                </div>

                {/* 情感共鸣 */}
                <div
                  className={`style-card ${selectedStyle === 'emotional' ? 'selected' : ''}`}
                  onClick={() => setSelectedStyle('emotional')}
                  style={{ padding: '14px 18px', borderRadius: 10, cursor: 'pointer' }}
                >
                  <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: 14, marginBottom: 4 }}>❤️ 情感共鸣</div>
                  <div style={{ color: '#5a6a8a', fontSize: 11, lineHeight: 1.3 }}>深度代入情绪，文辞优美真挚，触动同理心，极具文艺范。</div>
                </div>

                {/* 智能洗稿 */}
                <div
                  className={`style-card ${selectedStyle === 'rewriter' ? 'selected' : ''}`}
                  onClick={() => setSelectedStyle('rewriter')}
                  style={{ padding: '14px 18px', borderRadius: 10, cursor: 'pointer' }}
                >
                  <div style={{ color: '#34d399', fontWeight: 600, fontSize: 14, marginBottom: 4 }}>✍️ 智能洗稿</div>
                  <div style={{ color: '#5a6a8a', fontSize: 11, lineHeight: 1.3 }}>核心情节不变，更换流行网络话术，规避原创版权检测。</div>
                </div>
              </div>

              {/* 开始改写操作栏 */}
              <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                <button
                  className="cyber-btn-pink"
                  disabled={rewriting}
                  onClick={handleAIRewrite}
                  style={{
                    padding: '10px 28px',
                    borderRadius: 8,
                    fontSize: 14,
                    minWidth: 160,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 6,
                  }}
                >
                  {rewriting ? (
                    <>
                      <SyncOutlined spin /> 改写中...
                    </>
                  ) : (
                    <>
                      <ThunderboltOutlined /> 一键爆款二创
                    </>
                  )}
                </button>
                <span style={{ fontSize: 12, color: '#5a6a8a' }}>
                  一键改写将使用预设提示词发送给本地/云端 LLM，耗时约 5-15 秒。
                </span>
              </div>

              {/* AI 改写输出区域 */}
              {(rewriting || rewrittenText) && (
                <div
                  style={{
                    marginTop: 24,
                    padding: 20,
                    background: 'rgba(0,0,0,0.3)',
                    borderRadius: 12,
                    border: `1px solid ${PINK}33`,
                    animation: rewrittenText ? 'none' : 'textStreamGlow 3s infinite',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{ color: PINK, fontWeight: 600, fontSize: 13 }}>二创文案生成结果</div>
                    {rewrittenText && (
                      <button
                        onClick={handleCopyRewritten}
                        style={{
                          background: 'rgba(236, 72, 153, 0.08)',
                          border: `1px solid ${PINK}33`,
                          borderRadius: 6,
                          padding: '4px 10px',
                          color: PINK,
                          fontSize: 11,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 4,
                        }}
                      >
                        <CopyOutlined /> 复制改写文案
                      </button>
                    )}
                  </div>
                  
                  {rewriting && !rewrittenText ? (
                    <div style={{ color: '#5a6a8a', display: 'flex', alignItems: 'center', gap: 8, padding: '16px 0' }}>
                      <LoadingOutlined /> AI 编剧正在激情改写中，请稍候...
                    </div>
                  ) : (
                    <div
                      className="custom-scroll"
                      style={{
                        color: '#d0d8e6',
                        fontSize: 14,
                        lineHeight: 1.6,
                        whiteSpace: 'pre-wrap',
                        textAlign: 'justify',
                        maxHeight: 250,
                        overflowY: 'auto',
                      }}
                    >
                      {rewrittenText}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ScriptExtractorPage;
