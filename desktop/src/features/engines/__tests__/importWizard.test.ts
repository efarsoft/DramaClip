// 导入向导的判据层：第 ②→③ 步的闸门、可选落位方式、提交负载。
//
// 这里只翻译 models.import_inspect 的实测字段，不重复实现「能不能导入」——真正的判据在
// 服务端 importer 那一处。所以每条断言都写在「业主没做什么选择」上，而不是「文件缺什么」。
import { describe, expect, it } from 'vitest';
import type { ImportDraft } from '../importWizard';
import {
  activatableAfterImport,
  commitPayload,
  emptyDraft,
  effectiveMode,
  failedCheckNames,
  gateBlock,
  landedRecord,
  modeChoices,
  modeHint,
} from '../importWizard';
import { externalInspection as external, importRecord, inspection } from './fixtures';

function draft(over: Partial<ImportDraft> = {}): ImportDraft {
  return { ...emptyDraft(), ...over };
}

describe('第 ② 步闸门', () => {
  it('体检通过且库里没有同一件资产时直接放行', () => {
    expect(gateBlock(draft(), inspection())).toBeUndefined();
  });

  it('体检不通过就没法进第 ③ 步，且说的是缺哪几项', () => {
    const blocked = inspection({
      ok: false,
      checks: [{ name: '必需文件', status: 'fail', detail: '缺 tokenizer.json' }],
    });

    expect(gateBlock(draft(), blocked)).toMatch(/必需文件/);
  });

  it('业主显式勾选「按现状导入并标记为不完整」后放行，这是唯一开口', () => {
    const blocked = inspection({
      ok: false,
      checks: [{ name: '必需文件', status: 'fail', detail: '缺 tokenizer.json' }],
    });

    expect(gateBlock(draft({ allowIncomplete: true }), blocked)).toBeUndefined();
  });

  it('库里已有同一件资产时先要裁决冲突，三种判法都没选就拦住', () => {
    const clash = inspection({
      conflict: { model_id: 'faster-whisper-medium', path: 'D:\\models\\asr', size_bytes: 2_100_000_000, ok: false },
    });

    expect(gateBlock(draft(), clash)).toMatch(/冲突/);
    for (const verdict of ['overwrite', 'merge', 'coexist'] as const) {
      expect(gateBlock(draft({ onConflict: verdict }), clash)).toBeUndefined();
    }
  });

  it('仅登记不碰库内那一份，所以冲突不需要裁决', () => {
    const clash = inspection({
      conflict: { model_id: 'faster-whisper-medium', path: 'D:\\models\\asr', size_bytes: 1, ok: true },
    });

    expect(gateBlock(draft({ mode: 'register' }), clash)).toBeUndefined();
  });

  it('未识别的目录必须先声明能力，不声明就不给过', () => {
    expect(gateBlock(draft({ mode: 'register' }), external())).toMatch(/能力/);
    expect(gateBlock(draft({ mode: 'register', externalKind: 'asr' }), external())).toBeUndefined();
  });

  it('未识别时闸门按「仅登记」算：先前选过的复制方式不该反过来拦住', () => {
    expect(gateBlock(draft({ mode: 'copy', externalKind: 'asr' }), external())).toBeUndefined();
  });
});

describe('落位方式的可选项', () => {
  it('认得出身份的三种都能选', () => {
    expect(modeChoices(inspection())).toEqual(['copy', 'move', 'register']);
  });

  it('认不出身份的只有「仅登记」——placement 不知道就不许复制进库', () => {
    expect(modeChoices(external())).toEqual(['register']);
  });

  it('复制的说明带着手目标路径与目标盘余量，全部出自实测字段', () => {
    const hint = modeHint('copy', inspection());

    expect(hint).toContain('D:\\data\\models\\asr\\faster-whisper');
    expect(hint).toContain('GB');
  });

  it('未识别时不说「规范目录」，说的是登记后仍在业主自己的盘上', () => {
    expect(modeHint('register', external())).toContain(external().source_path);
  });

  it('未识别时第 ③ 步选中的就是「仅登记」，草稿里残留的复制方式不算选中', () => {
    expect(effectiveMode(draft({ mode: 'copy' }), external())).toBe('register');
    expect(effectiveMode(draft({ mode: 'move' }), inspection())).toBe('move');
  });
});

describe('提交负载', () => {
  it('默认只带 path 与 mode：没冲突没裁决时不给后端传空串', () => {
    expect(commitPayload(draft(), inspection())).toEqual({
      path: 'E:\\下载\\models--Systran--faster-whisper-medium',
      mode: 'copy',
    });
  });

  it('冲突裁决只在真有冲突时带上，不完整标记只在体检不通过时带上', () => {
    const clash = inspection({
      ok: false,
      conflict: { model_id: 'faster-whisper-medium', path: 'D:\\m', size_bytes: 1, ok: true },
    });

    expect(commitPayload(draft({ onConflict: 'merge', allowIncomplete: true }), clash)).toEqual({
      path: clash.source_path,
      mode: 'copy',
      on_conflict: 'merge',
      allow_incomplete: true,
    });
  });

  it('未识别时强制仅登记，并把能力与命名交给后端', () => {
    const given = external();

    expect(
      commitPayload(draft({ mode: 'copy', externalKind: 'tts', label: '  同事的音色  ' }), given),
    ).toEqual({
      path: given.source_path,
      mode: 'register',
      external_kind: 'tts',
      label: '同事的音色',
    });
  });

  it('空白 label 不上报：留空 = 用目录名，不是空标题', () => {
    expect(commitPayload(draft({ externalKind: 'asr', label: '   ' }), external())).not.toHaveProperty(
      'label',
    );
  });
});

describe('导入完成后', () => {
  it('内置清单里的资产可以立刻「选为生效」', () => {
    expect(activatableAfterImport(inspection())).toBe(true);
  });

  it('清单外的目录压根没有 model_id，就不给生效入口', () => {
    expect(activatableAfterImport(external())).toBe(false);
  });

  it('认得出身份但引擎还没接入：一样不给生效入口，设成生效只会让下一次分析报错', () => {
    expect(activatableAfterImport(inspection({ engine_ready: false }))).toBe(false);
  });
});

describe('不通过项清单', () => {
  it('一行说清拦住的是哪几项，warn 不算拦住', () => {
    const mixed = inspection({
      ok: false,
      checks: [
        { name: '必需文件', status: 'fail', detail: '缺 3' },
        { name: '权重尺寸对账', status: 'warn', detail: '疑似中断' },
        { name: '缓存布局', status: 'pass' },
      ],
    });

    expect(failedCheckNames(mixed)).toEqual(['必需文件']);
    expect(failedCheckNames(inspection())).toEqual([]);
  });
});

describe('完成页读的那条登记', () => {
  it('按「业主挑的那个目录」对上号，同一路径重复导入时取最新一条', () => {
    const report = inspection();
    const older = importRecord({ path: 'D:\\旧的那份', imported_at: 100 });
    const newer = importRecord({ path: 'D:\\这一次落的', imported_at: 200 });

    expect(landedRecord([older, newer], report.source_path)?.path).toBe('D:\\这一次落的');
  });

  it('登记本里没有这一路径时不编造：返回 null，完成页得另想办法说', () => {
    expect(landedRecord([importRecord()], 'E:\\别的地方')).toBeNull();
    expect(landedRecord([], 'E:\\下载')).toBeNull();
  });
});
