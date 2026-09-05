import { App as AntdApp, Button, Card, Empty, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { ExportJob } from '@dramaclip/protocol';
import { exportApi, mediaUrl, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';

/** 导出管理页（docs/desktop/03 §7.7 W4 版）：任务列表 + 成片预览（dramaclip:// 协议）。 */
export function ExportPage() {
  const { projectId = '' } = useParams();
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  const load = useCallback(async () => {
    setJobs(await exportApi.list(projectId));
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const completed = jobs.filter((job) => job.status === 'completed');
  const active: ExportJob | null =
    completed.find((job) => job.output_path === previewPath) ?? completed[0] ?? null;

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <header>
        <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>导出管理</h1>
      </header>
      <CompletedList
        jobs={completed}
        activeId={active?.id ?? null}
        onSelect={(path) => {
          setPreviewPath(path);
        }}
      />
      <PreviewCard path={active?.output_path ?? null} />
      <AllJobs jobs={jobs} />
    </div>
  );
}

function CompletedList({
  jobs,
  activeId,
  onSelect,
}: {
  jobs: ExportJob[];
  activeId: string | null;
  onSelect: (path: string | null) => void;
}) {
  return (
    <Card size="small" style={{ flex: 1 }} title="成片列表">
      {jobs.length === 0 ? (
        <Empty description="暂无成品——先在「生成导出」页导出" styles={{ image: { height: 60 } }} />
      ) : (
        jobs.map((job) => (
          <div
            key={job.id}
            onClick={() => {
              onSelect(job.output_path ?? null);
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 12px',
              marginBottom: 8,
              borderRadius: 6,
              cursor: 'pointer',
              border: `1px solid ${activeId === job.id ? tokens.colorPrimary : tokens.border}`,
              background: activeId === job.id ? 'rgba(77,159,255,0.08)' : 'transparent',
            }}
          >
            <Tag color="success">完成</Tag>
            <span style={{ color: tokens.textPrimary, fontSize: 13 }}>{modeName(job.narration_mode)}</span>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: tokens.textTertiary }}>
              {new Date(job.completed_at ?? job.created_at).toLocaleString('zh-CN')}
            </span>
          </div>
        ))
      )}
    </Card>
  );
}

function PreviewCard({ path }: { path: string | null }) {
  const { message } = AntdApp.useApp();
  if (path === null) {
    return (
      <Card size="small" style={{ width: 300 }} title="预览">
        <Empty description="选择左侧成片预览" styles={{ image: { height: 60 } }} />
      </Card>
    );
  }
  return (
    <Card size="small" style={{ width: 300 }} title="预览">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <video
          key={path}
          src={mediaUrl(path)}
          onError={(event) => {
            const media = event.currentTarget;
            console.error(
              `[video-error] code=${String(media.error?.code)} message=${String(media.error?.message)} src=${media.src}`,
            );
          }}
          controls
          style={{ width: '100%', borderRadius: 8, background: '#000', aspectRatio: '9/16' }}
        />
        <Button
          size="small"
          onClick={() => {
            revealInFolder(path).catch(() => {
              message.error('打开文件夹失败');
            });
          }}
        >
          打开所在文件夹
        </Button>
      </div>
    </Card>
  );
}

function AllJobs({ jobs }: { jobs: ExportJob[] }) {
  return (
    <Card size="small" title="全部任务">
      {jobs.map((job) => (
        <div
          key={job.id}
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            padding: '8px 0',
            borderBottom: `1px solid ${tokens.borderSecondary}`,
            fontSize: 13,
          }}
        >
          <Tag color={job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'processing'}>
            {job.status}
          </Tag>
          <span style={{ color: tokens.textPrimary }}>{modeName(job.narration_mode)}</span>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: tokens.textTertiary }}>
            {String(Math.round(job.progress))}%
          </span>
        </div>
      ))}
      {jobs.length === 0 && <div style={{ color: tokens.textTertiary, fontSize: 12 }}>暂无任务</div>}
    </Card>
  );
}

function modeName(mode: string | undefined): string {
  return (
    {
      raw_clip: '纯原片剪辑',
      intro_narration: '片头解说',
    }[mode ?? ''] ?? (mode ?? '-')
  );
}
