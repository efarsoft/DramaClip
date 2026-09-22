// 引擎中心纯函数的共用替身：字段与 protocol 的 ModelInfo / VerifyReport / ImportInspection /
// ImportRecord / SelftestResult 同步，缺字段即 typecheck 失败——这是「UI 不得凭空造判据」的下限保障。
import type {
  ImportInspection,
  ImportRecord,
  JobInfo,
  ModelInfo,
  SelftestResult,
  VerifyReport,
} from '@dramaclip/protocol';

export function model(over: Partial<ModelInfo> = {}): ModelInfo {
  return {
    model_id: 'kokoro-82m',
    kind: 'tts',
    engine: 'kokoro',
    repo_id: 'hexgrad/Kokoro-82M-v1.1-zh',
    name: 'Kokoro 82M 中文',
    required: false,
    status: 'installed',
    engine_ready: true,
    size_bytes: 350 * 1024 * 1024,
    ...over,
  };
}

export function report(over: Partial<VerifyReport> = {}): VerifyReport {
  return {
    model_id: 'kokoro-82m',
    name: 'Kokoro 82M 中文',
    kind: 'tts',
    engine: 'kokoro',
    engine_ready: true,
    ok: true,
    checks: [{ name: '必需文件齐全', status: 'pass' }],
    ...over,
  };
}

export function reportsOf(...items: VerifyReport[]): ReadonlyMap<string, VerifyReport> {
  return new Map(items.map((item) => [item.model_id, item]));
}

/** 一条「能力层自检通过」的账本记录：就绪 = 校验过 + 自检过，两半都得有替身。 */
export function selftestOk(over: Partial<SelftestResult> = {}): SelftestResult {
  return { ok: true, chars: 56, elapsed_s: 8.4, at: 1_760_000_000_000, ...over };
}

/** 自检账本（key → 结果），与 protocol 的 SelftestResults 同形。 */
export function selftestsOf(
  ...items: [string, SelftestResult][]
): Readonly<Record<string, SelftestResult>> {
  return Object.fromEntries(items);
}

/** 一份「能直接落位」的体检结果：认成了 Whisper Medium，全部判据通过，库里没有同一件。 */
export function inspection(over: Partial<ImportInspection> = {}): ImportInspection {
  return {
    source_path: 'E:\\下载\\models--Systran--faster-whisper-medium',
    file_count: 9,
    total_bytes: 1_500_000_000,
    recognized: true,
    model_id: 'faster-whisper-medium',
    name: 'Whisper Medium（高准确度）',
    kind: 'asr',
    engine: 'faster_whisper',
    engine_ready: true,
    model_root: 'E:\\下载\\models--Systran--faster-whisper-medium\\snapshots\\0123456789',
    cache_path: 'E:\\下载\\models--Systran--faster-whisper-medium',
    basis: '缓存目录名指向 Systran/faster-whisper-medium · config.json 的 model_type=ct2',
    missing_files: [],
    target: {
      placement: 'asr/faster-whisper',
      path: 'D:\\data\\models\\asr\\faster-whisper',
      free_bytes: 412_000_000_000,
    },
    conflict: null,
    checks: [{ name: '必需文件', status: 'pass' }],
    ok: true,
    ...over,
  };
}

/** 一条「本地导入」登记：copy 进库的那份，路径在库内。 */
export function importRecord(over: Partial<ImportRecord> = {}): ImportRecord {
  return {
    model_id: 'faster-whisper-medium',
    kind: 'asr',
    engine: 'faster_whisper',
    path: 'D:\\data\\models\\asr\\faster-whisper\\models--Systran--faster-whisper-medium',
    source_path: 'E:\\下载\\models--Systran--faster-whisper-medium',
    mode: 'copy',
    incomplete: false,
    imported_at: 1_760_000_000_000,
    ...over,
  };
}

/** 清单外的目录登记：认不出身份（model_id 为 null），所以只能撤销登记，不能生效。 */
export function externalRecord(over: Partial<ImportRecord> = {}): ImportRecord {
  return importRecord({
    model_id: null,
    engine: '',
    path: 'E:\\下载\\同事给的模型',
    source_path: 'E:\\下载\\同事给的模型',
    mode: 'register',
    label: '同事给的模型',
    ...over,
  });
}

/** 未识别的目录：后端不认身份，也就不知道 placement，只能由业主声明能力。 */
export function externalInspection(over: Partial<ImportInspection> = {}): ImportInspection {
  return inspection({
    recognized: false,
    model_id: null,
    name: null,
    kind: null,
    engine: null,
    model_root: null,
    cache_path: null,
    target: null,
    basis: '目录里没有内置清单任一引擎的必需文件',
    checks: [{ name: '必需文件', status: 'fail', detail: '未识别出模型，无法按引擎清单核对' }],
    ok: false,
    ...over,
  });
}

/** 导入落位作业：默认已是「完成」，异常用例各自改 status 与 error。 */
export function importJob(over: Partial<JobInfo> = {}): JobInfo {
  return {
    id: 'j1',
    type: 'model_import',
    ref_id: null,
    status: 'completed',
    progress: 100,
    created_at: 1,
    updated_at: 2,
    ...over,
  };
}
