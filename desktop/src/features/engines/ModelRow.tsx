/** 引擎模型行（本地模型：下载/删除/打开目录）。 */
import { Button, Card, Tag } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';

const noop = (): void => undefined;

export function ModelRow({
  model,
  recommended = false,
  onChanged,
}: {
  model: ModelInfo;
  recommended?: boolean;
  onChanged: () => void;
}): ReactElement {
  const installed = model.status === 'installed';
  const actions = buildActions(model, installed, onChanged);
  return (
    <Card size="small" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <strong style={{ color: tokens.textPrimary, fontSize: 13.5 }}>{model.name}</strong>
        <Tag color={installed ? 'success' : 'default'} style={{ marginRight: 0 }}>
          {installed ? '已安装' : '未安装'}
        </Tag>
        {recommended && <Tag color="blue" style={{ marginRight: 0 }}>推荐</Tag>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>{actions}</span>
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: tokens.textTertiary, display: 'flex', gap: 16 }}>
        <span>仓库：{model.repo_id}</span>
        {model.notes !== '' && <span>{model.notes}</span>}
      </div>
    </Card>
  );
}

function buildActions(
  model: ModelInfo,
  installed: boolean,
  onChanged: () => void,
): ReactElement[] {
  const list: ReactElement[] = [];
  if (!installed) list.push(downloadAction(model, onChanged));
  list.push(refreshAction(onChanged));
  if (installed && model.path !== undefined) list.push(openAction(model.path));
  if (installed) list.push(deleteAction(model, onChanged));
  return list;
}

function downloadAction(model: ModelInfo, onChanged: () => void): ReactElement {
  return (
    <Button
      size="small"
      type="primary"
      onClick={() => {
        modelsApi.download(model.model_id).then(onChanged).catch(noop);
      }}
    >
      在线下载
    </Button>
  );
}

function refreshAction(onChanged: () => void): ReactElement {
  return (
    <Button
      size="small"
      onClick={() => {
        modelsApi.scanLocal().then(onChanged).catch(noop);
      }}
    >
      刷新
    </Button>
  );
}

function openAction(path: string): ReactElement {
  return (
    <Button
      size="small"
      onClick={() => {
        void revealInFolder(path);
      }}
    >
      打开目录
    </Button>
  );
}

function deleteAction(model: ModelInfo, onChanged: () => void): ReactElement {
  return (
    <Button
      size="small"
      danger
      onClick={() => {
        modelsApi.remove(model.model_id).then(onChanged).catch(noop);
      }}
    >
      删除
    </Button>
  );
}
