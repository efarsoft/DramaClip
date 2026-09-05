import { Button, Card, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { rpc, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';

/** 模型管理页（docs/desktop/03 §7.8 W10 版）：清单状态 + 下载/删除 + 手动导入说明（一等能力）。 */
export function ModelsPage() {
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const load = useCallback(async () => {
    setModels(await rpc<ModelInfo[]>('models.list'));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const scan = async (): Promise<void> => {
    await rpc('models.scan_local', {});
    await load();
  };

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <header style={{ display: 'flex', alignItems: 'center' }}>
        <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>模型管理</h1>
        <span style={{ marginLeft: 16, fontSize: 13, color: tokens.textSecondary }}>
          已安装 {String((models ?? []).filter((m) => m.status === 'installed').length)} 个
        </span>
        <Button style={{ marginLeft: 'auto' }} onClick={() => void scan()}>
          扫描本地模型
        </Button>
      </header>
      <ManualImportCard />
      {models === null ? (
        <Card loading />
      ) : (
        models.map((model) => (
          <ModelRow
            key={model.model_id}
            model={model}
            onChanged={() => {
              void load();
            }}
          />
        ))
      )}
    </div>
  );
}

function ManualImportCard() {
  return (
    <Card size="small" type="inner" title="手动导入（推荐：网络不佳时的正道）">
      <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: tokens.textSecondary, lineHeight: '24px' }}>
        <li>
          浏览器打开模型仓库（ModelScope 优先）：
          <code style={{ color: tokens.colorPrimary }}> modelscope.cn/models/{'{仓库id}'}</code>
        </li>
        <li>下载仓库全部文件（通常含 model.bin / config.json 等）</li>
        <li>
          放入对应目录：
          <code style={{ color: tokens.colorPrimary }}>{'{数据目录}\\models\\{放置目录}'}</code>
          （各行的"放置目录"见模型卡片）
        </li>
        <li>回到本页点击「扫描本地模型」即生效</li>
      </ol>
    </Card>
  );
}

function ModelRow({ model, onChanged }: { model: ModelInfo; onChanged: () => void }) {
  const installed = model.status === 'installed';
  return (
    <Card size="small">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <strong style={{ color: tokens.textPrimary, fontSize: 14 }}>{model.name}</strong>
        <Tag color={installed ? 'success' : 'default'}>{installed ? '已安装' : '未安装'}</Tag>
        {model.required && <Tag color="blue">推荐</Tag>}
        <Buttons model={model} onChanged={onChanged} installed={installed} path={model.path ?? null} />
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: tokens.textTertiary, display: 'flex', gap: 16 }}>
        <span>仓库：{model.repo_id}</span>
        <span>类型：{model.kind}</span>
        {model.notes !== '' && <span>{model.notes}</span>}
      </div>
    </Card>
  );
}

interface ButtonSpec {
  key: string;
  label: string;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
}

function Buttons({
  model,
  onChanged,
  installed,
  path,
}: {
  model: ModelInfo;
  onChanged: () => void;
  installed: boolean;
  path: string | null;
}) {
  const noop = (): void => undefined;
  const specs: (ButtonSpec | false)[] = [
    !installed && {
      key: 'download',
      label: '在线下载',
      primary: true,
      onClick: (): void => {
        rpc('models.download', { model_id: model.model_id }).then(onChanged).catch(noop);
      },
    },
    { key: 'refresh', label: '刷新', onClick: onChanged },
    installed && path !== null && {
      key: 'open',
      label: '打开目录',
      onClick: (): void => {
        void revealInFolder(path);
      },
    },
    installed && {
      key: 'delete',
      label: '删除',
      danger: true,
      onClick: (): void => {
        rpc('models.delete', { model_id: model.model_id }).then(onChanged).catch(noop);
      },
    },
  ];

  return (
    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
      {specs.filter(Boolean).map((button) => {
        const spec = button as ButtonSpec;
        return (
          <Button
            key={spec.key}
            size="small"
            type={spec.primary === true ? 'primary' : 'default'}
            danger={spec.danger === true}
            onClick={spec.onClick}
          >
            {spec.label}
          </Button>
        );
      })}
    </div>
  );
}