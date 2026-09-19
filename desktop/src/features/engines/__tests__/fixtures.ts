// 引擎中心纯函数的共用替身：字段与 protocol 的 ModelInfo / VerifyReport 同步，
// 缺字段即 typecheck 失败——这是「UI 不得凭空造判据」的下限保障。
import type { ModelInfo, VerifyReport } from '@dramaclip/protocol';

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
