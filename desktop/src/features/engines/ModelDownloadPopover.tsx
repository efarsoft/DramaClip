/** 下载源选择按钮：点击弹气泡（选源 + 复制链接 + 开始下载），进度就地显示。 */
import { useState, type ReactElement } from 'react';
import { App as AntdApp, Button, Popover, Radio } from 'antd';
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons';
import type { ModelInfo, ModelSource } from '@dramaclip/protocol';
import { jobsApi, modelsApi } from '../../services/client';
import { type ModelDownloadState, useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';
import { downloadingLabel } from './downloadLabel';
import { errorText } from './errorText';

const SOURCE_META: Record<string, { label: string; hint: string }> = {
  modelscope: { label: 'ModelScope（国内）', hint: '国内 CDN，速度最快，推荐' },
  hf_mirror: { label: '国内镜像（更快）', hint: 'HuggingFace 镜像站，通常无需网络加速' },
  huggingface: { label: 'HF 官方源', hint: '官方源，可能需要网络加速' },
};

function sourceLabel(kind: string): string {
  return SOURCE_META[kind]?.label ?? kind;
}

/** 下载按钮：单源直接下，多源弹选择气泡；下载中显示进度三件套；失败给原因 + 重试。 */
export function DownloadSourceButton({
  model,
  onChanged,
}: {
  model: ModelInfo;
  onChanged: () => void;
}): ReactElement {
  const download = useUiStore((state) => state.modelDownloads[model.model_id]);
  const sources: readonly ModelSource[] = model.sources ?? [];
  const [open, setOpen] = useState(false);
  if (download?.status === 'downloading') {
    return <CancelDownload model={model} download={download} onChanged={onChanged} />;
  }
  if (download?.status === 'failed') {
    return <RetryDownload model={model} onChanged={onChanged} />;
  }
  if (sources.length === 0) {
    return <DirectDownload model={model} onChanged={onChanged} />;
  }
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomRight"
      content={<SourcePicker model={model} sources={sources} onPicked={() => { setOpen(false); }} />}
    >
      <Button size="small" type="primary" icon={<DownloadOutlined />}>
        下载
      </Button>
    </Popover>
  );
}

/**
 * 失败态（附录 B②）：这里只留「重试」这个动作。原因原文由宿主行写进**可见文本**
 * （资产行的状态列、生效卡的状态行，都出自 `downloadFailureNote`）——悬停要鼠标配合，
 * 一次性 toast 会自己消失，两者都不是账（规格 H3 §3.1.2）。
 */
function RetryDownload({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <Button
      size="small"
      danger
      icon={<DownloadOutlined />}
      onClick={() => {
        launch(message, model, undefined, onChanged);
      }}
    >
      重试
    </Button>
  );
}

/**
 * 下载中：进度三件套 + 取消（`RepairActions` 的强制重下话术早就承诺「下载中可取消」，
 * 这一版把入口补上）。作业 id 不在进度事件里（服务端不下发），刷新后 store 里也没有——
 * 所以按「进行中的 model_download 且 ref_id=本模型」现查，页面刷过之后取消照样能用。
 */
function CancelDownload({
  model,
  download,
  onChanged,
}: {
  model: ModelInfo;
  download: ModelDownloadState;
  onChanged: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const clearModelDownload = useUiStore((state) => state.clearModelDownload);
  const [busy, setBusy] = useState(false);
  const cancel = (): void => {
    setBusy(true);
    void requestCancel(model.model_id)
      .then((outcome) => {
        if (outcome.kind === 'blocked') {
          message.warning(`取消没生效：${outcome.reason}`);
          return;
        }
        // 服务端不为「已取消」补发进度事件（结局只写进作业账），销账只能在这里做——
        // 留着那条 downloading 就是永久假「下载中」；查不到在跑的作业同样是过期账。
        clearModelDownload(model.model_id);
        onChanged();
        message.info(
          outcome.kind === 'cancelled'
            ? `${model.name}：已取消下载，半成品留在原地，重试可续传`
            : '服务端已经没有进行中的下载任务，这条进度是过期账，已就地销掉',
        );
      })
      .catch((error: unknown) => {
        message.error(errorText(error, '取消请求失败'));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceSm }}>
      <Button size="small" disabled style={{ minWidth: 86 }}>
        {downloadingLabel(download)}
      </Button>
      <Button size="small" loading={busy} onClick={cancel}>
        取消
      </Button>
    </span>
  );
}

type CancelOutcome = { kind: 'cancelled' } | { kind: 'gone' } | { kind: 'blocked'; reason: string };

async function requestCancel(modelId: string): Promise<CancelOutcome> {
  const { jobs } = await jobsApi.list(50, true);
  const job = jobs.find((item) => item.type === 'model_download' && item.ref_id === modelId);
  if (job === undefined) return { kind: 'gone' };
  const result = await jobsApi.cancel(job.id);
  if (!result.cancelling) return { kind: 'blocked', reason: result.reason ?? '服务端未给出原因' };
  return { kind: 'cancelled' };
}

function DirectDownload({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <Button
      size="small"
      type="primary"
      icon={<DownloadOutlined />}
      onClick={() => {
        launch(message, model, undefined, onChanged);
      }}
    >
      下载
    </Button>
  );
}

function SourcePicker({
  model,
  sources,
  onPicked,
}: {
  model: ModelInfo;
  sources: readonly ModelSource[];
  onPicked: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [kind, setKind] = useState(() => sources[0]?.kind ?? '');
  const selected = sources.find((item) => item.kind === kind) ?? sources[0];
  if (selected === undefined) {
    return <DirectDownload model={model} onChanged={() => undefined} />;
  }
  return (
    <div style={{ width: 264, display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
      <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontWeight: 600, color: tokens.textSecondary }}>下载源</div>
      <SourceOptions sources={sources} kind={selected.kind} onPick={setKind} />
      <div style={{ display: 'flex', gap: tokens.spaceSm }}>
        <Button
          size="small"
          icon={<CopyOutlined />}
          style={{ flex: 1 }}
          onClick={() => {
            void navigator.clipboard.writeText(selected.web_url).then(() => {
              message.success('已复制下载页链接');
            });
          }}
        >
          复制链接
        </Button>
        <Button
          size="small"
          type="primary"
          icon={<DownloadOutlined />}
          style={{ flex: 1 }}
          onClick={() => {
            onPicked();
            launch(message, model, selected.kind, () => undefined);
          }}
        >
          开始下载
        </Button>
      </div>
    </div>
  );
}

function SourceOptions({
  sources,
  kind,
  onPick,
}: {
  sources: readonly ModelSource[];
  kind: string;
  onPick: (kind: string) => void;
}): ReactElement {
  return (
    <Radio.Group
      value={kind}
      onChange={(event) => {
        onPick(String(event.target.value));
      }}
      style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}
    >
      {sources.map((item) => (
        <Radio key={item.kind} value={item.kind} style={{ alignItems: 'flex-start' }}>
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textPrimary }}>
            {sourceLabel(item.kind)}
          </span>
          <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
            {SOURCE_META[item.kind]?.hint ?? ''}
          </div>
        </Radio>
      ))}
    </Radio.Group>
  );
}

interface MessageApi { success: (text: string) => void; error: (text: string) => void }

function launch(
  message: MessageApi,
  model: ModelInfo,
  source: string | undefined,
  onChanged: () => void,
): void {
  message.success(`开始下载 ${model.name}，完成后自动检测`);
  modelsApi
    .download(model.model_id, source)
    .then(onChanged)
    .catch((error: unknown) => {
      // 串行闸与磁盘预算的拒绝原话（「已有下载任务进行中…」「磁盘空间不足…」）必须上屏
      message.error(errorText(error, '下载任务创建失败'));
    });
}
