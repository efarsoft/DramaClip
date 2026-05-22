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

    // 生产模式：resources 目录（支持三种打包形态）
    const prodPaths = [
      // 1. 支持 --onefile 单文件打包可执行程序（Windows/Linux/macOS）
      path.join(this.resourcesPath, 'backend', 'backend.exe'),
      path.join(this.resourcesPath, 'backend', 'backend'),
      // 2. 支持 --onedir 单目录文件夹打包模式（Windows/Linux/macOS）
      path.join(this.resourcesPath, 'backend', 'backend', 'backend.exe'),
      path.join(this.resourcesPath, 'backend', 'backend', 'backend'),
      // 3. 支持 Python 源码配合内置 Python 解释器打包模式
      path.join(this.resourcesPath, 'backend', 'backend_main.py'),
      path.join(this.resourcesPath, 'backend', 'app', 'backend_main.py'),
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
