/** SRT 产物读取面：逐句时间视图的数据来源（写出侧唯一实现处 `service/dramaclip/engines/subtitle/srt.py`）。 */
export interface Cue {
  readonly start: number;
  readonly end: number;
  readonly text: string;
}

const STAMP = /^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/;

/** 时间码 → 秒；分秒越界（如 99:99:99）判为不合规，宁缺毋假。 */
function toSeconds(raw: string): number | null {
  const matched = STAMP.exec(raw.trim());
  if (matched === null) return null;
  const [, hour, minute, second, milli] = matched;
  if (Number(minute) > 59 || Number(second) > 59) return null;
  return Number(hour) * 3600 + Number(minute) * 60 + Number(second) + Number(milli) / 1000;
}

export function parseSrt(content: string): Cue[] {
  const cues: Cue[] = [];
  for (const block of content.replaceAll('\r\n', '\n').split(/\n{2,}/)) {
    const lines = block.split('\n');
    if (/^\s*\d+\s*$/.test(lines[0] ?? '')) lines.shift();
    const [left, right] = (lines.shift() ?? '').split('-->');
    if (left === undefined || right === undefined) continue;
    const start = toSeconds(left);
    const end = toSeconds(right);
    if (start === null || end === null) continue;
    const text = lines.map((line) => line.trim()).filter((line) => line !== '').join('\n');
    if (text === '') continue;
    cues.push({ start, end, text });
  }
  return cues;
}

/** 秒 → 展示用时间戳：不满一小时给 m:ss，满一小时给 h:mm:ss（同成片详情页时长口径）。 */
export function formatStamp(seconds: number): string {
  const total = Math.max(Math.floor(seconds), 0);
  const hour = Math.floor(total / 3600);
  const minute = Math.floor((total % 3600) / 60);
  const second = total % 60;
  const stamp = `${String(minute).padStart(hour > 0 ? 2 : 1, '0')}:${String(second).padStart(2, '0')}`;
  return hour > 0 ? `${String(hour)}:${stamp}` : stamp;
}

/**
 * 成片路径 → 同名 `.srt` 旁挂产物路径；空串原样返回（「没有时间轴」不是失败）。
 *
 * 走路径约定而不是新增协议字段：两侧（工具箱 copy.srt / 成片 output.srt）都由
 * 各自的写出函数落在产物同名位置，界面少一个要维护的账本字段。
 */
export function sidecarSrtPath(outputPath: string): string {
  if (outputPath === '') return '';
  const slash = Math.max(outputPath.lastIndexOf('/'), outputPath.lastIndexOf('\\'));
  const dot = outputPath.indexOf('.', slash + 1);
  return `${dot === -1 ? outputPath : outputPath.slice(0, dot)}.srt`;
}
