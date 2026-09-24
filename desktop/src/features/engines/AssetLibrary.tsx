/**
 * 资产库：一个域的全部模型，按「引擎已接入 / 待接入 / 外部登记」分区。
 * 未接入的资产照样列，但不给「选为生效」——判据是后端的 engine_ready 与体检结论，前端不写死。
 * 登记本读坏了要明说（importError），不能把「imported.json 打不开」演成「库里没货」。
 */
import { useState } from 'react';
import type { ReactElement } from 'react';
import { Alert, Button, Empty, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import type { ImportRecord, ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { PageSection } from '../../components/layout/PageKit';
import { type Reports, partitionAssets, reportFor } from './assetState';
import type { MachineSpecs } from './machineFit';
import { AssetRow } from './AssetRow';
import { GroupHead } from './AssetKit';
import { ExternalAssets } from './ExternalAssets';
import { useDownloadSettled } from './useDownloadSettled';

interface LibraryProps {
  models: readonly ModelInfo[];
  /** 登记本里 model_id 为 null 的那几条：本地有目录，引擎没接。 */
  externals: readonly ImportRecord[];
  /** models.import_records 自己坏了的原话；空串 = 读通了。 */
  importError: string;
  reports: Reports;
  /** 自检账本（engines.selftest_results）：就绪口径的能力层那一半。 */
  selftests?: SelftestResults;
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
};

/** 资产库分区（含工具栏）。 */
export function AssetLibrary({
  models,
  externals,
  importError,
  reports,
  selftests,
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
  const filtered = models.filter((model) => hits(model, keyword));
  const shown = externals.filter((record) => externalHits(record, keyword));
  const { usable, reserve } = partitionAssets(filtered);
  const group = { reports, selftests, specs, activeModelId, onActivate, onChanged, onVerify, renderPreview };
  return (
    <PageSection
      title="资产库"
      extra={
        <LibraryToolbar
          keyword={keyword}
          onKeyword={setKeyword}
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
              hint="下载备用可以，选为生效不行——合成/识别路径还没接进工厂。接入后各自进对应模式（如 IndexTTS2 → 音色克隆配音）；时间不预先承诺，界面不说没证的话"
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
  onKeyword,
  onVerifyAll,
  onImport,
}: {
  keyword: string;
  onKeyword: (value: string) => void;
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
  selftests,
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
          {models.map((model) => (
            <AssetRow
              key={model.model_id}
              model={model}
              report={reportFor(reports, model.model_id)}
              selftest={selftests?.[model.model_id]}
              specs={specs}
              active={model.model_id === activeModelId}
              onActivate={onActivate}
              onChanged={onChanged}
              onVerify={onVerify}
              preview={renderPreview?.(model)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
