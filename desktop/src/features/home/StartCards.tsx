/** 开始创作卡片区 + 九模式介绍弹窗（工作台主列）。 */
import { useState, type ReactElement, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Modal } from 'antd';
import {
  AppstoreOutlined,
  FolderAddOutlined,
  PlayCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { pickFolder, projectApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { MODE_INFO } from '../../components/modeMeta';

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
    desc: '导入本地短剧文件夹，AI 自动预筛与全量分析',
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
    key: 'modes',
    icon: <AppstoreOutlined />,
    tint: tokens.colorAccent,
    title: '九种出片模式',
    desc: '高光混剪、剧情解说、双人对谈……按推广场景选择',
    tag: 'llm',
  },
  {
    key: 'settings',
    icon: <SettingOutlined />,
    tint: tokens.colorWarning,
    title: '引擎与设置',
    desc: '下载模型、配置 LLM 端点与出片参数',
  },
];

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

export function StartCards({
  onCreated,
  needsAsrModel,
  needsLlm,
}: {
  onCreated: (projectId: string) => void;
  needsAsrModel: boolean;
  needsLlm: boolean;
}): ReactElement {
  const navigate = useNavigate();
  const [modesOpen, setModesOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const create = (): void => {
    void createThroughFolder(setCreating, onCreated);
  };

  const handlers: Record<string, () => void> = {
    create: create,
    resume: () => {
      void navigate('/projects');
    },
    modes: () => {
      setModesOpen(true);
    },
    settings: () => {
      void navigate('/models');
    },
  };
  const tags: Record<string, string | undefined> = {
    create: needsAsrModel ? '需要模型' : undefined,
    modes: needsLlm ? '建议配置 LLM' : undefined,
  };

  return (
    <section>
      <PanelTitle>开始创作</PanelTitle>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
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
      <ModesModal open={modesOpen} onClose={() => { setModesOpen(false); }} />
    </section>
  );
}

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
              borderRadius: 10,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 18,
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
                fontSize: 11,
                padding: '2px 9px',
                borderRadius: 999,
                color: tokens.colorWarning,
                border: `1px solid ${tokens.colorWarning}66`,
                background: `${tokens.colorWarning}14`,
              }}
            >
              {tag}
            </span>
          )}
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, color: tokens.textPrimary }}>{spec.title}</div>
        <div style={{ fontSize: 12.5, lineHeight: '20px', color: tokens.textTertiary }}>{spec.desc}</div>
      </div>
    </Card>
  );
}

function ModesModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="九种出片模式" width={560}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
        {MODE_INFO.map((item, index) => (
          <div key={item.mode} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span
              style={{
                width: 22,
                height: 22,
                flexShrink: 0,
                borderRadius: 6,
                background: tokens.accentSoft,
                color: tokens.colorPrimary,
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {index + 1}
            </span>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: tokens.textPrimary }}>{item.label}</div>
              <div style={{ fontSize: 12.5, color: tokens.textTertiary }}>{item.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function PanelTitle({ children }: { children: string }) {
  return (
    <h3
      style={{
        margin: '0 0 12px',
        fontSize: 15,
        fontWeight: 600,
        color: tokens.textPrimary,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ width: 3, height: 14, borderRadius: 2, background: tokens.gradientAccent }} />
      {children}
    </h3>
  );
}
