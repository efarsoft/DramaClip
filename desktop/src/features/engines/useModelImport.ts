/**
 * 导入向导在页面上的三件事：开合、落位后写设置、撤销登记后重拉。
 *
 * 这里一条判据都不实现——写回哪几个键出自 assetState.activateById（查不到那一行就返回 null），
 * 「能不能导、动了哪些文件」出自后端。页面只负责把这三件事接到弹窗与资产库上。
 */
import { useCallback, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { ModelInfo } from '@dramaclip/protocol';
import { modelsApi } from '../../services/client';
import { activateById } from './assetState';

export interface ImportHub {
  readonly importing: boolean;
  open: () => void;
  close: () => void;
  activateLanded: (modelId: string) => void;
  forget: (path: string) => void;
}

export function useModelImport(
  models: readonly ModelInfo[],
  reload: () => Promise<void>,
  save: (values: Record<string, string>) => Promise<void>,
): ImportHub {
  const { message } = AntdApp.useApp();
  const [importing, setImporting] = useState(false);

  /**
   * 向导第 ④ 步只交回 model_id：库里查不到这一行（页面数据比导入时旧）就一句设置都不写，
   * 宁可让业主刷新后再选，也不凭一个查无此物的 id 改引擎。
   */
  const activateLanded = useCallback(
    (modelId: string): void => {
      const values = activateById(models, modelId);
      if (values === null) {
        message.error('资产库里还没有这一行，刷新后再选为生效');
        return;
      }
      void save(values);
    },
    [message, models, save],
  );

  /** 撤销登记只划登记本那一行；文件本来就在业主自己的盘上，后端也不会去动它。 */
  const forget = useCallback(
    (path: string): void => {
      modelsApi
        .forgetImport(path)
        .then(() => {
          void reload();
        })
        .catch(() => {
          message.error('撤销登记失败');
        });
    },
    [message, reload],
  );

  return {
    importing,
    open: () => {
      setImporting(true);
    },
    close: () => {
      setImporting(false);
    },
    activateLanded,
    forget,
  };
}
