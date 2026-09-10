/** 开始创作卡片区（工作台主列）：全部为真实动作入口。 */
import { useState, type ReactElement, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from 'antd';
import { FolderAddOutlined, PlayCircleOutlined, SettingOutlined } from '@ant-design/icons';
import { pickFolder, projectApi } from '../../services/client';
import { tokens } from '../../styles/theme';

interface CardSpec {
  readonly key: string;
  readonly icon: ReactNode;
  readonly tint: string;
  readonly title: string;
  readonly desc: string;
  /** 展示条件标签：'asr'=缺 ASR 模型；'llm'=未配置 LLM。 */
  readonly tag?: 'asr' | 'llm';
}

const CARDS: readonly CardSpec[] = [
  {
    key: 'create',
    icon: <FolderAddOutlined />,
    tint: tokens.colorPrimary,
    title: '新建项目',
    desc: '导入本地短剧文件夹，逐集转写与冲突分析',
    tag: 'asr',
  },
  {
    key: 'resume',
    icon: <PlayCircleOutlined />,
    tint: tokens.colorSuccess,
    title: '继续创作',
    desc: '回到最近的项目，从上次的进度继续',
  },
  {
    key: 'settings',
    icon: <SettingOutlined />,
    tint: tokens.colorWarning,
    title: '引擎中心',
    desc: '下载模型、配置 LLM 端点',
  },
];

export function StartCards({
  onCreated,
  needsAsrModel,
}: {
  onCreated: (projectId: string) => void;
  needsAsrModel: boolean;
}): ReactElement {
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const create = (): void => {
    void createThroughFolder(setCreating, onCreated);
  };

  const handlers: Record<string, () => void> = {
    create: create,
    resume: () => {
      void navigate('/projects');
    },
    settings: () => {
      void navigate('/engines');
    },
  };
  const tags: Record<string, string | undefined> = {
    create: needsAsrModel ? '需要模型' : undefined,
  };

  return (
    <section>
      <PanelTitle>开始创作</PanelTitle>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
        {CARDS.map((card) => (
          <WorkflowCard
            key={card.key}
            spec={card}
            tag={tags[card.key]}
            busy={creating && card.key === 'create'}
            onClick={handlers[card.key] ?? NOOP}
          />
        ))}
      </div>
    </section>
  );
}

async function createThroughFolder(
  setCreating: (busy: boolean) => void,
  onCreated: (projectId: string) => void,
): Promise<void> {
  const folder = await pickFolder();
  if (folder === null) return;
  setCreating(true);
  try {
    const name = folder.split(/[\\/]/).pop() ?? '新项目';
    const project = await projectApi.create(name, folder);
    await projectApi.scanEpisodes(project.id);
    onCreated(project.id);
  } finally {
    setCreating(false);
  }
}

const NOOP = (): void => undefined;

function WorkflowCard({
  spec,
  tag,
  busy,
  onClick,
}: {
  spec: CardSpec;
  tag?: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <Card hoverable loading={busy} styles={{ body: { padding: '18px 20px', height: '100%' } }} onClick={onClick}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start' }}>
          <span
            style={{
              width: 40,
              height: 40,
              borderRadius: tokens.radiusCard,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: tokens.fontHeading,
              color: spec.tint,
              background: `${spec.tint}1A`,
            }}
          >
            {spec.icon}
          </span>
          {tag !== undefined && (
            <span
              style={{
                marginLeft: 'auto',
                fontSize: tokens.fontMicro,
                padding: '2px 9px',
                borderRadius: tokens.radiusChip,
                color: tokens.colorWarning,
                border: `1px solid ${tokens.colorWarning}66`,
                background: `${tokens.colorWarning}14`,
              }}
            >
              {tag}
            </span>
          )}
        </div>
        <div style={{ fontSize: tokens.fontTitle, fontWeight: 600, color: tokens.textPrimary }}>{spec.title}</div>
        <div style={{ fontSize: tokens.fontCaption, lineHeight: '20px', color: tokens.textTertiary }}>{spec.desc}</div>
      </div>
    </Card>
  );
}

function PanelTitle({ children }: { children: string }) {
  return (
    <h3
      style={{
        margin: '0 0 12px',
        fontSize: tokens.fontTitle,
        fontWeight: 600,
        color: tokens.textPrimary,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ width: 3, height: 14, borderRadius: tokens.radiusDot, background: tokens.gradientAccent }} />
      {children}
    </h3>
  );
}
