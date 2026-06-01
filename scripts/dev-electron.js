#!/usr/bin/env node
/**
 * DramaClip 开发模式 Electron 启动器
 * 用途: npm run dev:full 内部调用
 * 特点: 等待 Vite 就绪后启动 Electron，并支持后端 Python 源码直跑（manager 已支持）
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const isWin = process.platform === 'win32';

console.log('[dev-electron] Building main/preload for dev...');

const viteBuild = spawn(
  'npx',
  ['vite', 'build', '--mode', 'development'],
  { stdio: 'inherit', shell: isWin }
);

viteBuild.on('close', (code) => {
  if (code !== 0) {
    console.error('[dev-electron] Vite build failed');
    process.exit(code);
  }

  console.log('[dev-electron] Starting Electron (dev mode)...');
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
        VITE_DEV_SERVER_URL: 'http://localhost:5173'
      }
    }
  );

  electron.on('close', (code) => process.exit(code));
});
