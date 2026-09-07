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
  /** 稳定标识：页面据此挂接分区级行为（如 llm 的连接测试）。 */
  readonly id?: string;
  readonly title: string;
  readonly fields: readonly FieldSpec[];
}

const ANALYSIS_SECTION: SectionSpec = {
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
  title: '导出',
  fields: [
    {
      key: 'export.encoder',
      label: '编码器',
      type: 'select',
      options: () => [{ label: 'H.264', value: 'h264' }],
    },
    { key: 'export.bitrate_kbps', label: '码率 (kbps)', type: 'number', min: 1000, max: 50000 },
    { key: 'export.width', label: '宽度', type: 'number', min: 480, max: 2160 },
    { key: 'export.height', label: '高度', type: 'number', min: 480, max: 3840 },
  ],
};

const HARDWARE_SECTION: SectionSpec = {
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

function subtitleSection(presetOptions: readonly Option[]): SectionSpec {
  return {
    title: '字幕',
    fields: [
      { key: 'subtitle.default_preset', label: '默认预设', type: 'select', options: () => presetOptions },
      {
        key: 'subtitle.smart_match',
        label: '情绪智能匹配',
        type: 'switch',
        help: '按台词情绪自动微调字幕样式',
      },
    ],
  };
}

export function buildSections(presetOptions: readonly Option[]): readonly SectionSpec[] {
  return [ANALYSIS_SECTION, subtitleSection(presetOptions), EXPORT_SECTION, HARDWARE_SECTION];
}
