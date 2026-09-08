/** 出片中心：选模式 → 一键出片（编排/配音/渲染全自动），成品入作品库。 */
import { App as AntdApp, Button, Card, Empty, Progress, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { ExportJob, NarrationMode, Project } from '@dramaclip/protocol';
import { exportApi, projectApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { MODE_INFO } from '../../components/modeMeta';
import { useProduction, type ProduceTask } from './production';

const ALL_MODES = MODE_INFO.map((item) => item.mode) as NarrationMode[];

function modeLabel(mode: string): string {
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode;
}

const STAGE_META: Record<ProduceTask['stage'], { label: string; color: string }> = {
  planning: { label: '编排配音', color: tokens.colorInfo },
  rendering: { label: '渲染成片', color: tokens.colorWarning },
  done: { label: '已完成', color: tokens.colorSuccess },
  failed: { label: '失败', color: tokens.colorError },
};

/** 项目出片中心。 */
export function ProductionPage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const setCurrentProjectId = useUiStore((state) => state.setCurrentProjectId);
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<NarrationMode[]>([]);
  const [exports, setExports] = useState<ExportJob[] | null>(null);
  const { tasks, running, run } = useProduction(projectId);

  useEffect(() => {
    setCurrentProjectId(projectId === '' ? null : projectId);
    void projectApi.get(projectId).then((detail) => {
      setProject(detail.project);
    });
    return () => {
      setCurrentProjectId(null);
    };
  }, [projectId, setCurrentProjectId]);

  const loadExports = useCallback(async () => {
    setExports(await exportApi.list(projectId));
  }, [projectId]);

  useEffect(() => {
    if (running || tasks.some((task) => task.stage === 'done')) void loadExports();
  }, [loadExports, running, tasks]);

  const start = (): void => {
    if (selected.length === 0) return;
    void run(selected).catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  };

  const toggle = (mode: NarrationMode): void => {
    setSelected((prev) => (prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]));
  };

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <PageHeader projectName={project?.name} />

      <ModeSelectCard
        selected={selected}
        running={running}
        onToggle={toggle}
        onSelectAll={() => {
          setSelected(ALL_MODES);
        }}
        onStart={start}
      />

      {tasks.length > 0 && (
        <Card size="small" title="出片进度">
          {tasks.map((task) => (
            <TaskRow key={task.mode} task={task} />
          ))}
        </Card>
      )}

      <ExportsCard exports={exports} />
    </div>
  );
}

function ModeTile({
  label,
  desc,
  needs,
  checked,
  onToggle,
}: {
  label: string;
  desc: string;
  needs: ('copy' | 'voice')[];
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      size="small"
      hoverable
      onClick={onToggle}
      style={{
        borderColor: checked ? tokens.colorPrimary : tokens.border,
        background: checked ? tokens.accentSoft : undefined,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <strong style={{ color: tokens.textPrimary, fontSize: 13.5 }}>{label}</strong>
          {checked && (
            <Tag color="blue" style={{ marginRight: 0 }}>
              已选
            </Tag>
          )}
        </div>
        <span style={{ fontSize: 12, color: tokens.textTertiary }}>{desc}</span>
        <span style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
          {needs.includes('copy') ? (
            <NeedBadge text="含 AI 文案" />
          ) : (
            <NeedBadge text="无需文案" muted />
          )}
          {needs.includes('voice') ? (
            <NeedBadge text="含 AI 配音" />
          ) : (
            <NeedBadge text="原声" muted />
          )}
        </span>
      </div>
    </Card>
  );
}

function NeedBadge({ text, muted = false }: { text: string; muted?: boolean }): React.ReactElement {
  return (
    <span
      style={{
        fontSize: 10.5,
        padding: '1px 7px',
        borderRadius: 999,
        color: muted ? tokens.textTertiary : tokens.colorSuccess,
        border: `1px solid ${muted ? tokens.border : `${tokens.colorSuccess}55`}`,
        background: muted ? 'transparent' : `${tokens.colorSuccess}12`,
      }}
    >
      {text}
    </span>
  );
}

function TaskRow({ task }: { task: ProduceTask }) {
  const meta = STAGE_META[task.stage];
  return (
    <div style={{ padding: '10px 0', borderBottom: `1px solid ${tokens.borderSecondary}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <strong style={{ fontSize: 13.5, color: tokens.textPrimary }}>{modeLabel(task.mode)}</strong>
        <Tag color={meta.color}>{meta.label}</Tag>
        <span style={{ fontSize: 12, color: task.stage === 'failed' ? tokens.colorError : tokens.textTertiary }}>
          {task.note}
        </span>
        {task.stage === 'done' && (
          <Link to="/works" style={{ marginLeft: 'auto', fontSize: 12, color: tokens.colorPrimary }}>
            查看作品 →
          </Link>
        )}
      </div>
      {(task.stage === 'planning' || task.stage === 'rendering') && (
        <Progress percent={task.percent} size="small" strokeColor={meta.color} />
      )}
    </div>
  );
}


function PageHeader({ projectName }: { projectName?: string }): React.ReactElement {
  return (
    <header style={{ display: 'flex', alignItems: 'flex-end' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: tokens.textPrimary }}>
          {projectName ?? '…'} · 出片中心
        </h1>
        <div style={{ fontSize: 13, color: tokens.textTertiary, marginTop: 6 }}>
          选择模式一键出片：AI 编排、配音、渲染自动完成，成品在「作品库」查看
        </div>
      </div>
      <Link to="/works" style={{ marginLeft: 'auto', fontSize: 13, color: tokens.colorPrimary }}>
        前往作品库 →
      </Link>
    </header>
  );
}

function ModeSelectCard({
  selected,
  running,
  onToggle,
  onSelectAll,
  onStart,
}: {
  selected: NarrationMode[];
  running: boolean;
  onToggle: (mode: NarrationMode) => void;
  onSelectAll: () => void;
  onStart: () => void;
}) {
  return (
    <Card size="small" title="选择出片模式">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
        {MODE_INFO.map((item) => (
          <ModeTile
            key={item.mode}
            label={item.label}
            desc={item.desc}
            needs={item.needs}
            checked={selected.includes(item.mode as NarrationMode)}
            onToggle={() => {
              onToggle(item.mode as NarrationMode);
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: 16 }}>
        <span style={{ fontSize: 12, color: tokens.textTertiary }}>
          已选 {String(selected.length)} / {String(MODE_INFO.length)} 个模式
        </span>
        <Button size="small" style={{ marginLeft: 12 }} disabled={running} onClick={onSelectAll}>
          全选
        </Button>
        <Button
          type="primary"
          style={{ marginLeft: 'auto' }}
          disabled={selected.length === 0}
          loading={running}
          onClick={onStart}
        >
          {running ? '出片中…' : '开始出片'}
        </Button>
      </div>
    </Card>
  );
}

function ExportsCard({ exports }: { exports: ExportJob[] | null }) {
  return (
    <Card size="small" title="本项目导出记录">
      {exports === null ? null : exports.length === 0 ? (
        <Empty description="还没有导出记录" styles={{ image: { height: 60 } }} />
      ) : (
        exports.slice(0, 8).map((job) => <ExportRow key={job.id} job={job} />)
      )}
    </Card>
  );
}

function ExportRow({ job }: { job: ExportJob }) {
  const label = job.status === 'completed' ? '完成' : job.status === 'failed' ? '失败' : '进行中';
  const color = job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'processing';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 0',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
        fontSize: 13,
      }}
    >
      <Tag color={color}>{label}</Tag>
      <span style={{ color: tokens.textPrimary }}>{modeLabel(job.narration_mode ?? '')}</span>
      <span style={{ marginLeft: 'auto', fontSize: 12, color: tokens.textTertiary }}>
        {job.duration_s !== undefined ? `${String(Math.round(job.duration_s))}s` : ''}
      </span>
    </div>
  );
}
