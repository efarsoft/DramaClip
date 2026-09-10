/** 系统偏好设置项（引擎类配置在「引擎中心」；键权威源：service config.DEFAULTS）。 */

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
  readonly icon: string;
  readonly title: string;
  readonly fields: readonly FieldSpec[];
}

const ANALYSIS_SECTION: SectionSpec = {
  id: 'analysis',
  icon: '🎯',
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
      label: '全量分析推荐阈值',
      type: 'number',
      min: 0,
      max: 100,
    },
  ],
};

const EXPORT_SECTION: SectionSpec = {
  id: 'export',
  icon: '🎬',
  title: '出片',
  fields: [
    {
      key: 'strategy.max_duration_s',
      label: '成片目标时长上限 (秒)',
      type: 'number',
      min: 30,
      max: 1200,
      help: '编排按此预算挑选场景；推广建议 60-180，解说涨粉建议 180-300',
    },
    {
      key: 'strategy.min_duration_s',
      label: '成片最短时长 (秒)',
      type: 'number',
      min: 10,
      max: 120,
    },
  ],
};

const DOWNLOAD_SECTION: SectionSpec = {
  id: 'download',
  icon: '⬇️',
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
  icon: '⚙️',
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

/** 分区按使用频率排序：出片 → 分析 → 字幕 → 下载 → 硬件（DSS §4.1）。 */
export function buildSections(): readonly SectionSpec[] {
  return [
    EXPORT_SECTION,
    ANALYSIS_SECTION,
    DOWNLOAD_SECTION,
    HARDWARE_SECTION,
  ];
}
