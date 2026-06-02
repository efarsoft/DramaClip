#!/usr/bin/env node
/**
 * DramaClip 开发模式 Electron 启动器
 * 用途: npm run dev:full 内部调用
 *
 * 统一启动流程：
 *   1. 设置 DEV_ELECTRON_MANUAL=1，阻止 vite-plugin-electron 自动 startup
 *   2. 启动 vite dev server（含 main/preload 编译）
 *   3. 等待 vite 就绪后手动启动 Electron
 *
 * 避免 concurrently 并行导致的双窗口问题
 */
const { spawn } = require('child_process');
const path = require('path');

const isWin = process.platform === 'win32';

// 注入环境变量，让 vite.config.ts 中的 onstart 跳过 options.startup()
process.env.DEV_ELECTRON_MANUAL = '1';

console.log('[dev-electron] Starting Vite dev server...');

const vite = spawn(
  'npx',
  ['vite', '--host'],
  { stdio: ['inherit', 'pipe', 'pipe'], shell: isWin }
);

let electronStarted = false;

function startElectron() {
  if (electronStarted) return;
  electronStarted = true;

  console.log('[dev-electron] Vite ready, starting Electron...');
  const electronBin = isWin ? 'electron.cmd' : 'electron';
  const electronPath = path.join(__dirname, '..', 'node_modules', '.bin', electronBin);

  const electron = spawn(
    electronPath,
    ['.'],
    {
      stdio: 'inherit',
      shell: isWin,
      env: {
        ...process.env,
        VITE_DEV_SERVER_URL: 'http://localhost:5173',
      },
    }
  );

  electron.on('close', (code) => {
    vite.kill();
    process.exit(code);
  });
}

// 监听 vite stdout，检测到 dev server 就绪后启动 Electron
vite.stdout.on('data', (data) => {
  const msg = data.toString();
  process.stdout.write(msg);

  // Vite 输出 "Local: http://localhost:5173" 时认为就绪
  if (!electronStarted && /localhost:\d+/.test(msg)) {
    // 延迟 1 秒确保 main/preload 编译完成
    setTimeout(startElectron, 1500);
  }
});

vite.stderr.on('data', (data) => {
  process.stderr.write(data);
});

vite.on('close', (code) => {
  if (!electronStarted) {
    console.error('[dev-electron] Vite exited before ready, code:', code);
    process.exit(code || 1);
  }
});

// 优雅退出
process.on('SIGINT', () => {
  vite.kill('SIGINT');
  process.exit(0);
});

process.on('SIGTERM', () => {
  vite.kill('SIGTERM');
  process.exit(0);
});
