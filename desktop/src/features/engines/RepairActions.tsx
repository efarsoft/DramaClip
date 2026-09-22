/**
 * 修复动作（§10.2）：异常态自带修法，按钮与体检判据同源（repairPlan 推导）。
 *
 * 档位纪律：能自动的（清理残留）点了就干；要确认的（就地迁移、删除多余副本、
 * 强制重下）走 Popconfirm 且把代价写在确认文案里——强制重下是真删真下，
 * 必须让业主看见要删掉多少 GB。自检真加载权重，CPU 上十几秒，期间按钮保持
 * loading，不假装空闲（§10.6）。云端/储备资产没有本地推理可跑，不摆自检按钮。
 */
import { useState } from 'react';
import { App as AntdApp, Button, Popconfirm } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo, OrphanCopy, SelftestResult, VerifyReport } from '@dramaclip/protocol';
import { enginesApi, modelsApi } from '../../services/client';
import { formatBytes } from './assetState';
import { repairNeeds } from './repairPlan';

interface RepairProps {
  readonly model: ModelInfo;
  readonly report: VerifyReport | undefined;
  readonly selftest: SelftestResult | undefined;
  readonly onChanged: () => void;
  readonly onVerify: (modelId: string) => void;
}

export function RepairActions({
  model,
  report,
  selftest,
  onChanged,
  onVerify,
}: RepairProps): ReactElement | null {
  if (model.status !== 'installed') return null;
  const needs = repairNeeds(report);
  const broken = report !== undefined && !report.ok;
  const selftestFailed = selftest !== undefined && !selftest.ok;
  const localInference = model.engine_ready && (model.kind === 'asr' || model.kind === 'tts');
  return (
    <>
      {needs.residue && <ResidueButton model={model} onChanged={onChanged} onVerify={onVerify} />}
      {needs.migrate && <MigrateButton model={model} onChanged={onChanged} onVerify={onVerify} />}
      {needs.orphanPaths.length > 0 && <OrphanButton model={model} onChanged={onChanged} />}
      {localInference && (
        <SelftestButton model={model} selftest={selftest} onChanged={onChanged} />
      )}
      {(broken || selftestFailed) && <RedownloadButton model={model} onChanged={onChanged} />}
    </>
  );
}

/** 服务端 rpc 拒绝时带 [code] 原文——原样上屏，比前端猜一句「失败」有用。 */
function errText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback;
}

function ResidueButton({
  model,
  onChanged,
  onVerify,
}: {
  model: ModelInfo;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="small"
      loading={busy}
      title="删除 *.incomplete 半截文件：占磁盘但不参与推理，可安全清理"
      onClick={() => {
        setBusy(true);
        modelsApi
          .cleanResidue(model.model_id)
          .then((result) => {
            message.success(
              result.removed === 0
                ? '没有可清理的残留——可能刚被别的动作清掉了'
                : `已清理 ${String(result.removed)} 个残留，释放 ${formatBytes(result.freed_bytes)}`,
            );
            onVerify(model.model_id);
            onChanged();
          })
          .catch((error: unknown) => {
            message.error(errText(error, '清理失败'));
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      清理残留
    </Button>
  );
}

function MigrateButton({
  model,
  onChanged,
  onVerify,
}: {
  model: ModelInfo;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <Popconfirm
      title="就地迁移"
      description="把 snapshots/main 重命名成真实提交号布局——不搬文件、不联网；迁移后体检可逐文件对账。"
      okText="迁移"
      cancelText="取消"
      onConfirm={() => {
        modelsApi
          .relayout(model.model_id)
          .then((result) => {
            message.success(result.migrated ? '已迁移到提交号布局' : '已是合规布局，无需迁移');
            onVerify(model.model_id);
            onChanged();
          })
          .catch((error: unknown) => {
            message.error(errText(error, '迁移失败'));
          });
      }}
    >
      <Button size="small">就地迁移</Button>
    </Popconfirm>
  );
}

function OrphanButton({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const [open, setOpen] = useState(false);
  const [copies, setCopies] = useState<OrphanCopy[] | null>(null);
  return (
    <Popconfirm
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next && copies === null) {
          modelsApi
            .orphanList(model.model_id)
            .then(setCopies)
            .catch(() => {
              setCopies([]);
            });
        }
      }}
      title="删除多余副本"
      description={<OrphanDescription copies={copies} />}
      okText="删除"
      okButtonProps={{ danger: true }}
      cancelText="取消"
      onConfirm={() => {
        const list = copies ?? [];
        Promise.all(list.map((copy) => modelsApi.cleanOrphan(model.model_id, copy.path)))
          .then((results) => {
            const freed = results.reduce((sum, item) => sum + item.freed_bytes, 0);
            message.success(
              list.length === 0
                ? '名单里的副本已不在盘上——点「体检」刷新即可'
                : `已删除 ${String(list.length)} 处多余副本，释放 ${formatBytes(freed)}`,
            );
            onChanged();
          })
          .catch((error: unknown) => {
            message.error(errText(error, '删除失败'));
          });
      }}
    >
      <Button size="small">删多余副本</Button>
    </Popconfirm>
  );
}

function OrphanDescription({ copies }: { copies: OrphanCopy[] | null }): ReactElement {
  if (copies === null) return <span>正在查询副本清单…</span>;
  if (copies.length === 0) {
    return <span>体检名单里的副本已不在盘上——确定后重新体检即可回绿。</span>;
  }
  const total = copies.reduce((sum, copy) => sum + copy.size_bytes, 0);
  return (
    <span style={{ whiteSpace: 'pre-line' }}>
      {`共 ${String(copies.length)} 处、${formatBytes(total)}——引擎只读登记路径那份，\n删除不碰它：\n${copies
        .map((copy) => copy.path)
        .join('\n')}`}
    </span>
  );
}

function SelftestButton({
  model,
  selftest,
  onChanged,
}: {
  model: ModelInfo;
  selftest: SelftestResult | undefined;
  onChanged: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="small"
      loading={busy}
      title={selftestTitle(selftest)}
      onClick={() => {
        setBusy(true);
        enginesApi
          .selftest({ modelId: model.model_id })
          .then((result) => {
            if (result.ok) message.success(selftestSummary(result));
            else message.error(`自检未通过：${result.error ?? '未知原因'}`, 8);
            onChanged();
          })
          .catch((error: unknown) => {
            message.error(errText(error, '自检失败'));
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      {busy ? '自检中' : '自检'}
    </Button>
  );
}

function selftestSummary(result: SelftestResult): string {
  const elapsed = result.elapsed_s !== undefined ? ` · 耗时 ${result.elapsed_s.toFixed(1)}s` : '';
  if (result.chars !== undefined) {
    return `自检通过：识别 ${String(result.chars)} 字${elapsed}`;
  }
  if (result.duration_s !== undefined) {
    return `自检通过：合成 ${result.duration_s.toFixed(1)}s 音频${elapsed}`;
  }
  return `自检通过${elapsed}`;
}

function selftestTitle(selftest: SelftestResult | undefined): string {
  const intro = '用随包样例真跑一段：ASR 真转写 / TTS 真合成（CPU 上约十几秒）';
  if (selftest === undefined) return intro;
  const when = selftest.at !== undefined ? new Date(selftest.at).toLocaleString() : '时间未知';
  if (!selftest.ok) return `上次自检（${when}）未通过：${selftest.error ?? ''}`;
  return `上次自检（${when}）通过：${selftestSummary(selftest)}`;
}

function RedownloadButton({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <Popconfirm
      title="强制重新下载"
      description={`真删真下：先删除现有 ${formatBytes(model.size_bytes ?? 0)}，再重新下载（失败自动换源，下载中可取消）。`}
      okText="删除并重下"
      okButtonProps={{ danger: true }}
      cancelText="取消"
      onConfirm={() => {
        modelsApi
          .download(model.model_id, undefined, true)
          .then(() => {
            message.success(`已开始重新下载 ${model.name}`);
            onChanged();
          })
          .catch((error: unknown) => {
            message.error(errText(error, '下载任务创建失败'));
          });
      }}
    >
      <Button size="small">重新下载</Button>
    </Popconfirm>
  );
}
