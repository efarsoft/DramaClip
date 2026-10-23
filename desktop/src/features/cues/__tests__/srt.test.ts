/** SRT 解析：逐句时间轴视图的数据来源（后端 `engines/subtitle/srt.py` 的 `format_srt` 产物）。 */
import { describe, expect, it } from 'vitest';
import { formatStamp, parseSrt, sidecarSrtPath } from '../srt';

describe('parseSrt', () => {
  it('标准块解析出起止秒与文本', () => {
    const cues = parseSrt(
      '1\n00:00:01,234 --> 00:00:03,500\n皇后变卖首饰\n\n2\n00:01:10,000 --> 00:01:12,000\n才凑出五千两\n',
    );
    expect(cues).toHaveLength(2);
    expect(cues[0]?.start).toBeCloseTo(1.234, 3);
    expect(cues[0]?.end).toBeCloseTo(3.5, 3);
    expect(cues[0]?.text).toBe('皇后变卖首饰');
    expect(cues[1]?.start).toBeCloseTo(70, 3);
    expect(cues[1]?.text).toBe('才凑出五千两');
  });

  it('块内多行文本保留换行：OCR 分行是有意产物', () => {
    const cues = parseSrt('1\n00:00:00,000 --> 00:00:02,000\n第一行\n第二行\n');
    expect(cues).toHaveLength(1);
    expect(cues[0]?.text).toBe('第一行\n第二行');
  });

  it('CRLF 与块间空行不影响解析', () => {
    const cues = parseSrt('1\r\n00:00:05,000 --> 00:00:06,000\r\n句子一\r\n\r\n2\r\n00:00:08,000 --> 00:00:09,000\r\n句子二\r\n');
    expect(cues.map((cue) => cue.text)).toEqual(['句子一', '句子二']);
    expect(cues[0]?.start).toBeCloseTo(5, 3);
  });

  it('缺序号（首行即时间码）仍能解析', () => {
    const cues = parseSrt('00:00:02,000 --> 00:00:04,000\n没有时间码序号\n');
    expect(cues).toHaveLength(1);
    expect(cues[0]?.text).toBe('没有时间码序号');
  });

  it('时间码不合规的块跳过，其余保留', () => {
    const cues = parseSrt('1\n99:99:99,999 --> 00:00:03,000\n坏块\n\n2\n00:00:07,000 --> 00:00:08,000\n好块\n');
    expect(cues.map((cue) => cue.text)).toEqual(['好块']);
  });

  it('空内容与纯空白返回空列表', () => {
    expect(parseSrt('')).toEqual([]);
    expect(parseSrt('\n\n   \n')).toEqual([]);
  });
});

describe('formatStamp', () => {
  it('整秒与进位都按 m:ss 给', () => {
    expect(formatStamp(0)).toBe('0:00');
    expect(formatStamp(5.4)).toBe('0:05');
    expect(formatStamp(70)).toBe('1:10');
    expect(formatStamp(3725.9)).toBe('1:02:05');
  });
});

describe('sidecarSrtPath', () => {
  it('成片同名换 .srt：旁挂产物靠约定推出，不占协议字段', () => {
    expect(sidecarSrtPath('D:/data/outputs/p1/film_a1b2c3.mp4')).toBe(
      'D:/data/outputs/p1/film_a1b2c3.srt',
    );
    expect(sidecarSrtPath('C:\\data\\outputs\\替嫁新娘_成片.mkv')).toBe(
      'C:\\data\\outputs\\替嫁新娘_成片.srt',
    );
  });

  it('目录名里的点不算扩展名', () => {
    expect(sidecarSrtPath('D:/v1.0/build/film')).toBe('D:/v1.0/build/film.srt');
  });

  it('没有成片路径就没有时间轴：空串原样返回（不是失败）', () => {
    expect(sidecarSrtPath('')).toBe('');
  });
});
