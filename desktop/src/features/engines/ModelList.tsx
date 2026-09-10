/** 模型分组列表：档位分组 + 模型行（速度/精度评级、下载源气泡/目录/删除）。 */
import { useEffect, useRef, type ReactElement } from 'react';
import { App as AntdApp, Button, Empty, Popconfirm } from 'antd';
import { DeleteOutlined, FolderOpenOutlined } from '@ant-design/icons';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi, revealInFolder } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { DownloadSourceButton } from './ModelDownloadPopover';

interface TierSpec {
  readonly key: string;
  readonly label: string;
  readonly hint: string;
}

const TIERS: readonly TierSpec[] = [
  { key: 'fast', label: '快速档', hint: '速度优先，适合快速试效果' },
  { key: 'balanced', label: '均衡档', hint: '日常推荐，速度与准确度兼顾' },
  { key: 'accurate', label: '高精度档', hint: '准确度优先，对电脑配置要求更高' },
];

/** 档位分组列表（无工具栏）。 */
export function ModelList({
  models,
  onChanged,
}: {
  models: readonly ModelInfo[];
  onChanged: () => void;
}): ReactElement {
  useDownloadSettled(onChanged);
  if (models.length === 0) {
    return <Empty description="没有符合条件的模型" style={{ padding: tokens.spaceLg }} />;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      {TIERS.map((tier) => (
        <TierGroup key={tier.key} tier={tier} models={models} onChanged={onChanged} />
      ))}
      <TierGroup tier={{ key: '', label: '其他', hint: '' }} models={models} onChanged={onChanged} />
    </div>
  );
}

function TierGroup({
  tier,
  models,
  onChanged,
}: {
  tier: TierSpec;
  models: readonly ModelInfo[];
  onChanged: () => void;
}): ReactElement | null {
  const group = models.filter((m) => (m.tier ?? '') === tier.key);
  if (group.length === 0) return null;
  return (
    <div>
      <div
        style={{ display: 'flex', alignItems: 'baseline', gap: tokens.spaceSm, margin: `0 2px ${String(tokens.spaceSm)}` }}
      >
        <span style={{ fontSize: tokens.fontCaption, fontWeight: 600, color: tokens.textSecondary }}>
          {tier.label}
        </span>
        {tier.hint !== '' && (
          <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{tier.hint}</span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {group.map((model) => (
          <ModelRow key={model.model_id} model={model} onChanged={onChanged} />
        ))}
      </div>
    </div>
  );
}

function ModelRow({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const installed = model.status === 'installed';
  const path = model.path;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${String(tokens.spaceSm)} ${String(tokens.spaceMd)}`,
        borderRadius: tokens.radiusControl,
        border: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
      }}
    >
      <span style={mixins.statusDot(installed ? tokens.colorSuccess : tokens.textTertiary)} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>
          {model.name}
        </span>
        <span
          style={{
            marginLeft: tokens.spaceSm,
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {model.desc ?? model.repo_id}
        </span>
      </div>
      {(model.speed ?? 0) > 0 && <RatingDots label="速度" level={model.speed ?? 0} />}
      {(model.quality ?? 0) > 0 && <RatingDots label="精度" level={model.quality ?? 0} />}
      {model.size_label !== undefined && <span style={mixins.chip()}>{model.size_label}</span>}
      <span
        style={{
          fontSize: tokens.fontMicro,
          color: installed ? tokens.colorSuccess : tokens.textTertiary,
          flexShrink: 0,
        }}
      >
        {installed ? '已安装' : '未安装'}
      </span>
      <RowActions model={model} installed={installed} path={path} onChanged={onChanged} />
    </div>
  );
}

function RatingDots({ label, level }: { label: string; level: number }): ReactElement {
  return (
    <span
      style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}
      title={`${label} ${String(level)}/5`}
    >
      <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{label}</span>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: tokens.radiusDot,
            background: i <= level ? tokens.colorPrimary : tokens.border,
          }}
        />
      ))}
    </span>
  );
}

function DownloadButton({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  return <DownloadSourceButton model={model} onChanged={onChanged} />;
}

/** 下载结束（完成/失败）时提示并刷新列表（进度事件只到达一次）。 */function useDownloadSettled(onChanged: () => void): void {
  const { message } = AntdApp.useApp();
  const downloads = useUiStore((state) => state.modelDownloads);
  const seen = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const [modelId, state] of Object.entries(downloads)) {
      if (state.status === 'downloading' || seen.current.has(modelId)) continue;
      seen.current.add(modelId);
      if (state.status === 'done') {
        message.success('模型下载完成');
      } else {
        message.error('模型下载失败，可重试或手动导入');
      }
      onChanged();
    }
  }, [downloads, message, onChanged]);
}

function RowActions({
  model,
  installed,
  path,
  onChanged,
}: {
  model: ModelInfo;
  installed: boolean;
  path: string | undefined;
  onChanged: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  if (!installed) return <DownloadButton model={model} onChanged={onChanged} />;
  return (
    <span style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
      {path !== undefined && (
        <Button
          size="small"
          icon={<FolderOpenOutlined />}
          onClick={() => {
            void revealInFolder(path);
          }}
        >
          目录
        </Button>
      )}
      <Popconfirm
        title="删除模型"
        description="删除后可随时重新下载。"
        okText="删除"
        cancelText="取消"
        onConfirm={() => {
          modelsApi
            .remove(model.model_id)
            .then(onChanged)
            .catch(() => {
              message.error('删除失败');
            });
        }}
      >
        <Button size="small" danger icon={<DeleteOutlined />} />
      </Popconfirm>
    </span>
  );
}
