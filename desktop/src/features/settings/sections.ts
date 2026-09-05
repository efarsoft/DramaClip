/** 设置项声明（键与默认值权威源：service/dramaclip/infra/config.py DEFAULTS）。 */

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
  readonly title: string;
  readonly fields: readonly FieldSpec[];
}

const EDGE_VOICES: readonly Option[] = [
  { label: '云希 · 男声', value: 'zh-CN-YunxiNeural' },
  { label: '晓伊 · 女声', value: 'zh-CN-XiaoyiNeural' },
  { label: '云扬 · 男声（播音）', value: 'zh-CN-YunyangNeural' },
];

const KOKORO_VOICES: readonly Option[] = [
  { label: 'zf_001 · 女声', value: 'zf_001' },
  { label: 'zf_003 · 女声', value: 'zf_003' },
  { label: 'zm_001 · 男声', value: 'zm_001' },
  { label: 'zm_003 · 男声', value: 'zm_003' },
];

const LLM_SECTION: SectionSpec = {
  title: 'LLM 语义引擎',
  fields: [
    {
      key: 'llm.base_url',
      label: 'API 地址',
      type: 'text',
      placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      help: 'OpenAI 兼容端点；本地引擎可填 http://127.0.0.1:11434/v1（Ollama）',
    },
    { key: 'llm.api_key', label: 'API Key', type: 'password', placeholder: 'sk-…' },
    {
      key: 'llm.model',
      label: '模型名',
      type: 'text',
      placeholder: 'qwen-plus',
      help: '未配置时剧情/文案生成自动降级为关键词模式',
    },
  ],
};

const TTS_SECTION: SectionSpec = {
  title: '配音（TTS）',
  fields: [
    {
      key: 'tts.engine',
      label: '引擎',
      type: 'select',
      help: 'edge=微软云端（质量佳、需联网）；kokoro=本地离线（模型管理页下载后可用）',
      options: () => [
        { label: 'Edge · 云端', value: 'edge' },
        { label: 'Kokoro · 本地', value: 'kokoro' },
      ],
    },
    {
      key: 'tts.voice',
      label: '默认音色',
      type: 'select',
      options: (values) => (values['tts.engine'] === 'kokoro' ? KOKORO_VOICES : EDGE_VOICES),
    },
  ],
};

const ASR_SECTION: SectionSpec = {
  title: '语音识别（ASR）',
  fields: [
    {
      key: 'asr.model',
      label: '模型',
      type: 'select',
      help: 'small 精度更高（默认）；base 更快',
      options: () => [
        { label: 'small', value: 'small' },
        { label: 'base', value: 'base' },
      ],
    },
    {
      key: 'asr.device',
      label: '设备',
      type: 'select',
      help: 'GPU 需 CUDA 环境，当前默认 CPU',
      options: () => [{ label: 'CPU', value: 'cpu' }],
    },
    {
      key: 'asr.language',
      label: '语言',
      type: 'select',
      options: () => [
        { label: '中文', value: 'zh' },
        { label: '英文', value: 'en' },
      ],
    },
  ],
};

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
  return [
    LLM_SECTION,
    TTS_SECTION,
    ASR_SECTION,
    ANALYSIS_SECTION,
    subtitleSection(presetOptions),
    EXPORT_SECTION,
    HARDWARE_SECTION,
  ];
}
