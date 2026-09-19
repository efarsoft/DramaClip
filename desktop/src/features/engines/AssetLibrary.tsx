/**
 * 资产库：一个域的全部模型，按「引擎已接入 / 待接入 / 外部登记」分区，列表与表格两种视图共用同一批列。
 *
 * 分区取代了原来那行黄字（P2）：未接入引擎的资产照样列，但不给「选为生效」——
 * 判据是后端下发的 engine_ready 与体检结论，前端一处都不写死。登记本读坏了也要明说，
 * 不能把「imported.json 打不开」演成「库里没货」。
 */
import { useState } from 'react';
import type { ReactElement } from 'react';
import { Alert, Button, Empty, Input, Segmented } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import type { ImportRecord, ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { PageSection } from '../../components/layout/PageKit';
import { type Reports, partitionAssets, reportFor } from './assetState';
import type { MachineSpecs } from './machineFit';
import { COLUMNS, GRID } from './assetGrid';
import { AssetRow } from './AssetRow';
import { GroupHead } from './AssetKit';
import { ExternalAssets } from './ExternalAssets';
import { useDownloadSettled } from './useDownloadSettled';

type View = 'list' | 'table';

interface LibraryProps {
  models: readonly ModelInfo[];
  /** 登记本里 model_id 为 null 的那几条：本地有目录，引擎没接。 */
  externals: readonly ImportRecord[];
  /** models.import_records 自己坏了的原话；空串 = 读通了。 */
  importError: string;
  reports: Reports;
  specs: MachineSpecs;
  activeModelId: string | undefined;
  onActivate: (model: ModelInfo) => void;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
  onForget: (path: string) => void;
  onImport: () => void;
  /** 域自带的行内动作（配音域放试听）：资产库不懂各域的事，只负责摆位置。 */
  renderPreview?: ((model: ModelInfo) => ReactElement) | undefined;
}

type GroupProps = Omit<LibraryProps, 'models' | 'externals' | 'importError' | 'onForget' | 'onImport'> & {
  models: readonly ModelInfo[];
  view: View;
};

/** 资产库分区（含工具栏与视图切换）。 */
export function AssetLibrary({
  models,
  externals,
  importError,
  reports,
  specs,
  activeModelId,
  onActivate,
  onChanged,
  onVerify,
  onForget,
  onImport,
  renderPreview,
}: LibraryProps): ReactElement {
  useDownloadSettled(onChanged);
  const [keyword, setKeyword] = useState('');
  const [view, setView] = useState<View>('list');
  const filtered = models.filter((model) => hits(model, keyword));
  const shown = externals.filter((record) => externalHits(record, keyword));
  const { usable, reserve } = partitionAssets(filtered);
  const group = { reports, view, specs, activeModelId, onActivate, onChanged, onVerify, renderPreview };
  return (
    <PageSection
      title="资产库"
      extra={
        <LibraryToolbar
          keyword={keyword}
          view={view}
          onKeyword={setKeyword}
          onView={setView}
          onVerifyAll={onChanged}
          onImport={onImport}
        />
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
        {importError !== '' && <Alert type="warning" showIcon title={importError} />}
        {filtered.length === 0 && shown.length === 0 ? (
          <Empty description="没有符合条件的模型" style={{ padding: tokens.spaceLg }} />
        ) : (
          <>
            <AssetGroup title="可用 · 引擎已接入" models={usable} {...group} />
            <AssetGroup
              title="储备 · 待接入"
              hint="下载备用可以，选为生效不行——合成/识别路径还没接进工厂"
              collapsible
              models={reserve}
              {...group}
            />
          </>
        )}
        <ExternalAssets items={shown} onForget={onForget} />
      </div>
    </PageSection>
  );
}

function hits(model: ModelInfo, keyword: string): boolean {
  const kw = keyword.trim().toLowerCase();
  if (kw === '') return true;
  return (
    model.name.toLowerCase().includes(kw) ||
    model.repo_id.toLowerCase().includes(kw) ||
    (model.desc ?? '').toLowerCase().includes(kw)
  );
}

/** 外部资产没有 repo_id，能对上号的只有登记名与路径。 */
function externalHits(record: ImportRecord, keyword: string): boolean {
  const kw = keyword.trim().toLowerCase();
  if (kw === '') return true;
  return (record.label ?? '').toLowerCase().includes(kw) || record.path.toLowerCase().includes(kw);
}

function LibraryToolbar({
  keyword,
  view,
  onKeyword,
  onView,
  onVerifyAll,
  onImport,
}: {
  keyword: string;
  view: View;
  onKeyword: (value: string) => void;
  onView: (value: View) => void;
  onVerifyAll: () => void;
  onImport: () => void;
}): ReactElement {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
      <Input
        allowClear
        size="small"
        prefix={<SearchOutlined style={{ color: tokens.textTertiary }} />}
        placeholder="搜索模型"
        style={{ width: 180 }}
        value={keyword}
        onChange={(event) => {
          onKeyword(event.target.value);
        }}
      />
      <Segmented
        size="small"
        value={view}
        options={[
          { label: '列表', value: 'list' },
          { label: '表格', value: 'table' },
        ]}
        onChange={(value) => {
          onView(value as View);
        }}
      />
      <Button size="small" onClick={onVerifyAll}>
        批量校验
      </Button>
      <Button size="small" type="primary" onClick={onImport}>
        导入本地模型
      </Button>
    </span>
  );
}

function AssetGroup({
  title,
  hint,
  collapsible = false,
  models,
  reports,
  view,
  specs,
  activeModelId,
  onActivate,
  onChanged,
  onVerify,
  renderPreview,
}: GroupProps & { title: string; hint?: string; collapsible?: boolean }): ReactElement | null {
  const [open, setOpen] = useState(!collapsible);
  if (models.length === 0) return null;
  return (
    <div>
      <GroupHead
        title={title}
        hint={hint}
        count={models.length}
        collapsible={collapsible}
        open={open}
        onToggle={() => {
          setOpen(!open);
        }}
      />
      {open && (
        <AssetList
          models={models}
          view={view}
          reports={reports}
          specs={specs}
          activeModelId={activeModelId}
          onActivate={onActivate}
          onChanged={onChanged}
          onVerify={onVerify}
          renderPreview={renderPreview}
        />
      )}
    </div>
  );
}

function AssetList({
  models,
  view,
  reports,
  specs,
  activeModelId,
  onActivate,
  onChanged,
  onVerify,
  renderPreview,
}: GroupProps): ReactElement {
  const row = (model: ModelInfo, table: boolean) => (
    <AssetRow
      key={model.model_id}
      model={model}
      report={reportFor(reports, model.model_id)}
      specs={specs}
      active={model.model_id === activeModelId}
      onActivate={onActivate}
      onChanged={onChanged}
      onVerify={onVerify}
      preview={renderPreview?.(model)}
      table={table}
    />
  );
  if (view === 'list') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {models.map((model) => row(model, false))}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: GRID,
          gap: tokens.spaceMd,
          padding: `0 ${tokens.spaceMd}`,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        {COLUMNS.map((column) => (
          <span key={column}>{column}</span>
        ))}
      </div>
      {models.map((model) => row(model, true))}
    </div>
  );
}
