/** 云端配置动作集：加载/保存/启用/删除（同域单启用，状态与副作用就近内聚）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { EngineConfig } from '@dramaclip/protocol';
import { engineConfigsApi } from '../../services/client';
import type { FormState } from './CloudConfigModal';

type AppApi = ReturnType<typeof AntdApp.useApp>;

interface Editing {
  readonly id: string;
  readonly form: FormState;
}

export interface EngineConfigActions {
  readonly configs: readonly EngineConfig[];
  readonly saving: boolean;
  /** 保存失败的原因原文：进弹窗内联横幅，不再只闪一次 toast（卷二 P-A）。 */
  readonly saveError: string | null;
  readonly editing: Editing | null;
  readonly adding: boolean;
  readonly openAdd: () => void;
  readonly openEdit: (config: EngineConfig) => void;
  readonly close: () => void;
  readonly save: (form: FormState) => void;
  readonly enable: (config: EngineConfig) => void;
  readonly remove: (config: EngineConfig) => void;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback;
}

function trim(form: FormState): { name: string; base_url: string; api_key: string; model: string } {
  return {
    name: form.name.trim(),
    base_url: form.base_url.trim(),
    api_key: form.api_key.trim(),
    model: form.model.trim(),
  };
}

function persistCall(editingId: string | null, domain: string, payload: ReturnType<typeof trim>): Promise<EngineConfig> {
  return editingId !== null
    ? engineConfigsApi.update({ id: editingId, ...payload })
    : engineConfigsApi.create({ domain, ...payload });
}

function saveConfig(
  editingId: string | null,
  domain: string,
  form: FormState,
  settle: {
    readonly setSaving: (value: boolean) => void;
    readonly setSaveError: (value: string | null) => void;
    readonly onDone: () => void;
  },
): void {
  if (form.name.trim() === '') {
    settle.setSaveError('请填写配置名称：名称为空时服务端无法建档');
    return;
  }
  settle.setSaving(true);
  settle.setSaveError(null);
  persistCall(editingId, domain, trim(form))
    .then(() => {
      settle.onDone();
    })
    .catch((error: unknown) => {
      // 弹窗保持打开、草稿不丢：原因原文进表单顶部横幅，改完可直接再存
      settle.setSaveError(errorText(error, '保存失败'));
    })
    .finally(() => {
      settle.setSaving(false);
    });
}

function enableConfig(app: AppApi, config: EngineConfig, onDone: (text: string) => void): void {
  engineConfigsApi
    .enable(config.id)
    .then(() => {
      onDone(`已启用「${config.name}」`);
    })
    .catch((error: unknown) => {
      app.message.error(errorText(error, '启用失败'));
    });
}

function confirmRemove(app: AppApi, config: EngineConfig, onDone: (text: string) => void): void {
  app.modal.confirm({
    title: `删除配置「${config.name}」？`,
    content: '删除后不可恢复；启用中的配置需先启用其他配置。',
    okButtonProps: { danger: true },
    onOk: () =>
      engineConfigsApi
        .remove(config.id)
        .then(() => {
          onDone('已删除');
        })
        .catch((error: unknown) => {
          app.message.error(errorText(error, '删除失败'));
        }),
  });
}

function editActions(
  setAdding: (value: boolean) => void,
  setEditing: (value: Editing | null) => void,
  clearError: () => void,
): Pick<EngineConfigActions, 'openAdd' | 'openEdit' | 'close'> {
  return {
    openAdd: () => {
      clearError();
      setEditing(null);
      setAdding(true);
    },
    openEdit: (config) => {
      clearError();
      setAdding(false);
      setEditing({
        id: config.id,
        form: {
          name: config.name,
          base_url: config.base_url,
          api_key: config.api_key,
          model: config.model,
        },
      });
    },
    close: () => {
      clearError();
      setAdding(false);
      setEditing(null);
    },
  };
}

export function useEngineConfigs(domain: string, onChanged?: () => void): EngineConfigActions {
  const app = AntdApp.useApp();
  const [configs, setConfigs] = useState<readonly EngineConfig[]>([]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const reload = useCallback(() => {
    engineConfigsApi
      .list(domain)
      .then((res) => {
        setConfigs(res.configs);
      })
      .catch(() => {
        setConfigs([]);
      });
  }, [domain]);

  useEffect(() => {
    reload();
  }, [reload]);

  const afterChange = (text: string): void => {
    app.message.success(text);
    reload();
    onChanged?.();
  };

  const closeAndReload = (): void => {
    setAdding(false);
    setEditing(null);
    afterChange('已保存');
  };

  return {
    configs,
    saving,
    saveError,
    editing,
    adding,
    ...editActions(setAdding, setEditing, () => {
      setSaveError(null);
    }),
    save: (form) => {
      saveConfig(editing?.id ?? null, domain, form, {
        setSaving,
        setSaveError,
        onDone: closeAndReload,
      });
    },
    enable: (config) => {
      enableConfig(app, config, afterChange);
    },
    remove: (config) => {
      confirmRemove(app, config, afterChange);
    },
  };
}
