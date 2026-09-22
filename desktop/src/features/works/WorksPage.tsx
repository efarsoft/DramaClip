/** 成品库：按剧分组（规格 §4.5）——每部剧一个分区，片单横向滑动，点击进详情。 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntdApp, Card, Empty } from 'antd';
import { FolderOpenOutlined, PlayCircleOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { listWorks, mediaUrl, projectApi, revealInFolder } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO, modeLabel } from '../../components/modeMeta';

/** 模式色板（§3.4）：六枚全部从 tokens 派生，九种模式按序循环取用——色值只在 theme.ts 有一份。 */
const MODE_COLORS = [
  tokens.colorPrimary,
  tokens.colorAccent,
  tokens.colorSuccess,
  tokens.colorWarning,
  tokens.colorError,
  tokens.colorInfo,
] as const;

function modeColor(mode: string | undefined): string {
  if (mode === undefined) return tokens.textTertiary;
  const index = MODE_INFO.findIndex((item) => item.mode === mode);
  return MODE_COLORS[index % MODE_COLORS.length] ?? tokens.colorPrimary;
}

function durationLabel(s: number | undefined): string {
  if (s === undefined || s <= 0) return '';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${String(m)}:${String(sec).padStart(2, '0')}`;
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

/** 按剧分组；剧内按完成时间倒序，剧间按最新成片时间倒序。 */
function groupWorks(works: WorkItem[]): WorkGroup[] {
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
      (a, b) => (b.completed_at ?? b.id.localeCompare(a.id)) - ((a.completed_at ?? 0)),
    );
  }
  return list.sort((a, b) => {
    const aLatest = Math.max(...a.works.map((w) => w.completed_at ?? 0));
    const bLatest = Math.max(...b.works.map((w) => w.completed_at ?? 0));
    return bLatest - aLatest;
  });
}

/** 成品库页（导航「成品」）：按剧分组，剧内片单横向滑动。 */
export function WorksPage() {
  const navigate = useNavigate();
  const serviceState = useUiStore((state) => state.serviceState);
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

  // 服务就绪前 RPC 会失败（首进偶发 -32603 即此因）；ready 后（重）加载一次
  useEffect(() => {
    if (serviceState !== 'ready') return;
    void load().catch(() => undefined);
  }, [load, serviceState]);

  const groups = useMemo<WorkGroup[]>(() => (works === null ? [] : groupWorks(works)), [works]);

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
        <GroupList groups={groups} covers={covers} onOpen={(id) => { void navigate(`/works/${id}`); }} />
      )}
    </PageShell>
  );
}

function GroupList({
  groups,
  covers,
  onOpen,
}: {
  groups: WorkGroup[];
  covers: Map<string, string>;
  onOpen: (exportId: string) => void;
}): React.ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <>
      {groups.map((group) => (
        <PageSection
          key={group.projectId}
          title={group.name}
          extra={<span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>{`${String(group.works.length)} 条`}</span>}
          dense
        >
          <div style={{ display: 'flex', gap: tokens.spaceMd, overflowX: 'auto', paddingBottom: tokens.spaceSm }}>
            {group.works.map((work) => (
              <WorkCard
                key={work.id}
                work={work}
                cover={covers.get(work.project_id) ?? undefined}
                onOpen={() => {
                  onOpen(work.id);
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
      ))}
    </>
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
      <WorkPoster work={work} cover={cover} onFolder={folder} />
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        <span>{formatDate(work.completed_at)}</span>
        <span style={{ marginLeft: 'auto', fontFamily: tokens.fontFamilyMono }}>{formatSize(work.size_bytes)}</span>
      </div>
    </div>
  );
}

function WorkPoster({
  work,
  cover,
  onFolder,
}: {
  work: WorkItem;
  cover?: string;
  onFolder: (event: React.MouseEvent) => void;
}): React.ReactElement {
  const tint = modeColor(work.narration_mode);
  return (
    <div
      className="work-poster"
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
        <PlayCircleOutlined style={{ fontSize: tokens.glyph.poster, color: tint, position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }} />
      )}
      <span
        style={{
          position: 'absolute', inset: 0,
          background: tokens.posterScrim,
        }}
      />
      <PosterBadges work={work} />
      <div className="work-poster-folder">
        <FolderButton onClick={onFolder} />
      </div>
    </div>
  );
}

function PosterBadges({ work }: { work: WorkItem }): React.ReactElement {
  return (
    <>
      <span
        style={{
          position: 'absolute', left: 6, top: 6,
          background: tokens.posterCaption, color: tokens.colorWhite,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading, padding: '1px 6px', borderRadius: tokens.radiusChip,
        }}
      >
        {modeLabel(work.narration_mode)}
      </span>
      <span
        style={{
          position: 'absolute', right: 6, bottom: 6,
          background: tokens.posterCaption, color: tokens.colorWhite,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading, padding: '1px 6px', borderRadius: tokens.radiusChip,
          fontFamily: tokens.fontFamilyMono,
        }}
      >
        {durationLabel(work.duration_s)}
      </span>
    </>
  );
}

function FolderButton({ onClick }: { onClick: (event: React.MouseEvent) => void }): React.ReactElement {
  return (
    <button
      type="button"
      title="打开所在文件夹"
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 4,
        background: 'none', border: 'none', padding: 0,
        color: tokens.colorWhite, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, cursor: 'pointer',
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
  );
}

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
