/** CDP 逐页截图：连接 Electron 远程调试端口，遍历路由等待数据后截图。
 * 用法：node scripts/capture-ui.mjs <outDir>
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const OUT = process.argv[2] ?? 'scratch/ui-shots';
mkdirSync(OUT, { recursive: true });

const list = await fetch('http://127.0.0.1:9222/json/list').then((r) => r.json());
const page = list.find((t) => t.type === 'page');
if (!page) throw new Error('no page target');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let seq = 0;
const pending = new Map();
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
  });
}
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { res, rej } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
  }
};

await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 950, deviceScaleFactor: 1.25, mobile: false });

const ROUTES = [
  ['home', '#/'],
  ['projects', '#/projects'],
  ['engines-overview', '#/engines'],
  ['engines-asr', '#/engines/asr'],
  ['engines-tts', '#/engines/tts'],
  ['engines-llm', '#/engines/llm'],
  ['settings', '#/settings'],
  ['about', '#/about'],
  ['works', '#/works'],
];

for (const [name, hash] of ROUTES) {
  await send('Runtime.evaluate', { expression: `location.hash = '${hash}';` });
  await new Promise((r) => setTimeout(r, 2600));
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'));
  console.log(`captured ${name}`);
}

// 项目详情（分析工作台）与出片中心：需要真实 projectId
const proj = await send('Runtime.evaluate', {
  expression: `fetch('/@vite/client').catch(()=>{}); (async () => { return 'ok'; })()`,
  returnByValue: true,
});
// 从首页待办/项目页拿不到 id 就直接点第一个项目卡：读 window 上已有 React 状态不可行，改用 RPC 桥
const bridge = await send('Runtime.evaluate', {
  expression: `window.dramaclip ? 'bridge-ok' : 'no-bridge'`,
  returnByValue: true,
});
console.log('bridge:', bridge.result.value);
if (bridge.result.value === 'bridge-ok') {
  const ids = await send('Runtime.evaluate', {
    expression: `window.dramaclip.invoke('project.list').then(rs => rs.map(p => p.id).slice(0,2).join(','))`,
    returnByValue: true,
  });
  const idStr = ids.result.value ?? '';
  console.log('project ids:', idStr);
  const firstId = idStr.split(',')[0];
  if (firstId) {
    for (const [name, hashFn] of [['analysis', (id) => `#/projects/${id}/analysis`], ['produce', (id) => `#/projects/${id}/produce`]]) {
      await send('Runtime.evaluate', { expression: `location.hash = '${hashFn(firstId)}';` });
      await new Promise((r) => setTimeout(r, 3200));
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'));
      console.log(`captured ${name}`);
    }
    const works = await send('Runtime.evaluate', {
      expression: `window.dramaclip.invoke('export.list_works').then(rs => rs[0]?.id ?? '')`,
      returnByValue: true,
    });
    const workId = works.result.value ?? '';
    if (workId) {
      await send('Runtime.evaluate', { expression: `location.hash = '#/works/${workId}';` });
      await new Promise((r) => setTimeout(r, 3200));
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(join(OUT, 'work-detail.png'), Buffer.from(shot.data, 'base64'));
      console.log('captured work-detail');
    }
  }
}
ws.close();
console.log('done');
