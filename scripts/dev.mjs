#!/usr/bin/env node
/**
 * 开发编排（docs/desktop/02 §2）：在 desktop/ 启动 Vite。
 * vite-plugin-electron 负责构建主进程/preload 并自动拉起 Electron；
 * 端口固定 5180（strictPort），VITE_DEV_SERVER_URL 由本脚本预置。
 * 直接以 node 运行 vite bin（Node>=20.12 禁止无 shell spawn .cmd，且免 npx 开销）。
 */
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const desktopDir = path.resolve(fileURLToPath(import.meta.url), '..', '..', 'desktop');
const desktopRequire = createRequire(path.join(desktopDir, 'package.json'));
const viteBin = path.join(
  path.dirname(desktopRequire.resolve('vite/package.json')),
  'bin',
  'vite.js',
);

const child = spawn(process.execPath, [viteBin], {
  cwd: desktopDir,
  stdio: 'inherit',
  env: { ...process.env, VITE_DEV_SERVER_URL: 'http://localhost:5180' },
});

const forwardSignal = (signal) => () => {
  child.kill(signal);
};
process.on('SIGINT', forwardSignal('SIGINT'));
process.on('SIGTERM', forwardSignal('SIGTERM'));
child.on('exit', (code) => process.exit(code ?? 0));
