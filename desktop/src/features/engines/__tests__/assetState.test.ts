// 资产状态：UI 上每一句「就绪 / 缺模型 / 不完整 / 待接入」都必须能回溯到
// models.list 的 engine_ready + status + size_bytes 与 models.verify 的体检结论，
// 而不是前端写死的常量（那是 P1 缺陷的成因）。
import { describe, expect, it } from 'vitest';
import type { ModelInfo } from '@dramaclip/protocol';
import {
  activateById,
  activateSettings,
  activeAsset,
  assetState,
  canActivate,
  deleteNote,
  externalAssets,
  failureNote,
  formatBytes,
  partitionAssets,
  stateLabel,
  warnCount,
  warnNote,
  warnSummary,
} from '../assetState';
import { externalRecord, importRecord, model, report, selftestOk } from './fixtures';

describe('assetState', () => {
  it('已装 + 引擎接入 + 校验通过 + 自检通过 → ready（唯一能报「就绪」的组合，§10.1）', () => {
    expect(assetState(model(), report(), selftestOk())).toBe('ready');
  });

  it('校验通过但自检没过/没跑 → untested：文件在 ≠ 能推，不冒充就绪', () => {
    expect(assetState(model(), report())).toBe('untested');
    expect(assetState(model(), report(), { ok: false, error: 'cuDNN 找不到' })).toBe('untested');
    expect(stateLabel('untested')).toBe('待自检');
  });

  it('已装但体检不通过 → incomplete（自检救不了文件层的 fail）', () => {
    const broken = report({
      ok: false,
      checks: [
        { name: '必需文件齐全', status: 'fail', detail: '缺 3 项：tokenizer.json' },
        { name: '权重完整', status: 'fail', detail: '疑似下载中断' },
      ],
    });
    expect(assetState(model(), broken, selftestOk())).toBe('incomplete');
    expect(canActivate(model(), broken)).toBe(false);
  });

  it('引擎未接入 → reserve，且装没装都不能生效', () => {
    const wired = model({ engine_ready: false });
    expect(assetState(wired, report({ engine_ready: false }))).toBe('reserve');
    expect(assetState(wired, undefined)).toBe('reserve');
    expect(canActivate(wired, report({ engine_ready: false }))).toBe(false);
  });

  it('验收用例：目录被改名后 status 变 not_installed → 缺模型且不得生效', () => {
    const movedAway = model({ status: 'not_installed', size_bytes: 0 });
    expect(assetState(movedAway, undefined)).toBe('missing');
    expect(stateLabel('missing')).toBe('缺模型');
    expect(canActivate(movedAway, undefined)).toBe(false);
  });

  it('未校验 → unverified：不冒充就绪，也不给「选为生效」（§10.1 缺陷 4：绿灯必须有证据）', () => {
    expect(assetState(model(), undefined)).toBe('unverified');
    expect(canActivate(model(), undefined)).toBe(false);
  });

  it('warn 级异常不禁用生效（残留/无从对账照样可选），fail 才禁', () => {
    const withWarn = report({
      ok: true,
      checks: [{ name: '中断残留', status: 'warn', detail: '1 个 .incomplete（192MB）' }],
    });
    expect(canActivate(model(), withWarn)).toBe(true);
  });
});

describe('failureNote', () => {
  it('汇总 fail 项供横幅使用', () => {
    const note = failureNote(
      report({
        ok: false,
        checks: [
          { name: '必需文件齐全', status: 'fail', detail: '缺 3 项' },
          { name: '依赖组', status: 'pass' },
        ],
      }),
    );
    expect(note).toContain('必需文件齐全');
    expect(note).not.toContain('依赖组');
  });

  it('通过或未体检 → undefined', () => {
    expect(failureNote(report())).toBeUndefined();
    expect(failureNote(undefined)).toBeUndefined();
  });
});

describe('warn 上卡（§10.1 降级的另一半：可见 + 有修法）', () => {
  const withWarns = report({
    ok: true,
    checks: [
      { name: '中断残留', status: 'warn', detail: '1 个 .incomplete 半截文件（192MB）' },
      { name: '唯一路径', status: 'warn', detail: '另有 1 处同名缓存', paths: ['D:\\x'] },
      { name: '权重非空', status: 'pass' },
    ],
  });

  it('warnCount/warnSummary：只数 warn，摘要只列判据名（行内窄）', () => {
    expect(warnCount(withWarns)).toBe(2);
    expect(warnSummary(withWarns)).toBe('2 项待修：中断残留、唯一路径');
    expect(warnCount(report())).toBe(0);
    expect(warnSummary(undefined)).toBeUndefined();
  });

  it('warnNote：详情带后端原话，供 title 展开', () => {
    expect(warnNote(withWarns)).toContain('192MB');
    expect(warnNote(report())).toBeUndefined();
  });
});

describe('partitionAssets', () => {
  it('按 engine_ready 分「可用 / 储备」，而不是按下载进度', () => {
    const { usable, reserve } = partitionAssets([
      model(),
      model({ model_id: 'indextts2', engine: 'indextts2', engine_ready: false }),
    ]);
    expect(usable.map((m) => m.model_id)).toEqual(['kokoro-82m']);
    expect(reserve.map((m) => m.model_id)).toEqual(['indextts2']);
  });

  it('储备项下载完成后仍留在储备分区（除非 engine_ready 真变了）', () => {
    const reserveModel = model({ model_id: 'indextts2', engine_ready: false });
    expect(partitionAssets([reserveModel]).usable).toHaveLength(0);
  });
});

describe('formatBytes', () => {
  it('0 显示破折号，不留个假的 0GB', () => {
    expect(formatBytes(0)).toBe('—');
  });

  it('不足 1GB 用 MB，其余用 GB 两位小数', () => {
    expect(formatBytes(480 * 1024 * 1024)).toBe('480MB');
    expect(formatBytes(630783979)).toBe('602MB');
    expect(formatBytes(1024 ** 3)).toBe('1.00GB');
    expect(formatBytes(9.75 * 1024 ** 3)).toBe('9.75GB');
  });
});

describe('activateSettings', () => {
  const whisper = (tier: string): ModelInfo =>
    model({
      model_id: `faster-whisper-${tier}`,
      kind: 'asr',
      engine: 'faster_whisper',
      name: `Whisper ${tier}`,
    });

  it('whisper 档位写回 asr.model 短名，且能被 activeAsset 原样找回（往返闭合）', () => {
    for (const tier of ['base', 'small', 'medium', 'large-v3']) {
      const item = whisper(tier);
      const values = activateSettings(item);
      expect(values).toEqual({ 'asr.engine': 'faster_whisper', 'asr.model': tier });
      expect(activeAsset([item], 'asr', values)?.model_id).toBe(item.model_id);
    }
  });

  it('非 whisper 的 ASR 引擎按引擎名生效（sensevoice 没有档位）', () => {
    const item = model({ model_id: 'sensevoice-small', kind: 'asr', engine: 'sensevoice' });
    const values = activateSettings(item);
    expect(values).toEqual({ 'asr.engine': 'sensevoice' });
    expect(activeAsset([item], 'asr', values)?.model_id).toBe('sensevoice-small');
  });

  it('TTS 生效写回的是引擎名，并能用同一份设置找回这件资产', () => {
    const item = model({ kind: 'tts' });
    const values = activateSettings(item);
    expect(values).toEqual({ 'tts.engine': 'kokoro' });
    expect(activeAsset([item], 'tts', values)?.model_id).toBe('kokoro-82m');
  });
});

describe('本地导入的两种货：清单内多一个来源标记，清单外另起一组', () => {
  it('只有认不出身份的登记算「外部资产」，且按能力分到本域', () => {
    const records = [
      importRecord(),
      externalRecord({ kind: 'tts' }),
      externalRecord({ model_id: 'faster-whisper-medium' }),
      externalRecord(),
    ];

    expect(externalAssets(records, 'asr')).toEqual([externalRecord()]);
  });

  it('删除提示按落位方式说真话：搬进库的删文件，只登记的不动业主的盘', () => {
    expect(deleteNote(model())).toBe('删除后可随时重新下载。');
    expect(deleteNote(model({ imported: importRecord() }))).toContain('库里这一份');
    expect(deleteNote(model({ imported: importRecord({ mode: 'move' }) }))).toContain('库里这一份');
    expect(deleteNote(model({ imported: externalRecord() }))).toContain('自己盘上');
  });

  it('向导交回的 model_id 折算成设置值；库里查不到这一行就不猜', () => {
    expect(activateById([model()], 'kokoro-82m')).toEqual({ 'tts.engine': 'kokoro' });
    expect(activateById([], 'kokoro-82m')).toBeNull();
  });
});
