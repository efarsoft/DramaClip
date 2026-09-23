/** 成品库批量操作（卷二 §4.5 批量三件 + §3.4 危险操作四规矩）：
 * 勾选集、量化确认、逐条 RPC、诚实汇报——失败原因原文上屏，不静默吞。
 * 异步逻辑抽成模块级函数（消息通道注入），hook 只做组装。 */
import { useCallback, useMemo, useState } from 'react';
import { App as AntdApp } from 'antd';
import type { WorkItem } from '@dramaclip/protocol';
import { copyFiles, exportApi, pickFolder, revealInFolder } from '../../services/client';
import { formatTotalGb, selectedBytes } from './worksView';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 消息通道：antd MessageInstance 结构兼容，测试可注入假实现。 */
export interface Reporter {
  success(text: string): void;
  error(text: string): void;
  warning(text: string): void;
}

export async function revealWorks(works: readonly WorkItem[], reporter: Reporter): Promise<void> {
  let failed = 0;
  let reason = '';
  for (const work of works) {
    try {
      const result = await revealInFolder(work.output_path);
      if (!result.ok) {
        failed += 1;
        reason = result.reason ?? '';
      }
    } catch (error: unknown) {
      failed += 1;
      reason = errorMessage(error);
    }
  }
  if (failed > 0) reporter.error(`${String(failed)} 条产物打不开：${reason}`);
}

export async function copyWorksTo(
  works: readonly WorkItem[],
  dest: string,
  reporter: Reporter,
): Promise<void> {
  try {
    const result = await copyFiles(works.map((w) => w.output_path), dest);
    if (result.copied.length > 0) {
      reporter.success(`已复制 ${String(result.copied.length)} 个文件到 ${dest}`);
    }
    for (const fail of result.failed) {
      reporter.error(`复制失败 ${fail.path}：${fail.reason}`);
    }
  } catch (error: unknown) {
    reporter.error(errorMessage(error));
  }
}

export interface DeleteTally {
  deleted: number;
  missing: number;
  errors: string[];
}

/** 逐条删除：单条失败不断批，成败分别计数（missing=盘上已缺但记录照删，服务端语义）。 */
export async function deleteWorks(works: readonly WorkItem[]): Promise<DeleteTally> {
  const tally: DeleteTally = { deleted: 0, missing: 0, errors: [] };
  for (const work of works) {
    try {
      const result = await exportApi.delete(work.id);
      tally.deleted += 1;
      tally.missing += result.missing.length;
    } catch (error: unknown) {
      tally.errors.push(errorMessage(error));
    }
  }
  return tally;
}

export interface WorksBatch {
  readonly selectedIds: ReadonlySet<string>;
  readonly selected: WorkItem[];
  readonly toggle: (id: string) => void;
  readonly clear: () => void;
  readonly openFolders: () => Promise<void>;
  readonly copyTo: () => Promise<void>;
  readonly confirmDelete: () => void;
}

export function useWorksBatch(works: readonly WorkItem[], onDone: () => void): WorksBatch {
  const { message, modal } = AntdApp.useApp();
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const clear = useCallback(() => {
    setSelectedIds(new Set());
  }, []);
  const selected = useMemo(() => works.filter((w) => selectedIds.has(w.id)), [works, selectedIds]);
  const openFolders = useCallback(async () => {
    await revealWorks(selected, message);
  }, [selected, message]);
  const copyTo = useCallback(async () => {
    let dest: string | null;
    try {
      dest = await pickFolder();
    } catch (error: unknown) {
      message.error(errorMessage(error));
      return;
    }
    if (dest === null || dest === '') return; // 用户取消
    await copyWorksTo(selected, dest, message);
  }, [selected, message]);
  const confirmDelete = useCallback(() => {
    if (selected.length === 0) return;
    modal.confirm({
      title: `删除 ${String(selected.length)} 条成片？`,
      content: `共 ${formatTotalGb(selectedBytes(selected))}。文件会移入回收站（数据目录 .trash，按日期存放），可从「关于 → 本地数据 → 回收站」找回；只有清空回收站才真正删除。`,
      okText: '移入回收',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const tally = await deleteWorks(selected);
        if (tally.deleted > 0) message.success(`已移入回收 ${String(tally.deleted)} 条`);
        if (tally.missing > 0) message.warning(`${String(tally.missing)} 个文件已不在盘上，对应记录已删除`);
        if (tally.errors.length > 0) message.error(`删除失败 ${String(tally.errors.length)} 条：${tally.errors[0] ?? ''}`);
        clear();
        onDone();
      },
    });
  }, [selected, modal, message, clear, onDone]);
  return { selectedIds, selected, toggle, clear, openFolders, copyTo, confirmDelete };
}
