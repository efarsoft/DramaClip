/** 系统偏好设置项（引擎类配置在「引擎中心」；键权威源：service config.DEFAULTS）。
 *
 * 分区口径（09-10 §4.6 / 卷二 #9）：「生产线默认值」与「字幕」两分区补入——
 * 键与消费端同源：K 默认 = narration.variants_per_mode（出片中心 K 下拉初值 + 服务端
 * 缺省 k），风格默认 = narration.style_id（出片中心风格选择器同键），内封字幕预设 =
 * subtitle.default_preset（export 渲染消费）。subtitle.smart_match 至今无消费端，
 * 不做假控件——键留在服务端等裁决，界面不摆没人听的开关。
 */

export type SettingsMap = Record<string, string>;

export interface Option {
  readonly label: string;
  readonly value: string;
}

export type FieldType = 'text' | 'password' | 'number' | 'select' | 'switch';

export interface FieldSpec {
  readonly key: string;
  readonly label: string;
  readonly type: FieldType;
  readonly help?: string;
  readonly placeholder?: string;
  readonly min?: number;
  readonly max?: number;
  /** select 选项；voice 等联动字段按当前草稿值返回。 */
  readonly options?: (values: SettingsMap) => readonly Option[];
}

export interface SectionSpec {
  readonly id: string;
  readonly title: string;
  readonly fields: readonly FieldSpec[];
}

/** 目录类选项的注入源（SettingsPage 异步取回后传入，spec 本身保持纯数据）。 */
export interface DynamicOptions {
  /** narration.list_styles 的风格目录（不含「自动匹配」，由 spec 自己置顶）。 */
  readonly styles: readonly Option[];
  /** subtitle.list_presets 的预设目录；取不到时为空数组，控件照实显示当前值。 */
  readonly presets: readonly Option[];
}

const ANALYSIS_SECTION: SectionSpec = {
  id: 'analysis',
  title: '智能分析',
  fields: [
    {
      key: 'analysis.prescreen_threshold',
      label: '预筛入选阈值',
      type: 'number',
      min: 0,
      max: 100,
      help: '预筛综合分 ≥ 阈值的集推荐进入全量分析',
    },
    {
      key: 'analysis.full_threshold',
      label: '自动全量分析集数上限',
      type: 'number',
      min: 1,
      max: 80,
      help: '导入扫集后：集数 ≤ 此值则自动全量分析；超过则先预筛，只分析推荐集。改完对下一次导入生效。',
    },
  ],
};

function productionSection(dynamic: DynamicOptions): SectionSpec {
  return {
    id: 'production',
    title: '生产线默认值',
    fields: [
      {
        key: 'narration.variants_per_mode',
        label: '每个模式出几条方案 (K)',
        type: 'number',
        min: 1,
        max: 8,
        help: '出片中心「每个模式 N 条」的初值；不显式传 K 时服务端也按这个数出方案',
      },
      {
        key: 'narration.style_id',
        label: '解说风格默认',
        type: 'select',
        help: '与出片中心的风格选择器同键同源；改动对下一次规划生效',
        options: () => [{ label: '自动匹配（推荐）', value: 'auto' }, ...dynamic.styles],
      },
    ],
  };
}

/** 字幕分区：只放真有消费端的键（export 渲染时取 default_preset 烧录内封字幕）。 */
function subtitleSection(dynamic: DynamicOptions): SectionSpec {
  return {
    id: 'subtitle',
    title: '字幕',
    fields: [
      {
        key: 'subtitle.default_preset',
        label: '内封字幕默认预设',
        type: 'select',
        help: '出片时烧录内封字幕所用的预设；预设目录取不到时此处照实显示当前值',
        options: () => dynamic.presets,
      },
    ],
  };
}

const EXPORT_SECTION: SectionSpec = {
  id: 'export',
  title: '出片',
  fields: [
    {
      key: 'export.loudness_target_lufs',
      label: '成片响度目标 (LUFS)',
      type: 'number',
      min: -24,
      max: -6,
      help: '整片两遍归一的落点；移动端短剧建议 -16 ~ -12。数值越大越响，过大只会让平台压得更狠',
    },
    {
      key: 'export.loudness_true_peak_dbtp',
      label: '真峰值上限 (dBTP)',
      type: 'number',
      min: -6,
      max: 0,
      help: '防爆音的天花板，一般不用改',
    },
    {
      key: 'export.encoder',
      label: '视频编码',
      type: 'select',
      help: '自动=检测到 NVIDIA 显卡时 GPU 编码（NVENC），否则纯 CPU',
      options: () => [
        { label: '自动（推荐）', value: 'auto' },
        { label: 'NVIDIA GPU（NVENC）', value: 'h264_nvenc' },
        { label: '纯 CPU（libx264）', value: 'libx264' },
      ],
    },
    { key: 'export.width', label: '输出宽度 (px)', type: 'number', min: 480, max: 2160 },
    { key: 'export.height', label: '输出高度 (px)', type: 'number', min: 480, max: 2160 },
  ],
};

const DOWNLOAD_SECTION: SectionSpec = {
  id: 'download',
  title: '下载加速',
  fields: [
    {
      key: 'download.hf_mirror',
      label: 'HuggingFace 镜像站',
      type: 'text',
      placeholder: 'https://hf-mirror.com',
      help: '模型下载的国内镜像；镜像站失效时可自行替换',
    },
    {
      key: 'download.ms_base',
      label: 'ModelScope 站点',
      type: 'text',
      placeholder: 'https://modelscope.cn',
    },
  ],
};

const HARDWARE_SECTION: SectionSpec = {
  id: 'hardware',
  title: '硬件',
  fields: [
    {
      key: 'hardware.max_parallel_jobs',
      label: '最大并行任务数',
      type: 'number',
      min: 1,
      max: 8,
      help: '重启服务后完全生效',
    },
  ],
};

/** 分区按使用频率排序：出片 → 生产线默认值 → 分析 → 字幕 → 下载 → 硬件（DSS §4.1）。 */
export function buildSections(dynamic: DynamicOptions): readonly SectionSpec[] {
  return [
    EXPORT_SECTION,
    productionSection(dynamic),
    ANALYSIS_SECTION,
    subtitleSection(dynamic),
    DOWNLOAD_SECTION,
    HARDWARE_SECTION,
  ];
}
