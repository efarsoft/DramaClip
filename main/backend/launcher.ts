/**
 * 后端启动器
 * 负责发现和定位 backend.exe
 */

import { app } from 'electron';
import path from 'path';
import fs from 'fs';

export class BackendLauncher {
  private resourcesPath: string;

  constructor(resourcesPath: string) {
    this.resourcesPath = resourcesPath;
  }

  async findBackend(): Promise<string | null> {
    // 开发模式：查找 dist-electron/backend 或 Python 源码
    const devPaths = [
      path.join(process.cwd(), 'dist-electron', 'backend', 'backend.exe'),
      path.join(process.cwd(), 'dist-electron', 'backend', 'backend'),
      path.join(process.cwd(), 'app', 'backend_main.py'),
    ];

    // 生产模式：resources 目录
    const prodPaths = [
      path.join(this.resourcesPath, 'backend', 'backend.exe'),
      path.join(this.resourcesPath, 'backend', 'backend'),
    ];

    const searchPaths = app.isPackaged ? prodPaths : devPaths;

    for (const p of searchPaths) {
      if (fs.existsSync(p)) {
        console.log('[Main][BackendLauncher] Found backend at:', p);
        return p;
      }
    }

    console.warn('[Main][BackendLauncher] backend.exe not found in any location');
    return null;
  }

  getBackendDir(): string {
    if (app.isPackaged) {
      return path.join(this.resourcesPath, 'backend');
    }
    return path.join(process.cwd(), 'app');
  }

  async validateBackend(backendPath: string): Promise<boolean> {
    try {
      const stats = fs.statSync(backendPath);
      return stats.isFile() && (stats.mode & 0o111) !== 0; // 检查可执行权限
    } catch {
      return false;
    }
  }
}
