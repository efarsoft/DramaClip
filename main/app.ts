/**
 * DramaClip 应用入口
 * Electron 主进程入口点
 */

import { app, BrowserWindow, Menu, protocol, net } from 'electron';
import path from 'path';
import { WindowManager } from './window/manager';
import { setupIpcHandlers, setBackendManager, setWindowManager } from './ipc/bridge';
import { BackendLauncher } from './backend/launcher';
import { BackendManager } from './backend/manager';
import { IPC_CHANNELS } from './ipc/channels';

// 保持全局引用，防止 GC 回收
let windowManager: WindowManager | null = null;
let backendManager: BackendManager | null = null;

// 开发模式检测
const isDev = !app.isPackaged;

async function createWindow(): Promise<BrowserWindow> {
  windowManager = new WindowManager();
  const mainWindow = windowManager.createMainWindow();

  // 注册窗口管理器
  setWindowManager(windowManager);

  // 开发模式下打开 DevTools
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  // 加载页面内容
  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, '../../dist/index.html'));
  }

  return mainWindow;
}

async function initializeBackend(mainWindow: BrowserWindow): Promise<void> {
  const resourcesPath = isDev
    ? path.join(process.cwd(), 'resources')
    : process.resourcesPath;

  const backendLauncher = new BackendLauncher(resourcesPath);
  const backendPath = await backendLauncher.findBackend();

  if (!backendPath) {
    console.error('[Main][App] backend.exe not found, running in offline mode');
    return;
  }

  // 创建后端管理器
  backendManager = new BackendManager(
    backendPath,
    path.dirname(backendPath)
  );

  // 注册后端管理器
  setBackendManager(backendManager);

  // 监听后端事件并转发到渲染进程
  backendManager.on('ready', () => {
    console.log('[Main][App] Backend ready');
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_READY);
  });

  backendManager.on('progress', (payload: unknown) => {
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_PROGRESS, payload);
  });

  backendManager.on('log', (message: string, level: string) => {
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_LOG, message, level);
  });

  backendManager.on('error', (error: Error) => {
    console.error('[Main][App] Backend error:', error);
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_ERROR, error.message);
  });

  backendManager.on('exit', (code: number, signal: string) => {
    console.log(`[Main][App] Backend exited: code=${code}, signal=${signal}`);
  });

  backendManager.on('restarted', () => {
    console.log('[Main][App] Backend restarted');
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_READY);
  });

  backendManager.on('maxRestartAttemptsReached', () => {
    console.error('[Main][App] Max restart attempts reached');
    mainWindow.webContents.send(IPC_CHANNELS.BACKEND_ERROR, '后端启动失败，请重启应用');
  });

  try {
    await backendManager.start();
  } catch (error) {
    console.error('[Main][App] Failed to start backend:', error);
  }
}

function setupGlobalExceptionHandlers(): void {
  process.on('uncaughtException', (error) => {
    console.error('[Main][App] Uncaught Exception:', error);
  });

  process.on('unhandledRejection', (reason) => {
    console.error('[Main][App] Unhandled Rejection:', reason);
  });
}

// 注册自定义协议，用于在渲染进程中安全访问本地视频文件
// 必须在 app.ready 之前调用
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'dramaclip',
    privileges: {
      bypassCSP: true,
      stream: true,
      supportFetchAPI: true,
      standard: false,
      secure: true,
    },
  },
]);

// 应用启动
app.whenReady().then(async () => {
  console.log('[Main][App] DramaClip starting...');
  console.log(`[Main][App] Mode: ${isDev ? 'development' : 'production'}`);

  setupGlobalExceptionHandlers();

  // 设置空菜单，移除 File/View 等默认菜单
  Menu.setApplicationMenu(null);

  // 注册 IPC 处理器
  setupIpcHandlers();

  // 创建主窗口
  const mainWindow = await createWindow();

  // 注册 dramaclip:// 协议处理器
  protocol.handle('dramaclip', (request) => {
    // dramaclip://local/C%3A%5CVideos%5Cfile.mp4 → file:///C:/Videos/file.mp4
    const filePath = decodeURIComponent(request.url.replace('dramaclip://local/', ''));
    // Windows: 反斜杠 → 正斜杠
    const normalized = filePath.replace(/\\/g, '/');
    // UNC 路径 (//server/share/...) → file://server/share/...
    // 本地路径 (C:/...) → file:///C:/...
    if (normalized.startsWith('//')) {
      return net.fetch(`file:${normalized}`);
    }
    return net.fetch(`file:///${normalized}`);
  });

  // 初始化后端
  await initializeBackend(mainWindow);

  app.on('activate', async () => {
    // macOS: 点击 dock 图标时重新创建窗口
    if (BrowserWindow.getAllWindows().length === 0) {
      const newWindow = await createWindow();
      await initializeBackend(newWindow);
    }
  });
});

// 所有窗口关闭时
app.on('window-all-closed', () => {
  // 关闭后端进程
  if (backendManager) {
    backendManager.stop();
  }

  // macOS 除外，大多数桌面应用在所有窗口关闭后退出
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// 应用退出前清理
app.on('before-quit', async () => {
  console.log('[Main][App] DramaClip shutting down...');

  if (backendManager) {
    await backendManager.stop();
  }

  if (windowManager) {
    windowManager.destroy();
  }
});

// 导出服务实例供 IPC 使用
export { windowManager, backendManager };
