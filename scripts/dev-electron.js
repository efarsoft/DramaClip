#!/usr/bin/env node
/**
 * DramaClip 开发模式 Electron 启动器
 * 用途: npm run dev:full 内部调用
 *
 * 统一启动流程：
 *   1. 设置 DEV_ELECTRON_MANUAL=1，阻止 vite-plugin-electron 自动 startup
 *   2. 启动 vite dev server（含 main/preload 编译）
 *   3. 等待 main/preload 编译完成后手动启动 Electron
 *
 * 避免 concurrently 并行导致的双窗口问题
 */
const { spawn } = require('child_process');
const path = require('path');

const isWin = process.platform === 'win32';

// 注入环境变量，让 vite.config.ts 中的 onstart 跳过 options.startup()
process.env.DEV_ELECTRON_MANUAL = '1';

// ANSI 转义码剥离（Vite 6 输出含彩色/格式化字符，会破坏正则匹配）
// eslint-disable-next-line no-control-regex
const ANSI_RE = /[\u001b\u009b][[\]()#;?]*(?:(?:(?:(?:;[-a-zA-Z\d\/#&.:=?%@~_]+)*|[a-zA-Z\d]+(?:;[-a-zA-Z\d\/#&.:=?%@~_]*)?)?\u0007)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g;
function stripAnsi(s) { return s.replace(ANSI_RE, ''); }

console.log('[dev-electron] Starting Vite dev server...');

const vite = spawn(
  'npx',
  ['vite', '--host'],
  { stdio: ['inherit', 'pipe', 'pipe'], shell: isWin }
);

let electronStarted = false;
let devServerReady = false;
let mainBuilt = false;
let preloadBuilt = false;

function tryStartElectron() {
  if (electronStarted) return;
  if (!devServerReady || !mainBuilt || !preloadBuilt) {
    console.log(`[dev-electron] Waiting... server=${devServerReady} main=${mainBuilt} preload=${preloadBuilt}`);
    return;
  }

  electronStarted = true;
  console.log('[dev-electron] All ready, starting Electron...');

  const electronBin = isWin ? 'electron.cmd' : 'electron';
  const electronPath = path.join(__dirname, '..', 'node_modules', '.bin', electronBin);

  const electron = spawn(
    electronPath,
    ['.'],
    {
      stdio: 'inherit',
      shell: isWin,
      env: { ...process.env },
    }
  );

  electron.on('close', (code) => {
    vite.kill();
    process.exit(code);
  });

  electron.on('error', (err) => {
    console.error('[dev-electron] Failed to start Electron:', err.message);
    vite.kill();
    process.exit(1);
  });
}

// 累积全部输出（剥离 ANSI 后），用于检测 localhost:port 和编译状态
let cleanOutput = '';

function processChunk(raw) {
  const clean = stripAnsi(raw);
  cleanOutput += clean;
  return clean;
}

vite.stdout.on('data', (data) => {
  const msg = data.toString();
  process.stdout.write(msg); // 原始带色彩输出给用户
  const clean = processChunk(msg);

  // 检测 dev server URL
  if (!devServerReady) {
    const match = cleanOutput.match(/localhost:(\d+)/);
    if (match) {
      devServerReady = true;
      process.env.VITE_DEV_SERVER_URL = `http://localhost:${match[1]}`;
      console.log(`\n[dev-electron] Dev server on port ${match[1]}`);
      tryStartElectron();
    }
  }

  // 检测 main/preload 编译（vite-plugin-electron 输出 dist-electron/main/ 和 dist-electron/preload/）
  if (!mainBuilt && /dist-electron[\\/]main[\\/]/.test(clean)) {
    mainBuilt = true;
    console.log('[dev-electron] main built');
    tryStartElectron();
  }
  if (!preloadBuilt && /dist-electron[\\/]preload[\\/]/.test(clean)) {
    preloadBuilt = true;
    console.log('[dev-electron] preload built');
    tryStartElectron();
  }
});

vite.stderr.on('data', (data) => {
  const msg = data.toString();
  process.stderr.write(msg);
  processChunk(msg);

  // Vite 6 可能将 server URL 输出到 stderr
  if (!devServerReady) {
    const match = cleanOutput.match(/localhost:(\d+)/);
    if (match) {
      devServerReady = true;
      process.env.VITE_DEV_SERVER_URL = `http://localhost:${match[1]}`;
      console.log(`\n[dev-electron] Dev server on port ${match[1]} (from stderr)`);
      tryStartElectron();
    }
  }
});

vite.on('close', (code) => {
  if (!electronStarted) {
    console.error('[dev-electron] Vite exited before ready, code:', code);
    process.exit(code || 1);
  }
});

// 超时保护：60 秒
setTimeout(() => {
  if (!electronStarted) {
    console.error(`[dev-electron] Timeout! server=${devServerReady} main=${mainBuilt} preload=${preloadBuilt}`);
    console.error(`[dev-electron] Last 500 chars of output:\n${cleanOutput.slice(-500)}`);
    vite.kill();
    process.exit(1);
  }
}, 60000);

// 优雅退出
process.on('SIGINT', () => { vite.kill('SIGINT'); process.exit(0); });
process.on('SIGTERM', () => { vite.kill('SIGTERM'); process.exit(0); });
