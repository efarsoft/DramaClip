import { Alert, Button, Card } from 'antd';
import { useState } from 'react';
import type { Project } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { countByFilter, type MatrixFilter, type MatrixRow } from '../home/matrixRows';
import { DramaCard } from './DramaCard';
import { FirstRunEmpty } from './FirstRunEmpty';
import { applyQuery, buildLibraryRows, type LibraryQuery } from './libraryRows';
import { LibraryToolbar } from './LibraryToolbar';
import type { LibraryFacts } from './useLibraryFacts';

/** 剧库主体：失败横幅 > 首启三步 > 工具条 + 五要素卡网格（卷三图 2）。 */
const INITIAL_QUERY: LibraryQuery = { filter: 'all', search: '', sort: 'activity' };

export interface LibraryGridProps {
  projects: Project[] | null;
  loadError: string | null;
  facts: LibraryFacts;
  onRetry: () => void;
  onRetryFacts: () => void;
  onOpen: (project: Project) => void;
  onGoto: (route: string, project: Project) => void;
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
  onCreate: () => void;
}

export function LibraryGrid(props: LibraryGridProps): React.ReactElement {
  const [query, setQuery] = useState<LibraryQuery>(INITIAL_QUERY);
  const { projects, loadError } = props;
  // 失败态优先于一切：原文上屏 + 真重试按钮。已有旧数据时横幅压顶、网格保留（数据旧但可看）。
  const banner =
    loadError !== null ? (
      <Alert
        type="error"
        showIcon
        title={`项目列表加载失败：${loadError}`}
        description={projects === null ? '取到列表之前这里无法渲染；重试会重新拉取。' : '显示的是上一次取到的列表，可能已过期；重试会重新拉取。'}
        action={
          <Button size="small" danger onClick={props.onRetry}>
            重试
          </Button>
        }
      />
    ) : undefined;
  if (projects === null) {
    return loadError !== null ? <div>{banner}</div> : <Card loading />;
  }
  if (projects.length === 0 && loadError === null) {
    return <FirstRunEmpty onCreate={props.onCreate} />;
  }
  return <LibraryBody {...props} projects={projects} banner={banner} query={query} setQuery={setQuery} />;
}

function LibraryBody({
  projects,
  facts,
  banner,
  query,
  setQuery,
  onRetryFacts,
  onOpen,
  onGoto,
  onRename,
  onDuplicate,
  onDelete,
}: LibraryGridProps & {
  projects: Project[];
  banner: React.ReactElement | undefined;
  query: LibraryQuery;
  setQuery: (next: LibraryQuery) => void;
}): React.ReactElement {
  const { rows, factsMissing } = buildLibraryRows(projects, facts);
  const shown = applyQuery(rows, query);
  const counts = {
    all: countByFilter(rows, 'all'),
    running: countByFilter(rows, 'running'),
    failed: countByFilter(rows, 'failed'),
    shipped: countByFilter(rows, 'shipped'),
  } satisfies Record<MatrixFilter, number>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      {banner}
      {facts.factsError !== null && <FactsBanner error={facts.factsError} onRetry={onRetryFacts} />}
      <LibraryToolbar query={query} counts={counts} onChange={setQuery} />
      {shown.length === 0 ? (
        <div style={emptyHintStyle()}>没有符合筛选或搜索的剧</div>
      ) : (
        <CardGrid
          rows={shown}
          factsMissing={factsMissing}
          onOpen={onOpen}
          onGoto={onGoto}
          onRename={onRename}
          onDuplicate={onDuplicate}
          onDelete={onDelete}
        />
      )}
    </div>
  );
}

/** 缺账横幅：说清哪本账缺了、界面因此灰到什么程度、重试拉什么（宁灰勿假绿的话要说出口）。 */
function FactsBanner({ error, onRetry }: { error: string; onRetry: () => void }): React.ReactElement {
  return (
    <Alert
      type="warning"
      showIcon
      title="成品与任务账取不到：卡片阶段灯点灰"
      description={`${error}。列表照常可用；重试会重新拉取两本账。`}
      action={
        <Button size="small" onClick={onRetry}>
          重试
        </Button>
      }
    />
  );
}

function CardGrid({
  rows,
  factsMissing,
  onOpen,
  onGoto,
  onRename,
  onDuplicate,
  onDelete,
}: {
  rows: readonly MatrixRow[];
  factsMissing: boolean;
  onOpen: (project: Project) => void;
  onGoto: (route: string, project: Project) => void;
  onRename: (project: Project) => void;
  onDuplicate: (project: Project) => void;
  onDelete: (project: Project) => void;
}): React.ReactElement {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(236px, 1fr))', gap: tokens.spaceLg }}>
      {rows.map((row) => (
        <DramaCard
          key={row.project.id}
          row={row}
          factsMissing={factsMissing}
          onOpen={onOpen}
          onGoto={onGoto}
          onRename={onRename}
          onDuplicate={onDuplicate}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

/** 空筛选结果的占位框：虚线边框 + 居中一句话，不是一片白板。 */
function emptyHintStyle(): React.CSSProperties {
  return {
    padding: tokens.spaceLg,
    fontSize: tokens.text.meta.size,
    lineHeight: tokens.text.meta.leading,
    textAlign: 'center',
    color: tokens.textTertiary,
    border: `1px dashed ${tokens.borderSecondary}`,
    borderRadius: tokens.radiusCard,
  };
}
