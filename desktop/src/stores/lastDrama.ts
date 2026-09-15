/** 「继续上次」：最近打开过的那部剧。
 *
 * 用 localStorage 而不是 zustand / SQLite：按数据归属原则，它既不是随版本
 * 分发的只读内容，也不是业务产物，而是渲染层的个人偏好——刷新即失、换机即无，
 * 都不构成损失。
 * 不用 zustand persist 是因为它带来水合时序，而本页只在挂载时读一次；
 * 三个普通函数更直白，也更便于单测（jsdom 自带 localStorage）。
 */

const STORAGE_KEY = 'dramaclip.last-drama';

export interface LastDrama {
  readonly id: string;
  readonly name: string;
  readonly visitedAtMs: number;
}

export function readLastDrama(): LastDrama | null {
  let raw: string;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (value === null) return null;
    raw = value;
  } catch {
    // localStorage 不可用（隐私模式/被禁用）：当作没有记录。
    // 「继续上次」是便利项不是功能，不值得为它弹错。
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const candidate = parsed as Partial<LastDrama>;
  // 只认形状完整的记录：缺 id 的对象拼进路径会得到 /projects/undefined/analysis。
  if (typeof candidate.id !== 'string' || candidate.id === '') return null;
  if (typeof candidate.name !== 'string') return null;
  if (typeof candidate.visitedAtMs !== 'number') return null;
  return { id: candidate.id, name: candidate.name, visitedAtMs: candidate.visitedAtMs };
}

/** 打开某部剧时调用。调用方手里已经有剧名，所以这里不发任何 RPC。 */
export function rememberDrama(projectId: string, name: string): void {
  if (projectId === '' || name === '') return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ id: projectId, name, visitedAtMs: Date.now() } satisfies LastDrama),
    );
  } catch {
    // 写不进去（配额满）就下次再试，不打扰用户
  }
}

export function clearLastDrama(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 同 readLastDrama：不可用就算了
  }
}
