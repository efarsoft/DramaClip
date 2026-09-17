/** 成品库：按剧分组（规格 §4.5）——每部剧一个分区，片单横向滑动，点击进详情。 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntdApp, Card, Empty } from 'antd';
import { FolderOpenOutlined, PlayCircleOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { listWorks, mediaUrl, projectApi, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';

const MODE_COLORS = ['#7C9CFF', '#9B7BFF', '#34D399', '#FBBF24', '#F87171', '#60A5FA'];

function modeLabel(mode: string | undefined): string {
  if (mode === undefined) return '成片';
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode;
}

function modeColor(mode: string | undefined): string {
  if (mode === undefined) return tokens.textTertiary;
  const index = MODE_INFO.findIndex((item) => item.mode === mode);
  return MODE_COLORS[index % MODE_COLORS.length] ?? tokens.colorPrimary;
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
  return `${String(date.getMonth() + 1)}/${String(date.getDate())}`;
}

interface WorkGroup {
  readonly projectId: string;
  readonly name: string;
  readonly works: WorkItem[];
}

/** 成品库页（导航「成品」）：按剧分组，剧内片单横向滑动。 */
export function WorksPage() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [works, setWorks] = useState<WorkItem[] | null>(null);
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

  const groups = useMemo<WorkGroup[]>(() => {
    if (works === null) return [];
    const map = new Map<string, WorkGroup>();
    for (const work of works) {
      const group = map.get(work.project_id) ?? {
        projectId: work.project_id,
        name: work.project_name,
        works: [],
      };
      group.works.push(work);
      map.set(work.project_id, group);
    }
    const list = [...map.values()];
    for (const group of list) {
      group.works.sort(
        (a, b) => (b.completed_at ?? b.id.localeCompare(a.id)) as number - ((a.completed_at ?? 0) as number),
      );
    }
    return list.sort((a, b) => {
      const aLatest = Math.max(...a.works.map((w) => w.completed_at ?? 0));
      const bLatest = Math.max(...b.works.map((w) => w.completed_at ?? 0));
      return bLatest - aLatest;
    });
  }, [works]);

  const total = works?.length ?? 0;

  return (
    <PageShell>
      <PageHeader
        title="成品库"
        chip={`共 ${String(total)} 个`}
        desc="按剧分组的全部成片；点击卡片查看详情、文案与候选标题"
      />

      {works === null ? (
        <Card loading />
      ) : groups.length === 0 ? (
        <Card>
          <Empty description="还没有完成的成片——去项目里生成并导出第一个作品吧" />
        </Card>
      ) : (
        groups.map((group) => (
          <PageSection
            key={group.projectId}
            title={group.name}
            extra={<span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{`${String(group.works.length)} 条`}</span>}
            dense
          >
            <div style={{ display: 'flex', gap: tokens.spaceMd, overflowX: 'auto', paddingBottom: tokens.spaceSm }}>
              {group.works.map((work) => (
                <WorkCard
                  key={work.id}
                  work={work}
                  cover={covers.get(work.project_id) ?? undefined}
                  onOpen={() => {
                    void navigate(`/works/${work.id}`);
                  }}
                  onFolder={async () => {
                    try {
                      await revealInFolder(work.output_path);
                    } catch (error: unknown) {
                      message.error(error instanceof Error ? error.message : String(error));
                    }
                  }}
                />
              ))}
            </div>
          </PageSection>
        ))
      )}
    </PageShell>
  );
}

function WorkCard({
  work,
  cover,
  onOpen,
  onFolder,
}: {
  work: WorkItem;
  cover?: string;
  onOpen: () => void;
  onFolder: () => Promise<void>;
}): React.ReactElement {
  const { message } = AntdApp.useApp();
  const tint = modeColor(work.narration_mode);

  const folder = (event: React.MouseEvent): void => {
    event.stopPropagation();
    void onFolder().catch((error: unknown) => {
      message.error(error instanceof Error ? error.message : String(error));
    });
  };

  return (
    <div
      onClick={() => {
        onOpen();
      }}
      style={{ width: 150, flexShrink: 0, cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}
    >
      <div
        style={{
          position: 'relative',
          aspectRatio: '9 / 16',
          borderRadius: tokens.radiusCard,
          overflow: 'hidden',
          background: tokens.bgElevated,
          border: `1px solid ${tokens.borderSecondary}`,
        }}
      >
        {cover !== undefined ? (
          <img
            src={mediaUrl(cover)}
            alt=""
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <PlayCircleOutlined style={{ fontSize: 28, color: tint, position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }} />
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
        <button
          type="button"
          title="打开所在文件夹"
          onClick={folder}
          style={{
            position: 'absolute', left: 6, bottom: 6,
            display: 'flex', alignItems: 'center', gap: 4,
            background: 'none', border: 'none', padding: 0,
            color: tokens.colorWhite, fontSize: tokens.fontMicro, cursor: 'pointer',
          }}
          onMouseEnter={(event) => {
            event.currentTarget.style.color = tokens.colorPrimary;
          }}
          onMouseLeave={(event) => {
            event.currentTarget.style.color = tokens.colorWhite;
          }}
        >
          <FolderOpenOutlined />
          打开文件夹
        </button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, fontSize: tokens.fontMicro, color: tokens.textTertiary }}>
        <span>{formatDate(work.completed_at)}</span>
        <span style={{ marginLeft: 'auto', fontFamily: tokens.fontFamilyMono }}>{formatSize(work.size_bytes)}</span>
      </div>
    </div>
  );
}

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
