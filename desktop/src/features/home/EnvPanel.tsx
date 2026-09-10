/** 右栏：环境就绪度 + 工具箱 + 快速上手（工作台）。 */
import type { ReactElement, ReactNode } from 'react';
import { Card } from 'antd';
import { useNavigate } from 'react-router-dom';
import {
  BookOutlined,
  CloudServerOutlined,
  EditOutlined,
  FolderOutlined,
  RightOutlined,
  RocketOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

interface EnvRow {
  readonly name: string;
  readonly ok: boolean | null;
  readonly status: string;
  readonly action?: { label: string; path: string };
}

export function EnvPanel({
  models,
  llmBaseUrl,
  ttsEngine,
}: {
  models: ModelInfo[] | null;
  llmBaseUrl: string;
  ttsEngine: string;
}): ReactElement {
  const navigate = useNavigate();
  const asr = (models ?? []).find((m) => m.required);
  const kokoro = (models ?? []).find((m) => m.model_id.includes('kokoro'));
  const rows: EnvRow[] = [
    llmBaseUrl === ''
      ? { name: 'LLM 文案引擎', ok: false, status: '未配置', action: { label: '去配置', path: '/settings' } }
      : { name: 'LLM 文案引擎', ok: true, status: '已配置' },
    asr === undefined
      ? { name: 'ASR 语音识别', ok: null, status: '…' }
      : asr.status === 'installed'
        ? { name: 'ASR 语音识别', ok: true, status: `已安装 · ${asr.name}` }
        : { name: 'ASR 语音识别', ok: false, status: '未安装', action: { label: '去下载', path: '/models/tts' } },
    ttsEngine === 'kokoro'
      ? kokoro?.status === 'installed'
        ? { name: 'TTS 配音', ok: true, status: 'Kokoro 本地 · 已就绪' }
        : { name: 'TTS 配音', ok: false, status: 'Kokoro 缺模型', action: { label: '去下载', path: '/models/tts' } }
      : { name: 'TTS 配音', ok: true, status: 'Edge 云端 · 已就绪' },
    { name: 'FFmpeg 编码', ok: true, status: '内置 · 就绪' },
  ];
  return (
    <RightPanel title="环境就绪度">
      {rows.map((row) => (
        <EnvItem key={row.name} row={row} onAction={(path) => void navigate(path)} />
      ))}
    </RightPanel>
  );
}

function EnvItem({ row, onAction }: { row: EnvRow; onAction: (path: string) => void }) {
  const dot = row.ok === null ? tokens.textTertiary : row.ok ? tokens.colorSuccess : tokens.colorWarning;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '9px 0',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        fontSize: tokens.fontCaption,
      }}
    >
      <span style={{ width: 110, flexShrink: 0, color: tokens.textSecondary }}>{row.name}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: tokens.textTertiary }}>
        <span style={{ width: 6, height: 6, borderRadius: tokens.radiusDot, background: dot }} />
        {row.status}
      </span>
      {row.action !== undefined && (
        <button
          type="button"
          onClick={() => {
            onAction(row.action?.path ?? '');
          }}
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: 'none',
            color: tokens.colorPrimary,
            fontSize: tokens.fontCaption,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            padding: 0,
          }}
        >
          {row.action.label}
          <RightOutlined style={{ fontSize: tokens.fontIcon }} />
        </button>
      )}
    </div>
  );
}

const TOOLS = [
  { key: 'models', icon: <CloudServerOutlined />, tint: tokens.colorPrimary, title: '模型管理', desc: '下载或导入语音/转写模型' },
  { key: 'settings', icon: <SettingOutlined />, tint: tokens.colorWarning, title: '系统设置', desc: 'LLM 端点、TTS 音色与出片参数' },
  { key: 'projects', icon: <FolderOutlined />, tint: tokens.colorAccent, title: '项目管理', desc: '全部项目、剧集与出片记录' },
] as const;

export function ToolboxPanel(): ReactElement {
  const navigate = useNavigate();
  return (
    <RightPanel title="工具箱">
      {TOOLS.map((tool) => (
        <div
          key={tool.key}
          onClick={() => {
            void navigate(`/${tool.key}`);
          }}
          style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '9px 0', cursor: 'pointer' }}
          onMouseEnter={(event) => {
            event.currentTarget.style.opacity = '0.85';
          }}
          onMouseLeave={(event) => {
            event.currentTarget.style.opacity = '1';
          }}
        >
          <span
            style={{
              width: 32,
              height: 32,
              borderRadius: tokens.radiusControl,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: tokens.fontTitle,
              color: tool.tint,
              background: `${tool.tint}1A`,
            }}
          >
            {tool.icon}
          </span>
          <span style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>{tool.title}</span>
            <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{tool.desc}</span>
          </span>
          <RightOutlined style={{ marginLeft: 'auto', fontSize: tokens.fontIcon, color: tokens.textTertiary }} />
        </div>
      ))}
    </RightPanel>
  );
}

const TIPS = [
  { icon: <RocketOutlined />, text: '导入短剧后自动预筛，推荐集才做全量分析' },
  { icon: <EditOutlined />, text: '转写有误？分析页点对白流直接改，改完重跑语义' },
  { icon: <BookOutlined />, text: '九种模式支持一键全部生成，横向对比效果' },
] as const;

export function TipsPanel(): ReactElement {
  return (
    <RightPanel title="快速上手">
      {TIPS.map((tip) => (
        <div key={tip.text} style={{ display: 'flex', gap: 10, padding: '7px 0', alignItems: 'flex-start' }}>
          <span style={{ color: tokens.colorPrimary, fontSize: tokens.fontBodyLg, marginTop: 1 }}>{tip.icon}</span>
          <span style={{ fontSize: tokens.fontCaption, lineHeight: '19px', color: tokens.textTertiary }}>{tip.text}</span>
        </div>
      ))}
    </RightPanel>
  );
}

function RightPanel({ title, children }: { title: string; children: ReactNode }): ReactElement {
  return (
    <Card size="small" styles={{ body: { padding: '6px 16px 10px' } }}>
      <div
        style={{
          fontSize: tokens.fontBody,
          fontWeight: 600,
          color: tokens.textPrimary,
          padding: '10px 0 4px',
        }}
      >
        {title}
      </div>
      {children}
    </Card>
  );
}
