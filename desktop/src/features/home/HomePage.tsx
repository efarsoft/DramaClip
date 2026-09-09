import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DashboardSummary, ModelInfo, Project, WorkItem } from '@dramaclip/protocol';
import { listWorks, projectApi, rpc } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { EnvPanel, TipsPanel, ToolboxPanel } from './EnvPanel';
import { RecentProjects } from './RecentProjects';
import { RecentWorks } from './RecentWorks';
import { StartCards } from './StartCards';
import { TodoCard } from './TodoCard';
import { useTodos } from './useTodos';

/** 工作台：问候 + 开始创作 + 最近项目（左）｜环境/工具/上手（右）。 */
export function HomePage() {
  return <HomeContent />;
}

function HomeContent() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [ttsEngine, setTtsEngine] = useState('edge');
  const [works, setWorks] = useState<WorkItem[]>([]);
  const serviceState = useUiStore((state) => state.serviceState);

  const load = useCallback(async () => {
    const [summaryData, projectList, modelList, settings, workItems] = await Promise.all([
      projectApi.dashboardSummary(),
      projectApi.list(),
      rpc<ModelInfo[]>('models.list').catch(() => null),
      rpc<Record<string, string>>('settings.get').catch(() => null),
      listWorks(6).catch((): WorkItem[] => []),
    ]);
    setSummary(summaryData);
    setProjects(projectList.slice(0, 6));
    setModels(modelList);
    setLlmBaseUrl(settings?.['llm.base_url'] ?? '');
    setTtsEngine(settings?.['tts.engine'] ?? 'edge');
    setWorks(workItems);
  }, []);

  // 服务就绪前发起的 RPC 会失败；ready 后重载一次（修复启动时序竞争）
  useEffect(() => {
    if (serviceState === 'ready') void load();
  }, [load, serviceState]);

  const todos = useTodos(models, llmBaseUrl !== '', serviceState === 'unavailable');
  const needsModel = (models ?? []).some((m) => m.required && m.status !== 'installed');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <GreetingHeader summary={summary} />
      {todos.length > 0 && <TodoCard items={todos} />}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 330px', gap: 16, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          <StartCards needsAsrModel={needsModel} onCreated={(projectId) => {
              void navigate(`/projects/${projectId}/analysis`);
            }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          <RecentProjects projects={projects} />
          <RecentWorks works={works} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <EnvPanel models={models} llmBaseUrl={llmBaseUrl} ttsEngine={ttsEngine} />
          <ToolboxPanel />
          <TipsPanel />
        </div>
      </div>
    </div>
  );
}

function greetingText(): string {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 12) return '上午好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

function GreetingHeader({ summary }: { summary: DashboardSummary | null }) {
  const now = new Date();
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()] ?? '';
  const chips = [
    { label: '项目', value: summary?.project_count },
    { label: '剧集', value: summary?.episode_count },
    { label: '已分析', value: summary?.analyzed_episodes },
    { label: '已导出', value: summary?.export_count },
  ];
  return (
    <header style={{ display: 'flex', alignItems: 'flex-end' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: tokens.textPrimary }}>
          {greetingText()}
        </h1>
        <div style={{ fontSize: 13, color: tokens.textTertiary, marginTop: 6 }}>
          {String(now.getMonth() + 1)}月{String(now.getDate())}日 星期{week} ·
          选择一个方式开始，短剧素材也可以拖进来
        </div>
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
        {chips.map((chip) => (
          <span
            key={chip.label}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              padding: '6px 14px',
              borderRadius: 9,
              background: tokens.bgContainer,
              border: `1px solid ${tokens.borderSecondary}`,
            }}
          >
            <span style={{ fontSize: 16, fontWeight: 700, color: tokens.textPrimary }}>
              {chip.value ?? '…'}
            </span>
            <span style={{ fontSize: 10, color: tokens.textTertiary }}>{chip.label}</span>
          </span>
        ))}
      </div>
    </header>
  );
}
