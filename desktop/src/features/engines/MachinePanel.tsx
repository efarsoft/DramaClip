/** 本机运行条件面板：GPU / 内存 / 磁盘 / 运行环境 + 整机结论——回答"本地模型我能不能跑"。 */
import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from 'antd';
import type { HealthResult, ModelInfo } from '@dramaclip/protocol';
import { indexttsApi, runtimeApi, systemApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
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
export function MachinePanel({ models }: { models: readonly ModelInfo[] }): ReactElement {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthResult | null>(null);
  useEffect(() => {
    void systemApi
      .health()
      .then(setHealth)
      .catch(() => undefined);
  }, []);
  const probeCuda = useCallback(() => runtimeApi.status(), []);
  const probeIndextts = useCallback(() => indexttsApi.status(), []);
  const cuda = useEnvStatus(probeCuda);
  const indextts = useEnvStatus(probeIndextts);
  const gpu = health?.gpu_info;
  const specs = specsFromHealth(health);
  const maxSizeGb = maxLocalModelSizeGb(models);
  const verdict = judgeMachine(specs, maxSizeGb);
  const cells = specCellsOf(health);
  return (
    <SectionCard>
      <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>
        本机运行条件
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceLg, marginTop: tokens.spaceMd }}>
        {cells.map((cell) => (
          <SpecCell key={cell.label} label={cell.label} value={cell.value} />
        ))}
      </div>
      <EnvSection
        cuda={cuda}
        indextts={indextts}
        gpuIsNvidia={gpu?.ready === true && gpu.vendor === 'nvidia'}
        onGoTts={() => {
          void navigate('/engines/tts');
        }}
      />
      {verdict.verdict !== 'unknown' && <VerdictLine verdict={verdict} maxSizeGb={maxSizeGb} />}
      <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        本卡回答硬件「装得下 / 跑得动」与两个运行环境在不在；修复动作各有其家：CUDA
        运行库在本页「转写加速（GPU）」卡，IndexTTS 运行环境在配音 TTS 页。某次转写实际走了哪张卡，看语音识别域内的转写加速卡。
      </div>
    </SectionCard>
  );
}

/** 运行环境探测三态：装好 / 没装 / 探测失败——取不到 ≠ 不存在，失败不冒充「未安装」。 */
type EnvStatus = 'loading' | 'installed' | 'missing' | 'unknown';

function useEnvStatus(probe: () => Promise<{ installed: boolean }>): EnvStatus {
  const [status, setStatus] = useState<EnvStatus>('loading');
  useEffect(() => {
    let stopped = false;
    probe()
      .then((result) => {
        if (!stopped) setStatus(result.installed ? 'installed' : 'missing');
      })
      .catch(() => {
        if (!stopped) setStatus('unknown');
      });
    return () => {
      stopped = true;
    };
  }, [probe]);
  return status;
}

const ENV_DOT: Record<EnvStatus, string> = {
  loading: tokens.textTertiary,
  installed: tokens.colorSuccess,
  missing: tokens.colorWarning,
  unknown: tokens.textTertiary,
};

/** 运行环境两行：CUDA 运行库（转写加速）+ IndexTTS 运行环境（音色克隆）。
 * 总览只给结论与落点（本页口径）：CUDA 的下载按钮在隔壁 GPU 卡，IndexTTS 的一键
 * 安装在配音 TTS 页——这里不重复放动作，缺了就给落点。 */
function EnvSection({
  cuda,
  indextts,
  gpuIsNvidia,
  onGoTts,
}: {
  cuda: EnvStatus;
  indextts: EnvStatus;
  gpuIsNvidia: boolean;
  onGoTts: () => void;
}): ReactElement {
  return (
    <div
      style={{
        marginTop: tokens.spaceMd,
        paddingTop: tokens.spaceMd,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
      }}
    >
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        运行环境
      </span>
      <EnvRow label="CUDA 运行库" status={cuda} text={cudaText(cuda, gpuIsNvidia)} />
      <EnvRow
        label="IndexTTS 运行环境"
        status={indextts}
        text={indexttsText(indextts)}
        action={
          indextts === 'missing' ? (
            <Button size="small" type="link" style={{ padding: 0, height: 'auto' }} onClick={onGoTts}>
              去安装
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}

function cudaText(status: EnvStatus, gpuIsNvidia: boolean): string {
  if (status === 'loading') return '检测中…';
  if (status === 'unknown') return '状态未知 · 探测失败，稍后刷新页面重试';
  if (status === 'installed') return '已安装 · 转写可走 GPU 加速';
  return gpuIsNvidia
    ? '未安装 · 转写走 CPU，可在本页「转写加速（GPU）」卡下载'
    : '未安装 · 本机无 NVIDIA 显卡，无需安装，转写走 CPU';
}

function indexttsText(status: EnvStatus): string {
  if (status === 'loading') return '检测中…';
  if (status === 'unknown') return '状态未知 · 探测失败，稍后刷新页面重试';
  if (status === 'installed') return '已安装 · 音色克隆配音可用';
  return '未安装 · IndexTTS 音色克隆不可用（约 2~6GB，独立 Python + torch）';
}

function EnvRow({
  label,
  status,
  text,
  action,
}: {
  label: string;
  status: EnvStatus;
  text: string;
  action?: ReactElement;
}): ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, minWidth: 0 }}>
      <span style={mixins.statusDot(ENV_DOT[status])} />
      <span
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textSecondary,
          minWidth: 0,
        }}
      >
        {`${label}：${text}`}
      </span>
      {action !== undefined && <span style={{ marginLeft: 'auto', flexShrink: 0 }}>{action}</span>}
    </div>
  );
}

/** 硬件三格文案：显卡 / 内存 / 数据盘——取不到就如实「…」，不冒充有答案。 */
function specCellsOf(health: HealthResult | null): { label: string; value: string }[] {
  const gpu = health?.gpu_info;
  return [
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
}

function SpecCell({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>{label}</span>
      <span
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
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
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
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
function maxLocalModelSizeGb(models: readonly ModelInfo[]): number | undefined {
  const sizes = models.map((m) => parseSizeGb(m.size_label)).filter((s) => s !== undefined);
  return sizes.length === 0 ? undefined : Math.max(...sizes);
}
