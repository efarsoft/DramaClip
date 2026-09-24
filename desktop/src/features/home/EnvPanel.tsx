/** 右栏：环境就绪度 + 快速上手（工作台）。 */
import type { ReactElement, ReactNode } from 'react';
import { Card } from 'antd';
import { useNavigate } from 'react-router-dom';
import { BookOutlined, EditOutlined, RightOutlined } from '@ant-design/icons';
import type { ModelInfo } from '@dramaclip/protocol';
import { layout, tokens } from '../../styles/theme';

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
      ? { name: 'LLM 文案引擎', ok: false, status: '未配置', action: { label: '去配置', path: '/engines/llm' } }
      : { name: 'LLM 文案引擎', ok: true, status: '已配置' },
    asr === undefined
      ? { name: 'ASR 语音识别', ok: null, status: '…' }
      : asr.status === 'installed'
        ? { name: 'ASR 语音识别', ok: true, status: `已安装 · ${asr.name}` }
        : { name: 'ASR 语音识别', ok: false, status: '未安装', action: { label: '去下载', path: '/engines/asr' } },
    ttsEngine === 'kokoro'
      ? kokoro?.status === 'installed'
        ? { name: 'TTS 配音', ok: true, status: 'Kokoro 本地 · 已就绪' }
        : { name: 'TTS 配音', ok: false, status: 'Kokoro 缺模型', action: { label: '去下载', path: '/engines/tts' } }
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
        gap: tokens.spaceSm,
        padding: `${String(layout.envPanel.itemPaddingBlock)}px 0`,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
      }}
    >
      <span style={{ width: 110, flexShrink: 0, color: tokens.textSecondary }}>{row.name}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, color: tokens.textTertiary }}>
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
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: layout.envPanel.actionGap,
            padding: 0,
          }}
        >
          {row.action.label}
          <RightOutlined style={{ fontSize: tokens.glyph.icon }} />
        </button>
      )}
    </div>
  );
}

const TIPS = [
  { icon: <EditOutlined />, text: '转写有误？分析页点对白流直接改，改完重跑语义' },
  { icon: <BookOutlined />, text: '九种模式支持一键全部生成，横向对比效果' },
] as const;

export function TipsPanel(): ReactElement {
  return (
    <RightPanel title="快速上手">
      {TIPS.map((tip) => (
        <div key={tip.text} style={{ display: 'flex', gap: tokens.spaceSm, padding: `${String(layout.envPanel.tipPaddingBlock)}px 0`, alignItems: 'flex-start' }}>
          <span style={{ color: tokens.colorPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, marginTop: layout.envPanel.tipIconMarginTop }}>{tip.icon}</span>
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>{tip.text}</span>
        </div>
      ))}
    </RightPanel>
  );
}

function RightPanel({ title, children }: { title: string; children: ReactNode }): ReactElement {
  return (
    <Card
      size="small"
      styles={{
        body: {
          padding: `${String(layout.envPanel.bodyPaddingTop)}px ${String(layout.envPanel.bodyPaddingInline)}px ${String(layout.envPanel.bodyPaddingBottom)}px`,
        },
      }}
    >
      <div
        style={{
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          fontWeight: 600,
          color: tokens.textPrimary,
          padding: `${String(layout.envPanel.titlePaddingTop)}px 0 ${String(layout.envPanel.titlePaddingBottom)}px`,
        }}
      >
        {title}
      </div>
      {children}
    </Card>
  );
}
