/** Electron 主进程入口（docs/desktop/00 §2 启动时序）。 */
import { app, BrowserWindow, nativeTheme, protocol, screen, shell } from 'electron';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { registerIpc, broadcastEvent, resolveDataPaths, type IpcContext } from './ipc';
import { createPreviewHandler, createPreviewRoots } from './services/preview-protocol';
import { ServiceManager, type ServiceManagerOptions } from './services/service-manager';

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;
// dist-electron/main/index.js → 上三级即仓库根
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');

let mainWindow: BrowserWindow | null = null;
let manager: ServiceManager | null = null;

// 必须在 app.ready 前注册（stream: 支持视频流；bypassCSP: 允许 media 加载）
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'dramaclip',
    privileges: {
      stream: true,
      standard: true,
      bypassCSP: true,
      supportFetchAPI: true,
      corsEnabled: true,
      secure: true,
    },
  },
]);

function createMainWindow(): void {
  // 默认 1680×1050：1920×1080 在主流 1080p 屏扣掉任务栏（可用高约 1040px）放不下，
  // 1680×1050 在 1080p 与更大屏都完整可见；更小的屏钳到工作区尺寸，不越界
  const workArea = screen.getPrimaryDisplay().workAreaSize;
  // 开发态窗口/任务栏图标；打包后 exe 已内嵌 build/icon.ico，缺文件时省略（降级不可见）
  const devIcon = path.join(REPO_ROOT, 'build', 'icon.ico');

  mainWindow = new BrowserWindow({
    icon: existsSync(devIcon) ? devIcon : undefined,
    width: Math.min(1680, workArea.width),
    height: Math.min(1050, workArea.height),
    minWidth: 1024,
    minHeight: 680,
    show: false,
    frame: false,
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

/** 开发态数据目录：默认仓库 data/；DRAMACLIP_DATA_DIR 可重定向——
 * scripts/seed_scale_data.py 印的实跑步骤靠它成立（规模实测不碰真实数据）。
 * 打包态不认环境变量：产品数据永远落 userData/data。 */
function devDataDir(): string {
  const override = (process.env.DRAMACLIP_DATA_DIR ?? '').trim();
  return override === '' ? path.join(REPO_ROOT, 'data') : override;
}

function buildIpcContext(managerInstance: ServiceManager): IpcContext {
  const dataDir = app.isPackaged
    ? path.join(app.getPath('userData'), 'data')
    : devDataDir();
  return {
    rpc: (method, params) => managerInstance.rpc(method, params),
    restartService: () => { managerInstance.restart(); },
    appVersion: () => app.getVersion(),
    dataPaths: () => resolveDataPaths(dataDir),
    windows: () => (mainWindow === null ? [] : [mainWindow]),
  };
}

async function bootstrap(): Promise<void> {
  nativeTheme.themeSource = 'dark';
  // 打包模式：extraResources 落在 process.resourcesPath/app-resources；
  // 开发模式：仓库根 resources/
  const resourcesDir = app.isPackaged
    ? path.join(process.resourcesPath, 'app-resources')
    : path.join(REPO_ROOT, 'resources');
  const options: ServiceManagerOptions = {
    repoRoot: REPO_ROOT,
    resourcesDir,
    cwd: app.isPackaged ? process.resourcesPath : REPO_ROOT,
    dataDir: app.isPackaged
      ? path.join(app.getPath('userData'), 'data')
      : devDataDir(),
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
  // 本地媒体预览协议：dramaclip://local/<encodeURIComponent(绝对路径)>
  // video 元素要求 Range/206 分段响应；路径/类型/内存三重围栏见 preview-protocol.ts
  const previewDataRoot = app.isPackaged
    ? path.join(app.getPath('userData'), 'data')
    : devDataDir();
  const getPreviewRoots = createPreviewRoots(async () => {
    if (manager === null) return [];
    const projects = (await manager.rpc('project.list', {})) as readonly {
      source_path?: unknown;
    }[]; // 受信 sidecar 边界：形状由 protocol 契约钳制
    return projects
      .map((project) => project.source_path)
      .filter((value): value is string => typeof value === 'string' && value !== '');
  }, previewDataRoot);
  protocol.handle('dramaclip', createPreviewHandler(getPreviewRoots));
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
