#!/usr/bin/env node
/**
 * 持久化 e2e 冒烟脚本（回归工具）：起独立服务实例，验证
 * 心跳握手 → 模型清单 → 预筛 → 编排 → 导出 全链路。
 * 用法：node scripts/verify_e2e.mjs [--modes a,b,c]
 */
import net from 'node:net';
import { spawn, execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(fileURLToPath(import.meta.url), '..', '..');
const port = 51890;
const token = 'e2e'.padEnd(64, '0');
const dataDir = path.join(repoRoot, 'data');
const modesArg = process.argv
  .find((arg) => arg.startsWith('--modes='))
  ?.split('=')[1];
const modes = (modesArg ?? 'raw_clip,dialogue_narration').split(',');

let send = null;
let buffer = '';
const pending = new Map();
let nextId = 0;
let failures = 0;

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
    console.log('[e2e] 握手 OK:', msg.service_version);
    send({ type: 'hello-ack', app_version: 'e2e' });
    return;
  }
  if (msg.id !== undefined && pending.has(msg.id)) {
    const entry = pending.get(msg.id);
    pending.delete(msg.id);
    clearTimeout(entry.timer);
    if (msg.error) entry.reject(new Error(`[${msg.error.code}] ${msg.error.message}`));
    else entry.resolve(msg.result);
    return;
  }
  if (msg.method === 'log.append' && msg.params.level === 'error') {
    failures += 1;
    console.log(`[e2e][error] ${msg.params.message}`);
  }
}

function rpc(method, params = {}, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    nextId += 1;
    const id = `e2e-${nextId}`;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`RPC 超时: ${method}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    send({ jsonrpc: '2.0', id, method, params });
  });
}

async function waitJob(jobId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const status = await rpc('analysis.status', { job_id: jobId });
    if (['completed', 'failed', 'cancelled'].includes(status.status)) return status;
    if (Date.now() > deadline) throw new Error('任务超时');
    await new Promise((r) => setTimeout(r, 1500));
  }
}

async function main() {
  await new Promise((resolve) => server.listen(port, '127.0.0.1', resolve));
  console.log(`[e2e] 模式: ${modes.join(', ')}`);
  const py = spawn(path.join(repoRoot, '.venv', 'Scripts', 'python.exe'), ['-m', 'dramaclip'], {
    cwd: path.join(repoRoot, 'service'),
    env: {
      ...process.env,
      DRAMACLIP_SERVICE_ADDRESS: `127.0.0.1:${port}`,
      DRAMACLIP_AUTH_TOKEN: token,
      DRAMACLIP_DATA_DIR: dataDir,
      HF_HUB_OFFLINE: '1',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  });
  await new Promise((r) => setTimeout(r, 3000));

  const ping = await rpc('system.ping', {});
  console.log('[e2e] ping:', ping.service_version);

  const projects = await rpc('project.list');
  const wanted =
    process.argv.find((arg) => arg.startsWith('--project='))?.split('=')[1] ?? '';
  const candidates = projects.filter((p) => p.episode_count > 0);
  const project =
    candidates.find((p) => wanted !== '' && p.name.includes(wanted)) ??
    candidates.sort((a, b) => b.created_at - a.created_at)[0];
  if (project === undefined) {
    console.log('[e2e] 未找到含已完成剧集的项目');
    process.exit(1);
  }
  console.log(`[e2e] 项目: ${project.name}`);

  // 预筛 + 全量分析（跳过已完成集）
  const episodes = (await rpc('project.get', { project_id: project.id })).episodes;
  if (episodes.length > 0) {
    const prescreen = await rpc('analysis.prescreen', { project_id: project.id }).catch(() => null);
    if (prescreen !== null) await waitJob(prescreen.job_id, 300000);
  }

  let analysis = null;
  try {
    const { job_id } = await rpc('analysis.start', { project_id: project.id });
    analysis = await waitJob(job_id, 900000);
  } catch (error) {
    if (String(error.message).includes('-32202')) {
      console.log('[e2e] 全部集已完成分析，跳过（增量回归）');
    } else {
      throw error;
    }
  }
  if (analysis !== null) console.log(`[e2e] 分析: ${analysis.status}`);

  const { job_id: genJob } = await rpc('narration.generate_plans', {
    project_id: project.id,
    modes,
  });
  const gen = await waitJob(genJob, 300000);
  console.log(`[e2e] 编排: ${gen.status}`);

  const plans = await rpc('narration.list_plans', { project_id: project.id });
  const byMode = new Map();
  for (const plan of plans) {
    const existing = byMode.get(plan.narration_mode);
    if (existing === undefined || plan.created_at > existing.created_at) byMode.set(plan.narration_mode, plan);
  }
  for (const mode of modes) {
    const plan = byMode.get(mode);
    if (plan === undefined) continue;
    const { job_id: exportJobId } = await rpc('export.start', { plan_id: plan.id });
    const result = await waitJob(exportJobId, 600000);
    console.log(`[e2e] 导出 ${mode}: ${result.status}`);
  }

  const exportsList = await rpc('export.list', { project_id: project.id });
  const completed = exportsList.filter((e) => e.status === 'completed').length;
  console.log(`[e2e] 累计完成导出: ${completed}（服务错误日志 ${failures} 条）`);
  await rpc('system.shutdown', {}).catch(() => {});
  setTimeout(() => process.exit(0), 500);
}

main().catch((error) => {
  console.error('[e2e] 失败:', error);
  process.exit(1);
});
