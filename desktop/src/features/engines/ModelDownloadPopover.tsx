/** 下载源选择按钮：点击弹气泡（选源 + 复制链接 + 开始下载），进度就地显示。 */
import { useState, type ReactElement } from 'react';
import { App as AntdApp, Button, Popover, Radio, Tooltip } from 'antd';
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons';
import type { ModelInfo, ModelSource } from '@dramaclip/protocol';
import { modelsApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
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
    return (
      <Button size="small" disabled style={{ minWidth: 86 }}>
        {downloadingLabel(download)}
      </Button>
    );
  }
  if (download?.status === 'failed') {
    return <RetryDownload model={model} reason={download.message} onChanged={onChanged} />;
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

/** 失败态（附录 B② 根治）：分类原因挂在悬停上，按钮直接给「重试」——名字与动作同权重。 */
function RetryDownload({
  model,
  reason,
  onChanged,
}: {
  model: ModelInfo;
  reason: string;
  onChanged: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <Tooltip title={reason !== '' ? `上次失败：${reason}` : '上次下载失败了'} placement="top">
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
    </Tooltip>
  );
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
