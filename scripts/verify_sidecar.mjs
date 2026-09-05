#!/usr/bin/env node
/**
 * Sidecar 打包冒烟（W14 回归工具）：验证 PyInstaller 产物可独立运行——
 * 握手 → ping → 预设（DRAMACLIP_RESOURCES_DIR 注入）→ 模型清单 →
 * 合成视频预筛（ffmpeg + 分析引擎导入链）→ 优雅退出。
 * 用法：node scripts/verify_sidecar.mjs
 */
import net from 'node:net';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(fileURLToPath(import.meta.url), '..', '..');
const sidecar = path.join(repoRoot, 'resources', 'dramaclip-service', 'dramaclip-service.exe');
const ffmpeg = path.join(repoRoot, 'resources', 'ffmpeg', 'ffmpeg.exe');
const port = 51891;
const token = 'sidecar'.padEnd(64, '0');

let send = null;
let buffer = '';
const pending = new Map();
let nextId = 0;
const childProcesses = [];

const server = net.createServer((socket) => {
  send = (payload) => socket.write(JSON.stringify(payload) + '\n');
  socket.setEncoding('utf8');
  socket.on('data', (chunk) => {
    buffer += chunk;
    let idx = buffer.indexOf('\n');
    while (idx >= 0) {
      const line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line) handleLine(line);
      idx = buffer.indexOf('\n');
    }
  });
  socket.on('error', () => socket.destroy());
});

function handleLine(line) {
  const msg = JSON.parse(line);
  if (msg.type === 'hello') {
    console.log('[sidecar] 握手 OK:', msg.service_version);
    send({ type: 'hello-ack', app_version: 'sidecar-smoke' });
    return;
  }
  if (msg.id !== undefined && pending.has(msg.id)) {
    const entry = pending.get(msg.id);
    pending.delete(msg.id);
    clearTimeout(entry.timer);
    if (msg.error) entry.reject(new Error(`[${msg.error.code}] ${msg.error.message}`));
    else entry.resolve(msg.result);
  }
}

function rpc(method, params = {}, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    if (typeof send !== 'function') {
      reject(new Error(`服务未连接，无法调用 ${method}（sidecar 可能在启动时崩溃）`));
      return;
    }
    nextId += 1;
    const id = `sc-${nextId}`;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`RPC 超时: ${method}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    send({ jsonrpc: '2.0', id, method, params });
  });
}

function makeSampleVideo(dir) {
  const out = path.join(dir, 'sample.mp4');
  execFileSync(ffmpeg, [
    '-y', '-f', 'lavfi', '-i', 'testsrc2=duration=3:size=320x640:rate=15',
    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-c:a', 'aac', out,
  ], { stdio: 'pipe' });
  return out;
}

async function waitJob(jobId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const status = await rpc('analysis.status', { job_id: jobId });
    if (['completed', 'failed', 'cancelled'].includes(status.status)) return status;
    if (Date.now() > deadline) throw new Error('任务超时');
    await new Promise((r) => setTimeout(r, 500));
  }
}

function check(name, ok, detail = '') {
  console.log(`  ${ok ? '✓' : '✗'} ${name}${detail ? ` — ${detail}` : ''}`);
  if (!ok) process.exitCode = 1;
}

async function main() {
  const work = mkdtempSync(path.join(tmpdir(), 'dc-sidecar-'));
  const dataDir = path.join(work, 'data');
  await new Promise((resolve) => server.listen(port, '127.0.0.1', resolve));
  console.log('[sidecar] 产物:', sidecar);

  const child = spawn(sidecar, [], {
    env: {
      ...process.env,
      DRAMACLIP_SERVICE_ADDRESS: `127.0.0.1:${port}`,
      DRAMACLIP_AUTH_TOKEN: token,
      DRAMACLIP_DATA_DIR: dataDir,
      DRAMACLIP_RESOURCES_DIR: path.join(repoRoot, 'resources'),
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  });
  childProcesses.push(child);
  await new Promise((r) => setTimeout(r, 8000)); // onedir 冷启动

  const ping = await rpc('system.ping');
  check('system.ping', typeof ping.service_version === 'string', ping.service_version);

  const presets = await rpc('subtitle.list_presets');
  check('subtitle.list_presets（资源目录注入）', Array.isArray(presets) && presets.length >= 3,
    `${presets.length} 套`);

  const models = await rpc('models.list');
  check('models.list', Array.isArray(models) && models.length > 0, `${models.length} 个模型项`);

  const video = makeSampleVideo(work);
  const project = await rpc('project.create', { name: 'sidecar-smoke', source_path: work });
  await rpc('project.scan_episodes', { project_id: project.id });
  const prescreen = await rpc('analysis.prescreen', { project_id: project.id });
  const job = await waitJob(prescreen.job_id, 120000);
  check('analysis.prescreen（ffmpeg+引擎链）', job.status === 'completed', `status=${job.status}`);

  const shutdown = await rpc('system.shutdown');
  check('system.shutdown', shutdown.ok === true);
  const exited = await Promise.race([
    new Promise((resolve) => child.once('exit', resolve)),
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ]);
  check('进程优雅退出', exited !== null);

  rmSync(work, { recursive: true, force: true });
  server.close();
  if (process.exitCode === 1) {
    console.log('[sidecar] 冒烟失败');
    process.exit(1);
  }
  console.log('[sidecar] 冒烟全部通过');
  process.exit(0);
}

main().catch((error) => {
  console.error('[sidecar] 冒烟异常:', error.message);
  for (const child of childProcesses) child.kill();
  process.exit(1);
});
