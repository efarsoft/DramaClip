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
  /** 取数故障行：原因常驻可见文本 + 就地重试，不静默吞成空目录（规格 H3 §3.2.2）。 */
  readonly problem?: { readonly text: string; readonly onRetry: () => void };
}

export interface SectionSpec {
  readonly id: string;
  readonly title: string;
  readonly fields: readonly FieldSpec[];
}

/** 目录类选项的注入源（SettingsPage 异步取回后传入，spec 本身保持纯数据）。 */
export type CatalogName = 'styles' | 'presets';

export interface DynamicOptions {
  /** narration.list_styles 的风格目录（不含「自动匹配」，由 spec 自己置顶）。 */
  readonly styles: readonly Option[];
  /** subtitle.list_presets 的预设目录；取不到时为空数组，控件不编选项。 */
  readonly presets: readonly Option[];
  /** 目录取不到的原话（空串＝取到了）。裸 id 不能冒充名字，故障要说在可见文本里并可重试（规格 H3 §3.2.2）。 */
  readonly problems: Readonly<Record<CatalogName, string>>;
  readonly retry: (catalog: CatalogName) => void;
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

/** 目录取不到时的故障行规格；取到了（空串）就没有这一行——空目录不能伪装成「库里没东西」。 */
function problemOf(
  catalog: CatalogName,
  label: string,
  dynamic: DynamicOptions,
): { text: string; onRetry: () => void } | undefined {
  const problem = dynamic.problems[catalog];
  return problem === ''
    ? undefined
    : {
        text: `${label}取不到：${problem}`,
        onRetry: () => {
          dynamic.retry(catalog);
        },
      };
}

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
        problem: problemOf('styles', '风格目录', dynamic),
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
        help: '出片时烧录内封字幕所用的预设（取不到目录时此处会另起一行说明）',
        options: () => dynamic.presets,
        problem: problemOf('presets', '预设目录', dynamic),
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
      help: '自动=按平台真试编选择硬编（NVENC / AMF / QSV / VideoToolbox），全不可用才 libx264；固定编码器不探测，失败会按段级回退并在回执中写明',
      options: () => [
        { label: '自动（推荐）', value: 'auto' },
        { label: 'NVIDIA GPU（NVENC）', value: 'h264_nvenc' },
        { label: 'AMD GPU（AMF）', value: 'h264_amf' },
        { label: 'Intel 核显（QSV）', value: 'h264_qsv' },
        { label: '纯 CPU（libx264）', value: 'libx264' },
      ],
    },
    // 画布跟随源画幅（ADR-010）：这两个键只是**上限**，不是成片尺寸——横屏源出 16:9、
    // 竖屏源出 9:16，不足处补黑。label 若写成「输出宽度」就是在承诺一个已经不存在的固定尺寸。
    {
      key: 'export.width',
      label: '画布宽上限 (px)',
      type: 'number',
      min: 480,
      max: 2160,
      help: '成片画幅跟随源视频（横屏源出 16:9、竖屏源出 9:16），这里只定大小上限',
    },
    { key: 'export.height', label: '画布高上限 (px)', type: 'number', min: 480, max: 2160 },
    // AI 生成标注（业主裁决 2026-10-15）：用户开关、默认关闭——平台标注要求因平台
    // 而异，是否标注由使用者按发布平台自行决定。开启后成片右上角烧「AI 生成」。
    {
      key: 'export.ai_label',
      label: 'AI 生成标注',
      type: 'switch',
      help: '开启后成片右上角烧制「AI 生成」字样；部分平台对 AI 合成内容有标注要求。默认关闭，由你按发布平台自行决定',
    },
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

/** Agent 网关：本机回环 HTTP 工具面（外部 agent 调用文案审查与标题出稿）。 */
const AGENT_GATEWAY_SECTION: SectionSpec = {
  id: 'agent-gateway',
  title: 'Agent 网关',
  fields: [
    {
      key: 'agent_gateway.enabled',
      label: '启用 Agent 网关',
      type: 'switch',
      help: '在本机 127.0.0.1 起 HTTP 工具面，外部 agent 可调用文案审查与标题出稿；保存后立即生效',
    },
    {
      key: 'agent_gateway.port',
      label: '端口',
      type: 'number',
      min: 1024,
      max: 65535,
      help: '监听端口；改动保存即重启监听',
    },
    {
      key: 'agent_gateway.token',
      label: '访问 Token',
      type: 'password',
      help: '调用方携带 Authorization: Bearer <token>；留空保存时自动生成并回填；显示为掩码，原样保存不会覆写',
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

/** 分区按使用频率排序：出片 → 生产线默认值 → 分析 → 字幕 → Agent 网关 → 下载 → 硬件（DSS §4.1）。 */
export function buildSections(dynamic: DynamicOptions): readonly SectionSpec[] {
  return [
    EXPORT_SECTION,
    productionSection(dynamic),
    ANALYSIS_SECTION,
    subtitleSection(dynamic),
    AGENT_GATEWAY_SECTION,
    DOWNLOAD_SECTION,
    HARDWARE_SECTION,
  ];
}
