/** 提示词 tab 状态与动作：加载/编辑/保存/重置（UI 解耦）。 */
import { App as AntdApp } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { PromptInfo } from '@dramaclip/protocol';
import { promptsApi } from '../../services/client';

export function usePrompts(): PromptsState {
  const { message } = AntdApp.useApp();
  const [prompts, setPrompts] = useState<PromptInfo[] | null>(null);
  const [editing, setEditing] = useState<PromptInfo | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async (): Promise<void> => {
    setPrompts((await promptsApi.list()).prompts);
  }, []);

  useEffect(() => {
    reload()
      .catch((error: unknown) => {
        // 只报"加载失败"会把真因（未注册的方法、断连）藏起来，运维无从判断
        const reason = error instanceof Error ? error.message : String(error);
        message.error(`提示词加载失败：${reason}`);
        setPrompts([]);
      })
      .finally(() => undefined);
  }, [reload, message]);

  const showError = (error: unknown): void => {
    message.error(error instanceof Error ? error.message : String(error));
  };

  const runAction = async (action: () => Promise<{ ok: boolean }>, success: string): Promise<void> => {
    try {
      await action();
      message.success(success);
      await reload();
    } catch (error: unknown) {
      showError(error);
    }
  };

  const save = async (): Promise<void> => {
    if (editing === null) return;
    setSaving(true);
    try {
      await promptsApi.save(editing.key, draft);
      message.success('已保存，下一次出片即生效');
      setEditing(null);
      await reload();
    } catch (error: unknown) {
      showError(error);
    } finally {
      setSaving(false);
    }
  };

  const reset = (info: PromptInfo): void => {
    void runAction(() => promptsApi.reset(info.key), `「${info.title}」已恢复默认`);
  };

  // 打开时必须把现值灌进草稿：否则编辑框一片空白，存回去就是把提示词清空
  const openEdit = (info: PromptInfo): void => {
    setDraft(info.current);
    setEditing(info);
  };

  const closeEdit = (): void => {
    setEditing(null);
  };

  return { prompts, editing, openEdit, closeEdit, draft, setDraft, saving, save, reset };
}

export interface PromptsState {
  prompts: PromptInfo[] | null;
  editing: PromptInfo | null;
  openEdit: (info: PromptInfo) => void;
  closeEdit: () => void;
  draft: string;
  setDraft: (text: string) => void;
  saving: boolean;
  save: () => Promise<void>;
  reset: (info: PromptInfo) => void;
}
