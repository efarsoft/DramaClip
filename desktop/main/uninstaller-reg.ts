/** 卸载器定位依据：生效数据目录落注册表（HKCU\Software\DramaClip\DataDir）。
 *
 * NSIS 卸载器的「删除模型与运行环境」选项（build/installer.nsh）拿不到应用内
 * 存储重定向，只有这里知道真值——打包态每次启动刷新（重定向迁移后 relaunch
 * 即更新）；dev 态不写（仓库 data/ 不进卸载语义）。fire-and-forget：注册表
 * 不可写不阻断启动，卸载器读不到会回退默认路径。 */

import { spawn } from 'node:child_process';

export function registerDataDirForUninstaller(
  dataDir: string,
  isPackaged: boolean,
  platform: string,
  run: typeof spawn = spawn,
): void {
  if (!isPackaged || platform !== 'win32') return;
  run(
    'reg',
    ['add', 'HKCU\\Software\\DramaClip', '/v', 'DataDir', '/t', 'REG_SZ', '/d', dataDir, '/f'],
    { windowsHide: true },
  ).on('error', () => { /* 静默：见模块头 */ });
}
