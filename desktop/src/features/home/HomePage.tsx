import { App as AntdApp, Button, Card, Statistic } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DashboardSummary, HealthResult, ModelInfo, Project } from '@dramaclip/protocol';
import { pickFolder, projectApi, rpc, systemApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { TodoCard } from './TodoCard';
import { useTodos } from './useTodos';

/** 工作台（docs/desktop/03 §7.1 W3 子集）：统计概览 + 最近项目 + 快捷导入 + 服务状态。 */
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
    <div style={{ maxWidth: 960, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 32 }}>
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
    <header style={{ display: 'flex', alignItems: 'center' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 24, color: tokens.textPrimary }}>创作工作台</h1>
        <div style={{ fontSize: 12, color: tokens.textTertiary, marginTop: 4 }}>
          本地优先 · 导入剧集 → AI 分析 → 生成推广短视频
        </div>
      </div>
      <Button type="primary" loading={creating} style={{ marginLeft: 'auto' }} onClick={onCreate}>
        新建项目
      </Button>
    </header>
  );
}

function SummaryCards({
  summary,
  onProjects,
}: {
  summary: DashboardSummary | null;
  onProjects: () => void;
}) {
  const cards = [
    { title: '项目', value: summary?.project_count, onClick: onProjects },
    { title: '剧集总数', value: summary?.episode_count },
    { title: '已分析集数', value: summary?.analyzed_episodes },
    { title: '已导出视频', value: summary?.export_count },
  ];
  return (
    <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
      {cards.map((card) => (
        <Card key={card.title} hoverable onClick={card.onClick}>
          <Statistic title={card.title} value={card.value ?? '…'} />
        </Card>
      ))}
    </section>
  );
}

function RecentProjects({ projects }: { projects: Project[] }) {
  const navigate = useNavigate();
  return (
    <section>
      <SectionTitle>最近项目</SectionTitle>
      {projects.length === 0 ? (
        <Card variant="outlined">
          <div style={{ textAlign: 'center', color: tokens.textSecondary, padding: 24 }}>
            还没有项目——点击右上角「新建项目」，选择剧集文件夹开始
          </div>
        </Card>
      ) : (
        projects.map((project) => (
          <Card
            key={project.id}
            size="small"
            hoverable
            style={{ marginBottom: 8 }}
            onClick={() => {
              void navigate(`/projects/${project.id}/analysis`);
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <strong style={{ color: tokens.textPrimary }}>{project.name}</strong>
              <span style={{ fontSize: 12, color: tokens.textSecondary }}>
                {String(project.episode_count)} 集
              </span>
              <span style={{ marginLeft: 'auto', fontSize: 12, color: tokens.textTertiary }}>
                {project.status}
              </span>
            </div>
          </Card>
        ))
      )}
    </section>
  );
}

function SystemStatus({ health }: { health: HealthResult | null }) {
  return (
    <section>
      <SectionTitle>系统状态</SectionTitle>
      <Card size="small">
        <div style={{ display: 'flex', gap: 24, fontSize: 13, color: tokens.textSecondary }}>
          <span>服务：{health?.status ?? '…'}</span>
          <span>运行 {String(Math.round(health?.uptime_s ?? 0))}s</span>
          {health?.gpu !== undefined && <span>GPU：{health.gpu}</span>}
        </div>
      </Card>
    </section>
  );
}

function SectionTitle({ children }: { children: string }) {
  return (
    <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600, color: tokens.textPrimary }}>
      {children}
    </h3>
  );
}
