/** 本机运行条件面板：GPU / 内存 / 磁盘 + 整机结论——回答"本地模型我能不能跑"。 */
import { useEffect, useState, type ReactElement } from 'react';
import type { HealthResult, ModelInfo } from '@dramaclip/protocol';
import { systemApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { FIT_VERDICT_COLOR, FIT_VERDICT_LABEL, judgeMachine, parseSizeGb, specsFromHealth } from './machineFit';

function SectionCard({ children }: { children: React.ReactNode }): ReactElement {
  return (
    <div
      style={{
        padding: `${tokens.spaceMd} ${tokens.spaceLg}`,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
      }}
    >
      {children}
    </div>
  );
}

/** 总览页·本机运行条件卡。 */
export function MachinePanel({ models }: { models: ModelInfo[] }): ReactElement {
  const [health, setHealth] = useState<HealthResult | null>(null);
  useEffect(() => {
    void systemApi
      .health()
      .then(setHealth)
      .catch(() => undefined);
  }, []);
  const gpu = health?.gpu_info;
  const specs = specsFromHealth(health);
  const maxSizeGb = maxLocalModelSizeGb(models);
  const verdict = judgeMachine(specs, maxSizeGb);
  const cells: { label: string; value: string }[] = [
    {
      label: '显卡',
      value: gpu?.ready
        ? `${gpu.name}${gpu.max_cuda_version !== '' ? ` · CUDA ${gpu.max_cuda_version}` : ''}`
        : '未检测到 NVIDIA · 走 CPU',
    },
    {
      label: '内存',
      value:
        health?.ram_total_gb !== undefined
          ? `${String(health.ram_free_gb ?? '—')} / ${String(health.ram_total_gb)} GB 可用`
          : '…',
    },
    {
      label: '数据盘可用',
      value: health?.disk_free_gb !== undefined ? `${String(health.disk_free_gb)} GB` : '…',
    },
  ];
  return (
    <SectionCard>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceLg }}>
        {cells.map((cell) => (
          <SpecCell key={cell.label} label={cell.label} value={cell.value} />
        ))}
      </div>
      {verdict.verdict !== 'unknown' && <VerdictLine verdict={verdict} maxSizeGb={maxSizeGb} />}
    </SectionCard>
  );
}

function SpecCell({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary }}>{label}</span>
      <span
        style={{
          fontSize: tokens.fontCaption,
          color: tokens.textSecondary,
          fontFamily: tokens.fontFamilyMono,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {value}
      </span>
    </div>
  );
}

function VerdictLine({
  verdict,
  maxSizeGb,
}: {
  verdict: ReturnType<typeof judgeMachine>;
  maxSizeGb: number | undefined;
}): ReactElement {
  const tail =
    verdict.verdict === 'ok'
      ? '；本地引擎均为 CPU 可跑，NVIDIA 显卡仅用于转写加速'
      : `——${verdict.reason}`;
  return (
    <div
      style={{
        marginTop: tokens.spaceMd,
        paddingTop: tokens.spaceMd,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        fontSize: tokens.fontCaption,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: tokens.radiusThumb,
          background: FIT_VERDICT_COLOR[verdict.verdict],
          flexShrink: 0,
        }}
      />
      <span style={{ color: tokens.textSecondary }}>
        本机{FIT_VERDICT_LABEL[verdict.verdict]}
        {maxSizeGb !== undefined ? `全部本地模型（最大约 ${String(maxSizeGb)}GB）` : ''}
        {tail}
      </span>
    </div>
  );
}

/** registry 全部本地模型中的最大体积（GB）。 */
function maxLocalModelSizeGb(models: ModelInfo[]): number | undefined {
  const sizes = models.map((m) => parseSizeGb(m.size_label)).filter((s) => s !== undefined);
  return sizes.length === 0 ? undefined : Math.max(...sizes);
}
