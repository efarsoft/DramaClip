/**
 * 引擎中心页的数据拉取：一次拉齐模型清单、设置、体检报告、机器与登记本，各 tab 共用同一份。
 *
 * 五路一起等（Promise.all）而不是五张卡片各自加载：页面只有一句「加载中…」，
 * 半张表拼出来会给错状态。登记本单独回话——`{records, error}` 里的坏消息要原样上屏，
 * 它读坏了不等于库里没货，所以不能吞掉报错当空表。
 * 就地体检只并进被检的那一行：整表重拉会把别人刚跑完的下载进度一起抹掉。
 */
import { useCallback, useEffect, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { ImportRecord, ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { enginesApi, modelsApi, rpc, systemApi } from '../../services/client';
import { type Reports, reportsOf } from './assetState';
import { type MachineSpecs, specsFromHealth } from './machineFit';
import type { SettingsMap } from './EnginesPage';

export interface EnginesData {
  readonly models: ModelInfo[];
  readonly imported: ImportRecord[];
  readonly importError: string;
  readonly settings: SettingsMap;
  readonly reports: Reports;
  /** 自检账本（engines.selftest_results）：就绪口径的能力层那一半。 */
  readonly selftests: SelftestResults;
  readonly ffmpegVersion: string;
  readonly machine: MachineSpecs;
}

export interface EnginesDataHub {
  readonly data: EnginesData | null;
  readonly load: () => Promise<void>;
  readonly saveSettings: (values: SettingsMap) => Promise<void>;
  readonly verifyOne: (modelId: string) => Promise<void>;
}

export function useEnginesData(): EnginesDataHub {
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<EnginesData | null>(null);

  const load = useCallback(async () => {
    const [models, settings, reports, health, records, selftests] = await Promise.all([
      modelsApi.list(),
      rpc<SettingsMap>('settings.get'),
      modelsApi.verify(),
      systemApi.health(),
      modelsApi.importRecords(),
      enginesApi.selftestResults(),
    ]);
    setData({
      models,
      imported: records.records,
      importError: records.error,
      settings,
      reports: reportsOf(reports),
      selftests,
      ffmpegVersion: health.ffmpeg_version,
      machine: specsFromHealth(health),
    });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveSettings = useCallback(
    (values: SettingsMap): Promise<void> =>
      rpc('settings.update', { values }).then(() => {
        message.success('已保存');
        void load();
      }),
    [load, message],
  );

  const verifyOne = useCallback(async (modelId: string): Promise<void> => {
    const report = (await modelsApi.verify(modelId))[0];
    if (report === undefined) return;
    setData((current) =>
      current === null ? current : { ...current, reports: new Map(current.reports).set(modelId, report) },
    );
  }, []);

  return { data, load, saveSettings, verifyOne };
}
