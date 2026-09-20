/** 引擎音色目录：每个引擎的音色体系互不相通，故按引擎独立成键存储。
 *
 * Kokoro 名单 = 模型 voices/ 目录实际存在的中文音色（55 女 + 45 男）；
 * Edge 为微软官方中文音色名。这张表跟着 TTS 工厂的 ``supported()`` 走：
 * 工厂撤下一个引擎，这里必须一起撤，否则下拉能把业主送到一条造不出声的路上了。
 */
import type { DefaultOptionType } from 'antd/es/select';

export type TtsEngineName = 'kokoro' | 'edge';

export const TTS_ENGINES: readonly TtsEngineName[] = ['kokoro', 'edge'];

/** 不需要本地模型的引擎：Edge 走云端，故它没有「缺模型」这一态。其余引擎一律以资产为准。 */
export const TTS_MODEL_FREE_ENGINES: readonly TtsEngineName[] = ['edge'];

/** 引擎短名 → 展示名（设置值只有短名，UI 上说短名等于让人猜）。 */
export const TTS_ENGINE_LABEL: Record<TtsEngineName, string> = {
  kokoro: 'Kokoro 82M',
  edge: 'Edge',
};

/** 设置值 → 展示名；未登记引擎原样回显（不编名字）。 */
export function ttsEngineLabel(engine: string): string {
  return (TTS_ENGINE_LABEL as Record<string, string>)[engine] ?? engine;
}

/** 免本地模型的引擎（云端）：这类引擎没有「缺模型」这一态。 */
export function isModelFreeEngine(engine: string): boolean {
  return (TTS_MODEL_FREE_ENGINES as readonly string[]).includes(engine);
}

/** 设置值 → 该引擎的音色下拉；未登记的引擎没有音色可给。 */
export function voiceOptions(engine: string): DefaultOptionType[] {
  return (TTS_VOICE_OPTIONS as Record<string, DefaultOptionType[]>)[engine] ?? [];
}

/** 引擎 → 音色设置键。切换引擎互不覆盖各自的音色选择。 */
export function voiceSettingKey(engine: string): string {
  return `tts.voice.${engine}`;
}

function female(ids: string[]): { label: string; value: string }[] {
  return ids.map((id) => ({ label: `${id} · 女声`, value: id }));
}
function male(ids: string[]): { label: string; value: string }[] {
  return ids.map((id) => ({ label: `${id} · 男声`, value: id }));
}

const KOKORO_FEMALE_IDS = [
  'zf_001', 'zf_002', 'zf_003', 'zf_004', 'zf_005', 'zf_006', 'zf_007', 'zf_008',
  'zf_017', 'zf_018', 'zf_019', 'zf_021', 'zf_022', 'zf_023', 'zf_024', 'zf_026',
  'zf_027', 'zf_028', 'zf_032', 'zf_036', 'zf_038', 'zf_039', 'zf_040', 'zf_042',
  'zf_043', 'zf_044', 'zf_046', 'zf_047', 'zf_048', 'zf_049', 'zf_051', 'zf_059',
  'zf_060', 'zf_067', 'zf_070', 'zf_071', 'zf_072', 'zf_073', 'zf_074', 'zf_075',
  'zf_076', 'zf_077', 'zf_078', 'zf_079', 'zf_083', 'zf_084', 'zf_085', 'zf_086',
  'zf_087', 'zf_088', 'zf_090', 'zf_092', 'zf_093', 'zf_094', 'zf_099',
];
const KOKORO_MALE_IDS = [
  'zm_009', 'zm_010', 'zm_011', 'zm_012', 'zm_013', 'zm_014', 'zm_015', 'zm_016',
  'zm_020', 'zm_025', 'zm_029', 'zm_030', 'zm_031', 'zm_033', 'zm_034', 'zm_035',
  'zm_037', 'zm_041', 'zm_045', 'zm_050', 'zm_052', 'zm_053', 'zm_054', 'zm_055',
  'zm_056', 'zm_057', 'zm_058', 'zm_061', 'zm_062', 'zm_063', 'zm_064', 'zm_065',
  'zm_066', 'zm_068', 'zm_069', 'zm_080', 'zm_081', 'zm_082', 'zm_089', 'zm_091',
  'zm_095', 'zm_096', 'zm_097', 'zm_098', 'zm_100',
];

const EDGE_VOICES: { label: string; value: string }[] = [
  { label: '晓晓 · 女声（温暖）', value: 'zh-CN-XiaoxiaoNeural' },
  { label: '晓伊 · 女声', value: 'zh-CN-XiaoyiNeural' },
  { label: '云希 · 男声', value: 'zh-CN-YunxiNeural' },
  { label: '云扬 · 男声（播音）', value: 'zh-CN-YunyangNeural' },
  { label: '云健 · 男声（激情）', value: 'zh-CN-YunjianNeural' },
  { label: '云夏 · 男声（少年）', value: 'zh-CN-YunxiaNeural' },
  { label: '晓北 · 女声（东北）', value: 'zh-CN-liaoning-XiaobeiNeural' },
  { label: '晓妮 · 女声（陕西）', value: 'zh-CN-shaanxi-XiaoniNeural' },
  { label: '曉佳 · 女声（粤语）', value: 'zh-HK-HiuGaaiNeural' },
  { label: '曉曼 · 女声（粤语）', value: 'zh-HK-HiuMaanNeural' },
  { label: '雲龍 · 男声（粤语）', value: 'zh-HK-WanLungNeural' },
  { label: '曉臻 · 女声（台湾）', value: 'zh-TW-HsiaoChenNeural' },
  { label: '雲哲 · 男声（台湾）', value: 'zh-TW-YunJheNeural' },
  { label: '曉雨 · 女声（台湾）', value: 'zh-TW-HsiaoYuNeural' },
];

export const TTS_VOICE_OPTIONS: Record<TtsEngineName, DefaultOptionType[]> = {
  kokoro: [
    { label: '女声', options: female(KOKORO_FEMALE_IDS) },
    { label: '男声', options: male(KOKORO_MALE_IDS) },
  ],
  edge: EDGE_VOICES,
};
