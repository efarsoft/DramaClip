/** 本机运行条件面板：GPU / 内存 / 磁盘 / 运行环境 + 整机结论——回答"本地模型我能不能跑"。 */
import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from 'antd';
import type { DeviceProfile, HealthResult, ModelInfo } from '@dramaclip/protocol';
import { localRuntimeApi, runtimeApi, systemApi } from '../../services/client';
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
  const probeLocal = useCallback(() => localRuntimeApi.status(), []);
  const cuda = useEnvStatus(probeCuda);
  const localRuntime = useEnvStatus(probeLocal);
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
        localRuntime={localRuntime}
        gpuIsNvidia={gpu?.ready === true && gpu.vendor === 'nvidia'}
        onGoTts={() => {
          void navigate('/engines/tts');
        }}
      />
      {health?.device_profile !== undefined && (
        <TierLine profile={health.device_profile} ttsReady={localRuntime === 'installed'} />
      )}
      {verdict.verdict !== 'unknown' && <VerdictLine verdict={verdict} maxSizeGb={maxSizeGb} />}
      <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        本卡回答硬件「装得下 / 跑得动」与两个运行环境在不在；修复动作各有其家：CUDA
        运行库在本页「转写加速（GPU）」卡，本地智能运行环境在 ASR / 配音 TTS 页。某次转写实际走了哪张卡，看语音识别域内的转写加速卡。
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

/** 运行环境两行：CUDA 运行库（转写加速）+ 本地智能运行环境（本地识别/克隆/kokoro）。
 * 总览只给结论与落点（本页口径）：CUDA 的下载按钮在隔壁 GPU 卡，运行环境的一键
 * 安装在 ASR / 配音 TTS 页——这里不重复放动作，缺了就给落点。 */
function EnvSection({
  cuda,
  localRuntime,
  gpuIsNvidia,
  onGoTts,
}: {
  cuda: EnvStatus;
  localRuntime: EnvStatus;
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
        label="本地智能运行环境"
        status={localRuntime}
        text={localRuntimeText(localRuntime)}
        action={
          localRuntime !== 'installed' && localRuntime !== 'loading' ? (
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

function localRuntimeText(status: EnvStatus): string {
  if (status === 'loading') return '检测中…';
  if (status === 'unknown') return '状态未知 · 探测失败，稍后刷新页面重试';
  if (status === 'installed') return '已安装 · 本地识别 / 音色克隆 / Kokoro 可用';
  return '未装齐 · 本地识别与克隆配音不可用（约 2~6GB，独立 Python + torch）';
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
        ? `${gpu.name}${gpu.memory_total_mb > 0 ? ` · ${String(Math.round(gpu.memory_total_mb / 1024))}GB` : ''}${gpu.max_cuda_version !== '' ? ` · CUDA ${gpu.max_cuda_version}` : ''}`
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

/** 设备档位行：显存分档 + GPU 引擎能力结论 + 驱动引导（needed 才给下载入口）。 */
function TierLine({
  profile,
  ttsReady,
}: {
  profile: DeviceProfile;
  ttsReady: boolean;
}): ReactElement {
  const vram =
    profile.memory_total_mb > 0 ? `${String(Math.round(profile.memory_total_mb / 1024))}GB 显存` : '';
  const caps = profile.caps;
  // indextts2 的运行时态由前端组合：tts-venv 装好且 torch 变体为 cuda（后端探针只到安装态）
  const readyOf = (key: string): boolean =>
    key === 'indextts2_gpu' ? caps[key].ok && ttsReady : caps[key].ready;
  const readyList = Object.entries(caps)
    .filter(([key]) => readyOf(key))
    .map(([key]) => CAP_LABEL[key]);
  const okList = Object.entries(caps)
    .filter(([key, cap]) => cap.ok && !readyOf(key))
    .map(([key]) => CAP_LABEL[key]);
  const tail =
    readyList.length > 0
      ? `GPU 加速已生效：${readyList.join('、')}`
      : okList.length > 0
        ? `硬件满足但待运行时：${okList.join('、')}`
        : '';
  const dot = readyList.length > 0 ? tokens.colorSuccess : okList.length > 0 ? tokens.colorWarning : tokens.textTertiary;
  return (
    <div
      style={{
        marginTop: tokens.spaceMd,
        paddingTop: tokens.spaceMd,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        flexWrap: 'wrap',
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: tokens.radiusThumb, background: dot, flexShrink: 0 }} />
      <span style={{ color: tokens.textSecondary }}>
        {`${profile.tier_label}${vram !== '' ? ` · ${vram}` : ''} · ${profile.recommendation}${tail !== '' ? ` · ${tail}` : ''}`}
      </span>
      {profile.driver_guidance.needed && (
        <Button
          size="small"
          type="link"
          style={{ padding: 0, height: 'auto' }}
          onClick={() => {
            void window.open(profile.driver_guidance.url, '_blank');
          }}
        >
          更新驱动（需 {profile.driver_guidance.min_driver}+）
        </Button>
      )}
    </div>
  );
}

const CAP_LABEL: Record<string, string> = {
  faster_whisper_gpu: '转写加速',
  indextts2_gpu: '音色克隆',
  funasr_gpu: '本地 ASR',
  vocal_separation_gpu: '人声分离',
  local_visual_2b: '视觉 2B',
  local_visual_4b: '视觉 4B',
  local_visual_8b: '视觉 8B',
};

/** registry 全部本地模型中的最大体积（GB）。 */
function maxLocalModelSizeGb(models: readonly ModelInfo[]): number | undefined {
  const sizes = models.map((m) => parseSizeGb(m.size_label)).filter((s) => s !== undefined);
  return sizes.length === 0 ? undefined : Math.max(...sizes);
}
