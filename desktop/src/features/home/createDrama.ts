/** 建剧动作：选目录 → 建项目 → 扫集 → 返回新剧的入口路径。
 *
 * 从 StartCards.tsx 上提：「新增项目」有两个入口（工作台页头的 primary
 * 与空态引导里的那个），两处各写一份必然漂移。顺带把两份各写一遍的目录名解析
 * 收成 folderName 一处。
 *
 * 剧名取文件夹名：规格 §1 已定案「下载后通常按任务名称建文件夹，所以新增项目时
 * 剧名直接取文件夹名即与片单天然对齐，无需导入器、无需任何额外录入」。
 *
 * 一次选多目录的批量建项目要 project.batch_create（P-2），本片仍是单目录——
 * 这是 §4.2 的能力，不是工作台的。
 */
import { dramaEntryPath } from '../../app/routes';
import { pickFolder, projectApi } from '../../services/client';

export interface CreateDramaResult {
  readonly projectId: string;
  readonly name: string;
  readonly entryPath: string;
}

/** 用户取消选择时返回 null——取消不是失败，调用方不得弹错误提示。 */
export async function createDramaFromFolder(): Promise<CreateDramaResult | null> {
  const folder = await pickFolder();
  if (folder === null) return null;
  const name = folderName(folder);
  const project = await projectApi.create(name, folder);
  // 扫集失败不吞：目录里没有视频时服务端会抛，那句错要原样浮给用户。
  // 此时项目已建成，用户可以换个目录重扫，不必重建。
  await projectApi.scanEpisodes(project.id);
  return { projectId: project.id, name, entryPath: dramaEntryPath(project.id) };
}

/** 目录名 = 剧名。同时处理 / 与 \（Windows 原生对话框返回反斜杠），并容忍尾部分隔符。 */
export function folderName(folder: string): string {
  const trimmed = folder.replace(/[\\/]+$/, '');
  const name = trimmed.split(/[\\/]/).pop() ?? '';
  // 空串或盘符根（'D:\' → 'D:'）都算没有末段。给一个可用兜底。
  return name === '' || /^[a-zA-Z]:$/.test(name) ? '新剧' : name;
}
