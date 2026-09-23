/** 成品库（09-10 §4.5 定案A + 卷三图5）：按剧分组、组内网格；卡片带四项自检徽章；
 * 批量三件（打开文件夹/复制到/删除入回收）+ 自检筛选 + 历史成片补测。
 * 失败态纪律（意见01）：取不到 ≠ 一直在取——原文上屏 + 真重试，旧数据在手时横幅压顶。 */
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Empty } from 'antd';
import { SafetyCertificateOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { BatchBar } from './BatchBar';
import { PreviewModal } from './PreviewModal';
import { WorkCard } from './WorkCard';
import { useWorksBatch } from './useWorksBatch';
import { useWorksLoad, useWorksPageActions } from './useWorksData';
import { groupWorks, WORKS_FILTERS, type WorkGroup, type WorksFilterKey } from './worksView';

/** 成品库页（导航「成品」）。 */
export function WorksPage(): React.ReactElement {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<WorksFilterKey>('all');
  const [preview, setPreview] = useState<WorkItem | null>(null);
  const { works, error, covers, load } = useWorksLoad(filter);
  const { onSelfcheck, onFolder } = useWorksPageActions();
  const batch = useWorksBatch(works ?? [], () => {
    void load();
  });
  const groups = useMemo<WorkGroup[]>(() => (works === null ? [] : groupWorks(works)), [works]);
  return (
    <PageShell>
      <PageHeader
        title="成品库"
        chip={`共 ${String(works?.length ?? 0)} 个`}
        desc="按剧分组的全部成片：质检挑片、批量整理、追溯回方案"
        actions={
          <Button icon={<SafetyCertificateOutlined />} onClick={onSelfcheck}>
            补测自检
          </Button>
        }
      />
      <FilterRow filter={filter} onChange={setFilter} />
      <FailureBanner error={error} stale={works !== null} onRetry={load} />
      <WorksBody
        works={works}
        error={error}
        filter={filter}
        groups={groups}
        covers={covers}
        selectedIds={batch.selectedIds}
        onOpen={(id) => { void navigate(`/works/${id}`); }}
        onPreview={setPreview}
        onJumpPlan={(work) => { void navigate(`/projects/${work.project_id}/produce?focus=planning`); }}
        onFolder={onFolder}
        onToggleSelect={batch.toggle}
      />
      <BatchBar
        selected={batch.selected}
        actions={{
          onOpenFolders: () => { void batch.openFolders(); },
          onCopyTo: () => { void batch.copyTo(); },
          onDelete: batch.confirmDelete,
          onClear: batch.clear,
        }}
      />
      <PreviewModal work={preview} onClose={() => { setPreview(null); }} />
    </PageShell>
  );
}

/** 加载失败横幅：错误原文不截断；手里还有旧数据时如实标注「可能已过期」。 */
function FailureBanner({
  error,
  stale,
  onRetry,
}: {
  error: string;
  stale: boolean;
  onRetry: () => Promise<void>;
}): React.ReactElement | null {
  if (error === '') return null;
  return (
    <Alert
      type="error"
      showIcon
      title={
        stale
          ? `成品列表刷新失败（下列内容可能已过期）：${error}`
          : `成品列表加载失败：${error}`
      }
      action={
        <Button size="small" onClick={() => { void onRetry(); }}>
          重试
        </Button>
      }
    />
  );
}

/** 自检筛选 chip 行（#30「筛选·自检通过」）：选中态用主色描边+软底，不与勾选铺底抢通道。 */
function FilterRow({
  filter,
  onChange,
}: {
  filter: WorksFilterKey;
  onChange: (key: WorksFilterKey) => void;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center', flexWrap: 'wrap' }}>
      {WORKS_FILTERS.map((item) => {
        const active = item.key === filter;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => { onChange(item.key); }}
            style={{
              ...mixins.chip(),
              cursor: 'pointer',
              background: active ? tokens.accentSoft : tokens.bgElevated,
              color: active ? tokens.colorPrimary : tokens.textSecondary,
              border: `1px solid ${active ? tokens.colorPrimary : 'transparent'}`,
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

interface WorksBodyProps {
  works: WorkItem[] | null;
  error: string;
  filter: WorksFilterKey;
  groups: WorkGroup[];
  covers: Map<string, string>;
  selectedIds: ReadonlySet<string>;
  onOpen: (exportId: string) => void;
  onPreview: (work: WorkItem) => void;
  onJumpPlan: (work: WorkItem) => void;
  onFolder: (work: WorkItem) => void;
  onToggleSelect: (id: string) => void;
}

function WorksBody(props: WorksBodyProps): React.ReactElement {
  const { works, error, filter, groups } = props;
  if (works === null) {
    return error === '' ? <Card loading /> : <Empty description="什么都没取到——先修复上面的错误" />;
  }
  if (groups.length === 0) {
    const label = WORKS_FILTERS.find((item) => item.key === filter)?.label ?? '';
    return (
      <Card>
        <Empty
          description={
            filter === 'all'
              ? '还没有完成的成片——去项目里生成并导出第一个作品吧'
              : `「${label}」筛选下没有成片${filter === 'unchecked' ? '（全部都已自检）' : ''}`
          }
        />
      </Card>
    );
  }
  return <GroupGrid {...props} />;
}

function GroupGrid({
  groups,
  covers,
  selectedIds,
  onOpen,
  onPreview,
  onJumpPlan,
  onFolder,
  onToggleSelect,
}: WorksBodyProps): React.ReactElement {
  return (
    <>
      {groups.map((group) => (
        <PageSection
          key={group.projectId}
          title={group.name}
          extra={
            <span
              style={{
                fontSize: tokens.text.badge.size,
                lineHeight: tokens.text.badge.leading,
                color: tokens.textTertiary,
              }}
            >
              {`${String(group.works.length)} 条`}
            </span>
          }
          dense
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
              gap: tokens.spaceLg,
              padding: tokens.spaceLg,
            }}
          >
            {group.works.map((work) => (
              <WorkCard
                key={work.id}
                work={work}
                projectCover={covers.get(work.project_id)}
                selected={selectedIds.has(work.id)}
                actions={{
                  onOpen: () => { onOpen(work.id); },
                  onPreview: () => { onPreview(work); },
                  onJumpPlan: () => { onJumpPlan(work); },
                  onFolder: () => { onFolder(work); },
                  onToggleSelect: () => { onToggleSelect(work.id); },
                }}
              />
            ))}
          </div>
        </PageSection>
      ))}
    </>
  );
}
