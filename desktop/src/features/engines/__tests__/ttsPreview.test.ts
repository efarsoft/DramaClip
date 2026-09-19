// 试听的前置判断：只把「点了必然听不到所选声音」的几种情况挡在按钮上，
// 其余一律交给服务端 tts.preview 的真实结论——这里不猜就绪。
import { describe, expect, it } from 'vitest';
import { previewNotice } from '../ttsPreview';

describe('previewNotice', () => {
  it('未选引擎时先选引擎', () => {
    expect(previewNotice({ engine: '', voice: 'zf_001', state: null })).toBe('先选引擎再试听');
  });

  it('没有音色时不放行：三个引擎拿到空音色都会自己挑一把', () => {
    expect(previewNotice({ engine: 'edge', voice: '', state: null })).toBe('先选音色再试听');
  });

  it('云端引擎免本地模型，直接放行', () => {
    expect(previewNotice({ engine: 'edge', voice: 'zh-CN-YunxiNeural', state: null })).toBeUndefined();
  });

  it('模型未下载时给原因，不让人点了才知道', () => {
    expect(previewNotice({ engine: 'kokoro', voice: 'zf_001', state: 'missing' })).toMatch('未下载');
  });

  it('引擎未接入时给原因（储备资产不能出声）', () => {
    expect(previewNotice({ engine: 'kokoro', voice: 'zf_001', state: 'reserve' })).toMatch('未接入');
  });

  it('已落盘但没体检过的放行：体检结论由服务端合成时才见分晓', () => {
    expect(previewNotice({ engine: 'kokoro', voice: 'zf_001', state: 'unverified' })).toBeUndefined();
    expect(previewNotice({ engine: 'kokoro', voice: 'zf_001', state: 'ready' })).toBeUndefined();
  });
});
