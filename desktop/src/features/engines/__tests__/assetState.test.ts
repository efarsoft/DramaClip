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
  assetSummary,
  canActivate,
  deleteNote,
  domainStats,
  externalAssets,
  failureNote,
  formatBytes,
  incompleteAssets,
  partitionAssets,
  stateLabel,
} from '../assetState';
import { externalRecord, importRecord, model, report, reportsOf } from './fixtures';

describe('assetState', () => {
  it('已装 + 引擎接入 + 体检通过 → ready（唯一能报「就绪」的组合）', () => {
    expect(assetState(model(), report())).toBe('ready');
  });

  it('已装但体检不通过 → incomplete（旧的「半条命」判据在这里失效）', () => {
    const broken = report({
      ok: false,
      checks: [
        { name: '必需文件齐全', status: 'fail', detail: '缺 3 项：tokenizer.json' },
        { name: '权重完整', status: 'fail', detail: '疑似下载中断' },
      ],
    });
    expect(assetState(model(), broken)).toBe('incomplete');
    expect(canActivate(model(), broken)).toBe(false);
  });

  it('引擎未接入 → reserve，且装没装都不能生效', () => {
    const wired = model({ engine_ready: false });
    expect(assetState(wired, report({ engine_ready: false }))).toBe('reserve');
    expect(assetState(wired, undefined)).toBe('reserve');
    expect(canActivate(wired, report({ engine_ready: false }))).toBe(false);
  });

  it('验收用例：sherpa 目录被改名后 status 变 not_installed → 缺模型且不得生效', () => {
    const sherpa = model({
      model_id: 'sherpa-melo-zh',
      engine: 'sherpa_melo',
      name: 'sherpa-onnx melo-zh',
      status: 'not_installed',
      size_bytes: 0,
    });
    expect(assetState(sherpa, undefined)).toBe('missing');
    expect(stateLabel('missing')).toBe('缺模型');
    expect(canActivate(sherpa, undefined)).toBe(false);
  });

  it('未体检 → unverified：已装也不冒充「就绪」', () => {
    expect(assetState(model(), undefined)).toBe('unverified');
    expect(canActivate(model(), undefined)).toBe(true);
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

describe('assetSummary', () => {
  it('已装数、实占字节、不完整数、未接入数各自独立', () => {
    const models = [
      model(),
      model({ model_id: 'faster-whisper-medium', kind: 'asr', engine: 'faster_whisper', size_bytes: 1024 }),
      model({ model_id: 'indextts2', engine: 'indextts2', engine_ready: false }),
      model({
        model_id: 'faster-whisper-small',
        kind: 'asr',
        engine: 'faster_whisper',
        status: 'not_installed',
        size_bytes: 0,
      }),
    ];
    const reports = reportsOf(report({ model_id: 'faster-whisper-medium', ok: false }));

    const summary = assetSummary(models, reports);
    // 未安装那项：既不计入已装数，也不贡献字节。
    expect(summary.installed).toBe(3);
    expect(summary.bytes).toBe(350 * 1024 * 1024 * 2 + 1024);
    expect(summary.incomplete).toBe(1);
    expect(summary.reserve).toBe(1);
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

  it('TTS 按引擎名生效，并能找回同一件资产', () => {
    const item = model({ model_id: 'sherpa-melo-zh', kind: 'tts', engine: 'sherpa_melo' });
    const values = activateSettings(item);
    expect(values).toEqual({ 'tts.engine': 'sherpa_melo' });
    expect(activeAsset([item], 'tts', values)?.model_id).toBe('sherpa-melo-zh');
  });
});

describe('incompleteAssets', () => {
  const medium = model({
    model_id: 'faster-whisper-medium',
    kind: 'asr',
    engine: 'faster_whisper',
    name: 'Whisper Medium',
  });
  const broken = report({
    model_id: 'faster-whisper-medium',
    kind: 'asr',
    engine: 'faster_whisper',
    ok: false,
    checks: [
      { name: '必需文件齐全', status: 'fail', detail: '缺 3 项：tokenizer.json' },
      { name: '唯一路径', status: 'warn', detail: '两处候选' },
    ],
  });

  it('引擎已接入 + 已装 + 体检不通过 → 进「待修」清单，带 fail 判据与落点域', () => {
    const items = incompleteAssets([model(), medium], reportsOf(broken));
    expect(items).toHaveLength(1);
    expect(items[0]?.model.name).toBe('Whisper Medium');
    expect(items[0]?.note).toContain('缺 3 项');
    expect(items[0]?.note).not.toContain('两处候选');
    expect(items[0]?.tab).toBe('asr');
  });

  it('当前没在用它也要列——一旦切过去就直接失败', () => {
    const active = model({ model_id: 'faster-whisper-small', kind: 'asr', engine: 'faster_whisper' });
    expect(activeAsset([active, medium], 'asr', { 'asr.model': 'small' })?.model_id).toBe(
      'faster-whisper-small',
    );
    expect(incompleteAssets([active, medium], reportsOf(broken))).toHaveLength(1);
  });

  it('储备项（引擎未接入）坏了不算待修：它本来就不能生效，点了也没用', () => {
    const reserve = model({ model_id: 'indextts2', engine: 'indextts2', engine_ready: false });
    const bad = report({ model_id: 'indextts2', engine: 'indextts2', engine_ready: false, ok: false });
    expect(incompleteAssets([reserve], reportsOf(bad))).toHaveLength(0);
  });

  it('没落盘的不算待修——那是缺模型，走下载而不是修复', () => {
    const missing = model({ ...medium, status: 'not_installed', size_bytes: 0 });
    expect(incompleteAssets([missing], reportsOf(broken))).toHaveLength(0);
  });
});

describe('domainStats', () => {
  const ttsModels: ModelInfo[] = [
    model({ kind: 'tts' }),
    model({ kind: 'tts', model_id: 'sherpa-melo-zh', status: 'not_installed', size_bytes: 0 }),
    model({ kind: 'tts', model_id: 'indextts2', engine: 'indextts2', engine_ready: false }),
  ];

  it('可用 = 本域引擎已接入的件数，未接入的储备项不计入', () => {
    expect(domainStats(ttsModels, reportsOf(), 'tts')).toEqual({ wired: 2, incomplete: 0 });
  });

  it('待修 = 本域体检不通过的件数，别域的不串进来', () => {
    const withAsr = [
      ...ttsModels,
      model({ kind: 'asr', model_id: 'faster-whisper-medium', engine: 'faster_whisper' }),
    ];
    const broken = report({
      model_id: 'faster-whisper-medium',
      kind: 'asr',
      engine: 'faster_whisper',
      ok: false,
    });
    expect(domainStats(withAsr, reportsOf(broken), 'asr')).toEqual({ wired: 1, incomplete: 1 });
    expect(domainStats(withAsr, reportsOf(broken), 'tts')).toEqual({ wired: 2, incomplete: 0 });
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
