import { App as AntdApp, Button, Card, Statistic } from 'antd';
import {
  FolderOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DashboardSummary, HealthResult, ModelInfo, Project } from '@dramaclip/protocol';
import { pickFolder, projectApi, rpc, systemApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { RecentProjects } from './RecentProjects';
import { SectionTitle } from './SectionTitle';
import { TodoCard } from './TodoCard';
import { useTodos } from './useTodos';

/** 工作台（docs/desktop/03 §7.1）：待办 + 统计概览 + 最近项目 + 系统状态。 */
export function HomePage() {
  return <HomeContent />;
}

function HomeContent() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [llmBaseUrl, setLlmBaseUrl] = useState<string>('');
  const [creating, setCreating] = useState(false);
  const serviceState = useUiStore((state) => state.serviceState);

  const load = useCallback(async () => {
    const [summaryData, projectList, healthData, modelList, settings] = await Promise.all([
      projectApi.dashboardSummary(),
      projectApi.list(),
      systemApi.health(),
      rpc<ModelInfo[]>('models.list').catch(() => null),
      rpc<Record<string, string>>('settings.get').catch(() => null),
    ]);
    setSummary(summaryData);
    setProjects(projectList.slice(0, 6));
    setHealth(healthData);
    setModels(modelList);
    setLlmBaseUrl(settings?.['llm.base_url'] ?? '');
  }, []);

  // 服务就绪前发起的 RPC 会失败；ready 后重载一次（修复启动时序竞争）
  useEffect(() => {
    if (serviceState === 'ready') void load();
  }, [load, serviceState]);

  const onCreate = useCallback(async () => {
    const folder = await pickFolder();
    if (folder === null) return;
    setCreating(true);
    try {
      const name = folder.replaceAll('\\', '/').split('/').pop() ?? '新项目';
      const project = await projectApi.create(name, folder);
      await projectApi.scanEpisodes(project.id);
      message.success(`已创建「${name}」`);
      await navigate(`/projects/${project.id}/analysis`);
    } finally {
      setCreating(false);
    }
  }, [message, navigate]);

  const todos = useTodos(models, llmBaseUrl !== '', serviceState === 'unavailable');

  return (
    <div style={{ maxWidth: 1040, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 28 }}>
      <HomeHeader creating={creating} onCreate={() => void onCreate()} />
      <TodoCard items={todos} />
      <SummaryCards
        summary={summary}
        onProjects={() => {
          void navigate('/projects');
        }}
      />
      <RecentProjects projects={projects} />
      <SystemStatus health={health} />
    </div>
  );
}

function HomeHeader({ creating, onCreate }: { creating: boolean; onCreate: () => void }) {
  return (
    <header style={{ display: 'flex', alignItems: 'flex-end' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: tokens.textPrimary }}>
          创作工作台
        </h1>
        <div style={{ fontSize: 13, color: tokens.textTertiary, marginTop: 6 }}>
          本地优先 · 导入剧集 → AI 分析 → 生成推广短视频
        </div>
      </div>
      <Button
        type="primary"
        loading={creating}
        style={{ marginLeft: 'auto', height: 38, paddingInline: 20 }}
        onClick={onCreate}
      >
        新建项目
      </Button>
    </header>
  );
}

function StatCard({
  icon,
  tint,
  title,
  value,
  onClick,
}: {
  icon: ReactNode;
  tint: string;
  title: string;
  value: number | string | undefined;
  onClick?: () => void;
}) {
  return (
    <Card hoverable={onClick !== undefined} onClick={onClick} styles={{ body: { padding: 18 } }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span
          style={{
            width: 42,
            height: 42,
            borderRadius: 11,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 19,
            color: tint,
            background: `${tint}1F`,
          }}
        >
          {icon}
        </span>
        <Statistic
          title={<span style={{ fontSize: 12, color: tokens.textTertiary }}>{title}</span>}
          value={value ?? '…'}
          styles={{ content: { fontSize: 26, fontWeight: 700, color: tokens.textPrimary } }}
        />
      </div>
    </Card>
  );
}

function SummaryCards({
  summary,
  onProjects,
}: {
  summary: DashboardSummary | null;
  onProjects: () => void;
}) {
  return (
    <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
      <StatCard
        icon={<FolderOutlined />}
        tint={tokens.colorPrimary}
        title="项目"
        value={summary?.project_count}
        onClick={onProjects}
      />
      <StatCard
        icon={<VideoCameraOutlined />}
        tint={tokens.colorAccent}
        title="剧集总数"
        value={summary?.episode_count}
      />
      <StatCard
        icon={<ThunderboltOutlined />}
        tint={tokens.colorWarning}
        title="已分析集数"
        value={summary?.analyzed_episodes}
      />
      <StatCard
        icon={<PlayCircleOutlined />}
        tint={tokens.colorSuccess}
        title="已导出视频"
        value={summary?.export_count}
      />
    </section>
  );
}

function SystemStatus({ health }: { health: HealthResult | null }) {
  const items = [
    { label: '服务', value: health?.status ?? '…' },
    { label: '运行时长', value: `${String(Math.round(health?.uptime_s ?? 0))}s` },
    ...(health?.gpu === undefined ? [] : [{ label: 'GPU', value: health.gpu }]),
  ];
  return (
    <section>
      <SectionTitle>系统状态</SectionTitle>
      <Card styles={{ body: { padding: '14px 18px' } }}>
        <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
          {items.map((item) => (
            <div key={item.label} style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ fontSize: 12, color: tokens.textTertiary }}>{item.label}</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: tokens.textSecondary }}>
                {item.value}
              </span>
            </div>
          ))}
          <span
            style={{
              marginLeft: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12,
              color: tokens.colorSuccess,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 4,
                background: tokens.colorSuccess,
                boxShadow: `0 0 6px ${tokens.colorSuccess}`,
              }}
            />
            在线
          </span>
        </div>
      </Card>
    </section>
  );
}
