/** 作品库：跨项目已完成的成片（卡片网格 + 预览 + 定位文件）。 */
import { useCallback, useEffect, useState } from 'react';
import { App as AntdApp, Card, Empty, Modal, Tag } from 'antd';
import { FolderOpenOutlined, PlayCircleOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { listWorks, mediaUrl, projectApi, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';
import { PageHeader, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';

const MODE_COLORS = ['#4D9FFF', '#7C5CFF', '#34D399', '#FBBF24', '#F87171', '#60A5FA'];

function modeLabel(mode: string | undefined): string {
  if (mode === undefined) return '成片';
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode;
}

function modeColor(mode: string | undefined): string {
  if (mode === undefined) return tokens.textTertiary;
  const index = MODE_INFO.findIndex((item) => item.mode === mode);
  return MODE_COLORS[index % MODE_COLORS.length] ?? tokens.colorPrimary;
}

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(seconds: number | undefined): string {
  if (seconds === undefined || seconds <= 0) return '—';
  const total = Math.round(seconds);
  return `${String(Math.floor(total / 60))}:${String(total % 60).padStart(2, '0')}`;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '';
  const date = new Date(ms);
  return `${String(date.getMonth() + 1)}/${String(date.getDate())} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/** 作品库页（导航「作品」）。 */
export function WorksPage() {
  const [works, setWorks] = useState<WorkItem[] | null>(null);
  const [preview, setPreview] = useState<WorkItem | null>(null);
  const [covers, setCovers] = useState<Map<string, string>>(new Map());

  const load = useCallback(async () => {
    const [items, projects] = await Promise.all([
      listWorks(),
      projectApi.list().catch(() => []),
    ]);
    setWorks(items);
    setCovers(new Map(projects.map((p) => [p.id, p.cover_path ?? ''])));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageShell>
      <PageHeader
        title="作品库"
        chip={`共 ${String(works?.length ?? 0)} 个`}
        desc="全部项目制作完成的成片；点击卡片可预览"
      />

      {works === null ? (
        <Card loading />
      ) : works.length === 0 ? (
        <Card>
          <Empty description="还没有完成的成片——去项目里生成并导出第一个作品吧" />
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
          {works.map((work) => (
            <WorkCard
              key={work.id}
              work={work}
              cover={covers.get(work.project_id) ?? undefined}
              onPreview={() => {
                setPreview(work);
              }}
            />
          ))}
        </div>
      )}

      <PreviewModal work={preview} onClose={() => { setPreview(null); }} />
    </PageShell>
  );
}

function PreviewModal({ work, onClose }: { work: WorkItem | null; onClose: () => void }) {
  return (
    <Modal
      open={work !== null}
      onCancel={onClose}
      footer={null}
      width={520}
      title={work === null ? '' : `${work.project_name} · ${modeLabel(work.narration_mode)}`}
    >
      {work !== null && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <video
            src={mediaUrl(work.output_path)}
            controls
            autoPlay
            style={{ width: '100%', borderRadius: tokens.radiusControl, background: '#000' }}
          />
          <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
            {formatDuration(work.duration_s)} · {formatSize(work.size_bytes)} ·{' '}
            {formatDate(work.completed_at)}
          </div>
        </div>
      )}
    </Modal>
  );
}

function WorkMeta({ work }: { work: WorkItem }): React.ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <div
      style={{
        marginTop: 'auto',
        display: 'flex',
        alignItems: 'center',
        fontSize: tokens.fontCaption,
        color: tokens.textTertiary,
      }}
    >
      <span>
        {formatDuration(work.duration_s)} · {formatSize(work.size_bytes)}
      </span>
      <button
        type="button"
        title="打开所在文件夹"
        onClick={() => {
          revealInFolder(work.output_path).catch((error: unknown) => {
            message.error(error instanceof Error ? error.message : String(error));
          });
        }}
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          background: 'none',
          border: 'none',
          color: tokens.colorPrimary,
          fontSize: tokens.fontCaption,
          cursor: 'pointer',
          padding: 0,
        }}
      >
        <FolderOpenOutlined />
        文件夹
      </button>
    </div>
  );
}

function WorkCard({
  work,
  cover,
  onPreview,
}: {
  work: WorkItem;
  cover?: string;
  onPreview: () => void;
}): React.ReactElement {
  const tint = modeColor(work.narration_mode);

  return (
    <Card hoverable styles={{ body: { padding: 0, height: '100%' } }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Poster cover={cover} tint={tint} onPreview={onPreview} />
        <div style={{ padding: '12px 14px 14px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Tag
              color={tint}
              style={{ marginInlineEnd: 0, fontSize: tokens.fontMicro, borderRadius: tokens.radiusChip }}
            >
              {modeLabel(work.narration_mode)}
            </Tag>
            <span style={{ marginLeft: 'auto', fontSize: tokens.fontMicro, color: tokens.textTertiary }}>
              {formatDate(work.completed_at)}
            </span>
          </div>
          <div style={{ fontSize: tokens.fontBodyLg, fontWeight: 600, color: tokens.textPrimary }}>
            {work.project_name}
          </div>
          <WorkMeta work={work} />
        </div>
      </div>
    </Card>
  );
}


function Poster({
  cover,
  tint,
  onPreview,
}: {
  cover?: string;
  tint: string;
  onPreview: () => void;
}): React.ReactElement {
  return (
    <div
      onClick={onPreview}
      style={{
        height: 120,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        cursor: 'pointer',
        background: `linear-gradient(135deg, ${tint}26 0%, ${tokens.bgElevated} 100%)`,
        borderTopLeftRadius: 8,
        borderTopRightRadius: 8,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {cover !== undefined && (
        <img
          src={mediaUrl(cover)}
          alt=""
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            opacity: 0.8,
          }}
        />
      )}
      <PlayCircleOutlined
        style={{ fontSize: tokens.fontPoster, color: cover === undefined ? tint : '#FFFFFF', zIndex: 1 }}
      />
      <span style={{ fontSize: tokens.fontCaption, color: '#FFFFFF', zIndex: 1, textShadow: '0 1px 4px rgba(0,0,0,0.6)' }}>
        点击预览
      </span>
    </div>
  );
}
