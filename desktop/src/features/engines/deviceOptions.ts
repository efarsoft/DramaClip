/** ASR / TTS / 视觉轨的「运行设备」选项：可用性读后端算好的 cap，不读厂商、不解析文案。
 *
 * CUDA 是承诺（`device_resolve` 会拒绝不 ready 的 cuda），所以界面只提供会被接受的
 * 值。两类缺席必须保留 CUDA 而不是藏掉：显卡还在探测中、该引擎没有能力判据
 * （kokoro 一类）——「不知道」渲染成「不可用」就是假阴性（`unknown ≠ ok`）。
 */
import type { DeviceCaps, GpuInfo } from '@dramaclip/protocol';
import type { MachineSpecs } from './machineFit';

export interface DeviceOption {
  readonly label: string;
  readonly value: string;
  readonly disabled?: boolean;
}

/** 引擎 → cap 名：与后端 `device_resolve._COMPONENT_CAPS` 同一批键。
 * cosyvoice 系与 indextts2 共用 `indextts2_gpu`——那个键实质是「torch cu128 栈」。 */
const ENGINE_CAP: Readonly<Record<string, string>> = {
  faster_whisper: 'faster_whisper_gpu',
  sensevoice: 'funasr_gpu',
  paraformer: 'funasr_gpu',
  indextts2: 'indextts2_gpu',
  cosyvoice: 'indextts2_gpu',
  cosyvoice3: 'indextts2_gpu',
};

const CUDA_LABEL = 'CUDA（NVIDIA）';

/** 视觉模型档位 → cap 名：`qwen3-vl-4b` → `local_visual_4b`（后端 device_profile 同一批键）。 */
export function visualCapKey(modelId: string): string {
  return `local_visual_${modelId.slice(modelId.lastIndexOf('-') + 1)}`;
}

export function deviceOptions(args: {
  readonly engine: string;
  readonly saved: string;
  readonly gpu?: GpuInfo;
  readonly caps?: DeviceCaps;
  /** 判据不随引擎名走的域直接点名 cap 键（视觉轨按模型档位各有一条）。 */
  readonly capKey?: string;
}): readonly DeviceOption[] {
  const base: readonly DeviceOption[] = [
    { label: '自动（检测 GPU）', value: 'auto' },
    { label: 'CPU', value: 'cpu' },
  ];
  if (!args.gpu?.ready) {
    return [...base, { label: CUDA_LABEL, value: 'cuda' }];
  }
  const cap = args.caps?.[args.capKey ?? ENGINE_CAP[args.engine] ?? ''];
  if (cap === undefined || cap.ready) {
    return [...base, { label: CUDA_LABEL, value: 'cuda' }];
  }
  if (args.saved !== 'cuda') return base;
  // 陈旧设置可见、可改走，而不是静默吞掉或渲染成空白
  return [
    ...base,
    {
      label: `CUDA（${cap.reason !== '' ? cap.reason : '本机不可用'}）`,
      value: 'cuda',
      disabled: true,
    },
  ];
}

/** antd 形状：各域 tab 共用，选项生成只住在 `deviceOptions` 这一处。 */
export function deviceSelectProps(args: {
  readonly engine: string;
  readonly saved: string;
  readonly machine: MachineSpecs;
  readonly capKey?: string;
}): { readonly options: readonly DeviceOption[] } {
  return {
    options: deviceOptions({
      engine: args.engine,
      saved: args.saved,
      gpu: args.machine.gpu,
      caps: args.machine.caps,
      capKey: args.capKey,
    }),
  };
}
