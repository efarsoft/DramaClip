// 待办清单三档（§10.2/§10.5）：现象 + 后果的文案必须能回溯到判据与账本，
// 动作由 RepairActions 按判据召唤——这份清单只供料，不自己造话。
import { describe, expect, it } from 'vitest';
import { attentionAssets } from '../assetState';
import { model, report, reportsOf, selftestOk, selftestsOf } from './fixtures';

const medium = model({
  model_id: 'faster-whisper-medium',
  kind: 'asr',
  engine: 'faster_whisper',
  name: 'Whisper Medium',
});

const mediumReport = report({
  model_id: 'faster-whisper-medium',
  kind: 'asr',
  engine: 'faster_whisper',
});

describe('attentionAssets · 三档定性', () => {
  it('体检 fail → severity=fail，现象取后端判据原文，后果说清「切过去会失败」', () => {
    const broken = report({
      model_id: 'faster-whisper-medium',
      kind: 'asr',
      engine: 'faster_whisper',
      ok: false,
      checks: [{ name: '必需文件齐全', status: 'fail', detail: '缺 config.json' }],
    });
    const [item] = attentionAssets([medium], reportsOf(broken));
    expect(item?.severity).toBe('fail');
    expect(item?.note).toContain('缺 config.json');
    expect(item?.consequence).toBe('现在切过去会直接失败');
    expect(item?.tab).toBe('asr');
  });

  it('未校验 → unconfirmed「没有证据能用」；校验过没自检 → unconfirmed「没证实能加载」', () => {
    const [unverified] = attentionAssets([medium], reportsOf());
    expect(unverified?.severity).toBe('unconfirmed');
    expect(unverified?.note).toContain('未校验');
    expect(unverified?.report).toBeUndefined();

    const [tested] = attentionAssets([medium], reportsOf(mediumReport));
    expect(tested?.severity).toBe('unconfirmed');
    expect(tested?.note).toContain('自检还没跑过');
  });

  it('自检跑过但没过 → unconfirmed，现象带自检失败的原话', () => {
    const failed = selftestsOf([
      'faster-whisper-medium',
      { ok: false, error: '加载/推理失败：RuntimeError: cuDNN 找不到' },
    ]);
    const [item] = attentionAssets([medium], reportsOf(mediumReport), failed);
    expect(item?.severity).toBe('unconfirmed');
    expect(item?.note).toContain('cuDNN 找不到');
  });

  it('校验+自检都过但有 warn → warn 档，现象取 warn 判据原文（192MB 残留这级）', () => {
    const warnReport = report({
      model_id: 'faster-whisper-medium',
      kind: 'asr',
      engine: 'faster_whisper',
      checks: [
        { name: '必需文件齐全', status: 'pass' },
        { name: '中断残留', status: 'warn', detail: '1 个 .incomplete 文件，共 192 MB' },
      ],
    });
    const [item] = attentionAssets(
      [medium],
      reportsOf(warnReport),
      selftestsOf(['faster-whisper-medium', selftestOk()]),
    );
    expect(item?.severity).toBe('warn');
    expect(item?.note).toContain('192 MB');
    expect(item?.consequence).toBe('不影响推理，但占磁盘或存疑');
  });
});

describe('attentionAssets · 进清单的门槛与排序', () => {
  it('两层全过且无 warn → 不进清单；没落盘/储备档也不进（各有说法，不混进待办）', () => {
    expect(
      attentionAssets([medium], reportsOf(mediumReport), selftestsOf(['faster-whisper-medium', selftestOk()])),
    ).toHaveLength(0);
    expect(attentionAssets([model({ status: 'not_installed', size_bytes: 0 })], reportsOf())).toHaveLength(0);
    expect(attentionAssets([model({ engine_ready: false })], reportsOf())).toHaveLength(0);
  });

  it('排序按严重度：fail 在 unconfirmed 前，unconfirmed 在 warn 前', () => {
    const broken = model({ model_id: 'broken-tts', name: 'Broken' });
    const warnModel = model({ model_id: 'warn-tts', name: 'Warny' });
    const warnReport = report({
      model_id: 'warn-tts',
      checks: [
        { name: '必需文件齐全', status: 'pass' },
        { name: '中断残留', status: 'warn', detail: '共 8 MB' },
      ],
    });
    const failReport = report({
      model_id: 'broken-tts',
      ok: false,
      checks: [{ name: '权重非空', status: 'fail', detail: '权重是 0 字节' }],
    });
    const items = attentionAssets(
      [warnModel, model(), broken],
      reportsOf(warnReport, failReport),
      selftestsOf(['warn-tts', selftestOk()]),
    );
    expect(items.map((item) => item.severity)).toEqual(['fail', 'unconfirmed', 'warn']);
    expect(items.map((item) => item.model.model_id)).toEqual(['broken-tts', 'kokoro-82m', 'warn-tts']);
  });
});
