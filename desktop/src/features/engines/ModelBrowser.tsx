/** 模型浏览器（SmartSub 式）：推荐卡 + 搜索/只看已安装 + 档位分组列表。 */
import { useState, type ReactElement } from 'react';
import { App as AntdApp, Button, Input, Switch, Tag } from 'antd';
import { ReloadOutlined, SearchOutlined, StarFilled } from '@ant-design/icons';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { ModelList } from './ModelList';
import { DownloadSourceButton } from './ModelDownloadPopover';

/** 完整浏览器：推荐卡 + 工具栏 + 分组列表。 */
export function ModelBrowser({
  models,
  onChanged,
}: {
  models: readonly ModelInfo[];
  onChanged: () => void;
}): ReactElement {
  const [keyword, setKeyword] = useState('');
  const [installedOnly, setInstalledOnly] = useState(false);
  const kw = keyword.trim().toLowerCase();
  const filtered = models.filter((m) => {
    if (installedOnly && m.status !== 'installed') return false;
    if (kw === '') return true;
    return (
      m.name.toLowerCase().includes(kw) ||
      m.repo_id.toLowerCase().includes(kw) ||
      (m.desc ?? '').toLowerCase().includes(kw)
    );
  });
  const recommended = pickRecommended(models);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      {recommended !== null && <RecommendCard model={recommended} onChanged={onChanged} />}
      <BrowserToolbar
        keyword={keyword}
        onKeyword={setKeyword}
        installedOnly={installedOnly}
        onInstalledOnly={setInstalledOnly}
        onChanged={onChanged}
      />
      <ModelList models={filtered} onChanged={onChanged} />
    </div>
  );
}

/** 推荐卡：「为这台电脑推荐」+ 一键下载（SmartSub 式入口）。 */
function RecommendCard({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const installed = model.status === 'installed';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.border}`,
        background: tokens.accentSoft,
      }}
    >
      <StarFilled style={{ color: tokens.colorWarning, fontSize: tokens.fontTitleLg }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>
          为这台电脑推荐 · {model.name}
        </div>
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>
          {model.desc ?? ''}
          {model.size_label !== undefined ? ` · ${model.size_label}` : ''}
        </div>
      </div>
      {installed ? (
        <Tag color="success" style={{ marginRight: 0 }}>
          已就绪
        </Tag>
      ) : (
        <DownloadSourceButton model={model} onChanged={onChanged} />
      )}
    </div>
  );
}

function BrowserToolbar({
  keyword,
  onKeyword,
  installedOnly,
  onInstalledOnly,
  onChanged,
}: {
  keyword: string;
  onKeyword: (value: string) => void;
  installedOnly: boolean;
  onInstalledOnly: (value: boolean) => void;
  onChanged: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
      <Input
        allowClear
        size="small"
        prefix={<SearchOutlined style={{ color: tokens.textTertiary }} />}
        placeholder="搜索模型名称 / 描述"
        style={{ width: 240 }}
        value={keyword}
        onChange={(event) => {
          onKeyword(event.target.value);
        }}
      />
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>只看已安装</span>
      <Switch size="small" checked={installedOnly} onChange={onInstalledOnly} />
      <Button
        size="small"
        type="text"
        icon={<ReloadOutlined />}
        style={{ marginLeft: 'auto' }}
        onClick={() => {
          modelsApi
            .scanLocal()
            .then(() => {
              message.success('已重新检测本地模型');
              onChanged();
            })
            .catch(() => {
              message.error('检测失败');
            });
        }}
      >
        重新检测
      </Button>
    </div>
  );
}

/** 推荐策略：均衡档优先（CPU 环境），缺则候选第一个。 */
function pickRecommended(models: readonly ModelInfo[]): ModelInfo | null {
  const candidates = models.filter((m) => (m.tier ?? '') !== '');
  const balanced = candidates.find((m) => m.tier === 'balanced');
  const pick = balanced ?? candidates[0];
  return pick ?? null;
}
