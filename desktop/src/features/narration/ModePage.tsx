import { App as AntdApp, Button, Card, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { NarrationMode, Project } from '@dramaclip/protocol';
import { narrationApi, projectApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';

interface ModeCard {
  mode: NarrationMode;
  name: string;
  description: string;
  duration: string;
  group: 'AI 解说' | '原片组' | '字幕驱动' | '特殊';
  enabled: boolean;
}

const MODE_CARDS: ModeCard[] = [
  { mode: 'raw_clip', name: '纯原片剪辑', description: '高光场景智能编排', duration: '30-120s', group: '原片组', enabled: true },
  { mode: 'intro_narration', name: '片头解说', description: 'TTS 引子 + 正片高光', duration: '45-90s', group: 'AI 解说', enabled: true },
  { mode: 'cross_narration', name: '交叉解说', description: '旁白与原声交替', duration: '60-120s', group: 'AI 解说', enabled: true },
  { mode: 'full_narration', name: '全片解说', description: '全程 AI 配音', duration: '120-300s', group: 'AI 解说', enabled: false },
  { mode: 'dialogue_narration', name: '剧情解说', description: '对白重新编排叙事', duration: '45-120s', group: 'AI 解说', enabled: false },
  { mode: 'subtitle_flow', name: '字幕金句流', description: '动态字幕双通道', duration: '30-90s', group: '字幕驱动', enabled: false },
  { mode: 'ultra_short_hook', name: '超短悬念版', description: '信息流钩子', duration: '10-20s', group: '字幕驱动', enabled: true },
  { mode: 'dual_host_chat', name: '双人对谈', description: '双音色聊天体', duration: '60-180s', group: '特殊', enabled: false },
];

/** 模式配置页（docs/desktop/03 §7.4 W4 子集）：选择模式 → 生成编排。 */
export function ModePage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const analysisProgress = useUiStore((state) => state.analysisProgress);
  const [selected, setSelected] = useState<NarrationMode[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const toggle = (mode: NarrationMode) => {
    setSelected((prev) => (prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]));
  };

  const onGenerate = useCallback(async () => {
    setSubmitting(true);
    try {
      await narrationApi.generatePlans(projectId, selected);
      message.success('编排任务已提交');
      await navigate(`/projects/${projectId}/generate`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }, [message, navigate, projectId, selected]);

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <PageHeader projectId={projectId} onLoaded={setCurrentProjectId} />
      <Card size="small" style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {MODE_CARDS.map((card) => (
            <ModeTile
              key={card.mode}
              card={card}
              checked={selected.includes(card.mode)}
              onToggle={() => { toggle(card.mode); }}
            />
          ))}
        </div>
      </Card>
      <footer style={{ display: 'flex', alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: tokens.textTertiary }}>
          已选 {String(selected.length)} 个模式 · 生成后可导出成片
        </span>
        <Button
          type="primary"
          style={{ marginLeft: 'auto' }}
          disabled={selected.length === 0}
          loading={submitting}
          onClick={() => void onGenerate()}
        >
          生成编排方案
        </Button>
      </footer>
      {analysisProgress !== null && (
        <div style={{ marginTop: 12, fontSize: 12, color: tokens.textSecondary }}>
          最近任务：{analysisProgress.message}（{String(analysisProgress.percent)}%）
        </div>
      )}
    </div>
  );
}

function PageHeader({
  projectId,
  onLoaded,
}: {
  projectId: string;
  onLoaded: (id: string | null) => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  useEffect(() => {
    onLoaded(projectId === '' ? null : projectId);
    void projectApi.get(projectId).then((detail) => { setProject(detail.project); });
    return () => { onLoaded(null); };
  }, [projectId, onLoaded]);
  return (
    <header style={{ marginBottom: 16 }}>
      <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>
        {project?.name ?? '…'} · 选择剪辑模式
      </h1>
    </header>
  );
}

function ModeTile({ card, checked, onToggle }: { card: ModeCard; checked: boolean; onToggle: () => void }) {
  return (
    <Card
      size="small"
      hoverable={card.enabled}
      onClick={card.enabled ? onToggle : undefined}
      style={{
        borderColor: checked ? tokens.colorPrimary : tokens.border,
        background: checked ? 'rgba(77,159,255,0.08)' : undefined,
        opacity: card.enabled ? 1 : 0.45,
        cursor: card.enabled ? 'pointer' : 'not-allowed',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <strong style={{ color: tokens.textPrimary, fontSize: 14 }}>{card.name}</strong>
          {card.enabled ? (
            checked && <Tag color="blue">已选</Tag>
          ) : (
            <Tag>P1/P2</Tag>
          )}
        </div>
        <span style={{ fontSize: 12, color: tokens.textSecondary }}>{card.description}</span>
        <span style={{ fontSize: 12, color: tokens.textTertiary }}>{card.duration}</span>
      </div>
    </Card>
  );
}
