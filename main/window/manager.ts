/**
 * 窗口管理器
 * 负责主窗口的创建、销毁、状态管理
 */

import { BrowserWindow, screen, app } from 'electron';
import path from 'path';
import fs from 'fs';

export interface WindowState {
  x?: number;
  y?: number;
  width: number;
  height: number;
  isMaximized: boolean;
}

const DEFAULT_STATE: WindowState = {
  width: 1280,
  height: 800,
  isMaximized: false,
};

export class WindowManager {
  private mainWindow: BrowserWindow | null = null;
  private stateFilePath: string;

  constructor() {
    const userDataPath = app.getPath('userData');
    this.stateFilePath = path.join(userDataPath, 'window-state.json');
  }

  createMainWindow(): BrowserWindow {
    const state = this.loadState();

    this.mainWindow = new BrowserWindow({
      width: state.width,
      height: state.height,
      x: state.x,
      y: state.y,
      minWidth: 1024,
      minHeight: 680,
      show: false, // 等待 ready-to-show 再显示
      frame: true, // 使用系统原生窗口边框
      backgroundColor: '#ffffff',
      autoHideMenuBar: true, // 隐藏菜单栏
      webPreferences: {
        preload: path.join(__dirname, '../preload/preload.js'),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: false,
      },
    });

    // 准备好后显示窗口
    this.mainWindow.once('ready-to-show', () => {
      if (this.mainWindow) {
        this.mainWindow.show();
        if (state.isMaximized) {
          this.mainWindow.maximize();
        }
      }
    });

    // 窗口状态变化时保存
    this.mainWindow.on('resize', () => this.saveState());
    this.mainWindow.on('move', () => this.saveState());
    this.mainWindow.on('maximize', () => this.saveState());
    this.mainWindow.on('unmaximize', () => this.saveState());

    // 窗口关闭时清理
    this.mainWindow.on('closed', () => {
      this.mainWindow = null;
    });

    return this.mainWindow;
  }

  getMainWindow(): BrowserWindow | null {
    return this.mainWindow;
  }

  destroy(): void {
    if (this.mainWindow) {
      this.mainWindow.destroy();
      this.mainWindow = null;
    }
  }

  private loadState(): WindowState {
    try {
      if (fs.existsSync(this.stateFilePath)) {
        const data = fs.readFileSync(this.stateFilePath, 'utf-8');
        const state = JSON.parse(data) as WindowState;

        // 验证窗口是否在可见屏幕范围内
        if (this.isStateValid(state)) {
          return state;
        }
      }
    } catch (error) {
      console.error('[Main][WindowManager] Failed to load window state:', error);
    }

    return { ...DEFAULT_STATE };
  }

  private saveState(): void {
    if (!this.mainWindow) return;

    try {
      const bounds = this.mainWindow.getBounds();
      const state: WindowState = {
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        isMaximized: this.mainWindow.isMaximized(),
      };

      fs.writeFileSync(this.stateFilePath, JSON.stringify(state, null, 2));
    } catch (error) {
      console.error('[Main][WindowManager] Failed to save window state:', error);
    }
  }

  private isStateValid(state: WindowState): boolean {
    const displays = screen.getAllDisplays();

    // 检查窗口中心是否在任何屏幕上
    if (state.x !== undefined && state.y !== undefined) {
      const centerX = state.x + state.width / 2;
      const centerY = state.y + state.height / 2;

      return displays.some((display) => {
        const { x, y, width, height } = display.bounds;
        return centerX >= x && centerX <= x + width && centerY >= y && centerY <= y + height;
      });
    }

    return true;
  }
}
