import { App as AntdApp, Button, Card, Empty, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { ExportJob, NarrationPlan } from '@dramaclip/protocol';
import { exportApi, narrationApi } from '../../services/client';
import { tokens } from '../../styles/theme';

const PLAN_STATUS_COLORS: Record<string, string> = {
  ready: 'success',
  generating: 'processing',
  failed: 'error',
  pending: 'default',
};

/** 生成进度页（docs/desktop/03 §7.5 W4 版）：编排方案列表 + 逐方案导出 + 导出记录。 */
export function GeneratePage() {
  const { projectId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const [plans, setPlans] = useState<NarrationPlan[] | null>(null);
  const [exports, setExports] = useState<ExportJob[]>([]);

  const load = useCallback(async () => {
    const [planList, exportList] = await Promise.all([
      narrationApi.listPlans(projectId),
      exportApi.list(projectId),
    ]);
    setPlans(planList);
    setExports(exportList);
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onExport = useCallback(
    async (plan: NarrationPlan) => {
      try {
        await exportApi.start(plan.id);
        message.success(`「${modeName(plan.narration_mode)}」导出任务已提交`);
        await load();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [load, message],
  );

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <header>
        <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>生成与导出</h1>
      </header>

      <Card size="small" title="编排方案">
        {plans === null ? null : plans.length === 0 ? (
          <Empty description="还没有编排方案——先到「模式选择」生成" styles={{ image: { height: 60 } }} />
        ) : (
          plans.map((plan) => <PlanRow key={plan.id} plan={plan} exports={exports} onExport={onExport} />)
        )}
      </Card>

      <Card size="small" title="导出记录">
        {exports.length === 0 ? (
          <Empty description="暂无导出记录" styles={{ image: { height: 60 } }} />
        ) : (
          exports.map((job) => <ExportRow key={job.id} job={job} />)
        )}
      </Card>
    </div>
  );
}

function PlanRow({
  plan,
  exports,
  onExport,
}: {
  plan: NarrationPlan;
  exports: ExportJob[];
  onExport: (plan: NarrationPlan) => Promise<void>;
}) {
  const related = exports.filter((job) => job.plan_id === plan.id);
  const completed = related.find((job) => job.status === 'completed');
  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <strong style={{ color: tokens.textPrimary }}>{modeName(plan.narration_mode)}</strong>
        <Tag color={PLAN_STATUS_COLORS[plan.status] ?? 'default'}>{plan.status}</Tag>
        <span style={{ fontSize: 12, color: tokens.textSecondary }}>
          {String(plan.plan_data.timeline.length)} 段 · {String(totalDuration(plan))}s
        </span>
        <Button size="small" type="primary" style={{ marginLeft: 'auto' }} onClick={() => void onExport(plan)}>
          导出成片
        </Button>
      </div>
      <TimelineStrip plan={plan} />
      {completed !== undefined && (
        <div style={{ marginTop: 8, fontSize: 12, color: tokens.textSecondary }}>
          成片：{completed.output_path ?? '-'}
        </div>
      )}
    </Card>
  );
}

function TimelineStrip({ plan }: { plan: NarrationPlan }) {
  const total = Math.max(totalDuration(plan), 1);
  const colors: Record<string, string> = {
    original: '#2563EB',
    narration: '#F59E0B',
    ducked: '#6B7280',
  };
  return (
    <div style={{ display: 'flex', height: 14, borderRadius: 3, overflow: 'hidden', marginTop: 10 }}>
      {plan.plan_data.timeline.map((segment, index) => {
        const width = String(((segment.end - segment.start) / total) * 100);
        return (
          <div
            key={`${String(segment.start)}-${String(index)}`}
            title={`${segmentLabel(segment)} ${String(segment.start)}-${String(segment.end)}s`}
            style={{
              width: `${width}%`,
              background: colors[segment.audio] ?? '#333740',
              marginRight: 1,
            }}
          />
        );
      })}
    </div>
  );
}

function ExportRow({ job }: { job: ExportJob }) {
  const statusColor =
    job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'processing';
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
      <Tag color={statusColor}>{job.status}</Tag>
      <span style={{ color: tokens.textPrimary }}>{modeName(job.narration_mode ?? '')}</span>
      <span style={{ fontSize: 12, color: tokens.textTertiary, fontFamily: tokens.fontFamilyMono }}>
        {job.output_path ?? '-'}
      </span>
    </div>
  );
}

function modeName(mode: string): string {
  return (
    {
      raw_clip: '纯原片剪辑',
      intro_narration: '片头解说',
      cross_narration: '交叉解说',
      full_narration: '全片解说',
      dialogue_narration: '剧情解说',
      subtitle_flow: '字幕金句流',
      ultra_short_hook: '超短悬念版',
      dual_host_chat: '双人对谈',
      inner_monologue: '内心独白',
    }[mode] ?? mode
  );
}

function segmentLabel(segment: { audio: string }): string {
  return { original: '原声', narration: '旁白', ducked: '压低' }[segment.audio] ?? segment.audio;
}

function totalDuration(plan: NarrationPlan): number {
  return Math.round(plan.plan_data.timeline.reduce((sum, seg) => sum + (seg.end - seg.start), 0));
}
