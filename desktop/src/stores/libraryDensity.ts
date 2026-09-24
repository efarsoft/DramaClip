/** 剧库密度档（卷二 P-E）：海报墙（grid，认脸）/ 列表（list，扫行）。
 *
 * 与 lastDrama 同理走 localStorage：渲染层个人偏好，不是业务数据——
 * 刷新即失、换机即无都不构成损失；zustand persist 的水合时序对「挂载读一次」
 * 的场景是纯开销。
 */

const STORAGE_KEY = 'dramaclip.library-density';

export type LibraryDensity = 'grid' | 'list';

/** 只认 'list' 一个字面量，其余（含损坏值/旧值）一律回落海报墙——默认档不猜。 */
export function readDensity(): LibraryDensity {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'list' ? 'list' : 'grid';
  } catch {
    // localStorage 不可用（隐私模式/被禁用）：用默认档，不打扰
    return 'grid';
  }
}

export function writeDensity(density: LibraryDensity): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, density);
  } catch {
    // 写不进去（配额满）就下次再试；本次会话内 state 仍生效
  }
}
