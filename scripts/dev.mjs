#!/usr/bin/env node
/**
 * 开发编排（docs/desktop/02 §2）：在 desktop/ 启动 Vite。
 * vite-plugin-electron 负责构建主进程/preload 并自动拉起 Electron；
 * 端口固定 5180（strictPort），VITE_DEV_SERVER_URL 由本脚本预置。
 */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const desktopDir = path.resolve(fileURLToPath(import.meta.url), '..', '..', 'desktop');

const child = spawn(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['vite'], {
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
