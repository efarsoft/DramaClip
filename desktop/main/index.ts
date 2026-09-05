/** Electron 主进程入口（docs/desktop/00 §2 启动时序）。 */
import { app, BrowserWindow, nativeTheme, shell } from 'electron';
import path from 'node:path';
import { registerIpc, broadcastEvent, type IpcContext } from './ipc';
import { ServiceManager, type ServiceManagerOptions } from './services/service-manager';

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;
// dist-electron/main/index.js → 上三级即仓库根
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');

let mainWindow: BrowserWindow | null = null;
let manager: ServiceManager | null = null;

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  // 渲染层日志转发到主进程控制台（错误可追踪）
  mainWindow.webContents.on('console-message', (event) => {
    const source = `${event.sourceId}:${String(event.lineNumber)}`;
    console.log(`[renderer] ${event.level}: ${event.message} (${source})`);
  });
  // 补发当前服务状态（ready 广播可能早于渲染层订阅）
  mainWindow.webContents.on('did-finish-load', () => {
    if (manager !== null) {
      broadcastEvent(buildIpcContext(manager), {
        type: 'service-state',
        state: manager.currentState,
      });
    }
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  // 外部链接一律交给系统浏览器
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });
  if (DEV_SERVER_URL !== undefined && DEV_SERVER_URL.length > 0) {
    void mainWindow.loadURL(DEV_SERVER_URL);
  } else {
    void mainWindow.loadFile(path.join(__dirname, '..', '..', 'dist', 'index.html'));
  }
}

function buildIpcContext(managerInstance: ServiceManager): IpcContext {
  return {
    rpc: (method, params) => managerInstance.rpc(method, params),
    restartService: () => { managerInstance.restart(); },
    appVersion: () => app.getVersion(),
    windows: () => (mainWindow === null ? [] : [mainWindow]),
  };
}

async function bootstrap(): Promise<void> {
  nativeTheme.themeSource = 'dark';
  const options: ServiceManagerOptions = {
    repoRoot: REPO_ROOT,
    dataDir: app.isPackaged
      ? path.join(app.getPath('userData'), 'data')
      : path.join(REPO_ROOT, 'data'),
    appVersion: app.getVersion(),
    isPackaged: app.isPackaged,
    onStateChange: (state) => { console.log(`[ServiceManager] state=${state}`); },
    onEvent: (event) => {
      const context = manager === null ? null : buildIpcContext(manager);
      if (context !== null) broadcastEvent(context, event);
    },
  };
  manager = new ServiceManager(options);
  registerIpc(buildIpcContext(manager));
  createMainWindow();
  await manager.start();
}

void app.whenReady().then(() => {
  void bootstrap();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', (event) => {
  if (manager === null) return;
  event.preventDefault();
  const instance = manager;
  manager = null;
  void instance.stop().finally(() => { app.quit(); });
});
