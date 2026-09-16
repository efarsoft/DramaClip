/** 成品库：跨项目已完成的成片（卡片网格 + 预览 + 定位文件）。 */
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

function durationLabel(s: number | undefined): string {
  if (s === undefined || s <= 0) return '';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '';
  const date = new Date(ms);
  return `${String(date.getMonth() + 1)}/${String(date.getDate())} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/** 成品库页（导航「成品」）。 */
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
        title="成品库"
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: tokens.spaceLg }}>
          {works.map((work) => (
            <WorkCard
              key={work.id}
              work={work}
              cover={work.cover_path ?? covers.get(work.project_id) ?? undefined}
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
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
          gap: tokens.spaceXs,
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
        <Poster work={work} cover={cover} tint={tint} onPreview={onPreview} />
        <div style={{ padding: `${String(tokens.spaceSm)} ${String(tokens.spaceLg)} ${String(tokens.spaceMd)}`, display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, flex: 1 }}>
          <div style={{ fontSize: tokens.fontBodyLg, fontWeight: 600, color: tokens.textPrimary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {work.project_name}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, fontSize: tokens.fontMicro, color: tokens.textTertiary }}>
            <span>{formatDate(work.completed_at)}</span>
            <WorkMeta work={work} />
          </div>
        </div>
      </div>
    </Card>
  );
}


function Poster({
  work,
  cover,
  tint,
  onPreview,
}: {
  work: WorkItem;
  cover?: string;
  tint: string;
  onPreview: () => void;
}): React.ReactElement {
  return (
    <div
      onClick={onPreview}
      style={{
        aspectRatio: '9 / 16',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: tokens.spaceSm,
        cursor: 'pointer',
        background: `linear-gradient(135deg, ${tint}26 0%, ${tokens.bgElevated} 100%)`,
        borderTopLeftRadius: 8,
        borderTopRightRadius: 8,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {cover !== undefined ? (
        <img
          src={mediaUrl(cover)}
          alt=""
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
          }}
        />
      ) : (
        <PlayCircleOutlined
          style={{ fontSize: tokens.fontPoster, color: tint, zIndex: 1 }}
        />
      )}
      <span
        style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, rgba(0,0,0,0) 55%, rgba(0,0,0,0.6) 100%)',
        }}
      />
      <span
        style={{
          position: 'absolute', left: 6, top: 6,
          background: 'rgba(0,0,0,0.72)', color: tokens.colorWhite,
          fontSize: tokens.fontMicro, padding: '1px 6px', borderRadius: tokens.radiusChip,
        }}
      >
        {modeLabel(work.narration_mode)}
      </span>
      <span
        style={{
          position: 'absolute', right: 6, bottom: 6,
          background: 'rgba(0,0,0,0.72)', color: tokens.colorWhite,
          fontSize: tokens.fontMicro, padding: '1px 6px', borderRadius: tokens.radiusChip,
          fontFamily: tokens.fontFamilyMono,
        }}
      >
        {durationLabel(work.duration_s)}
      </span>
    </div>
  );
}
