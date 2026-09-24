/** 假 Python 服务：说 NDJSON 握手协议，供 service-manager 生命周期测试用。
 * system.ping → {}；crash.now → 立即 exit(1)（模拟崩溃）；system.shutdown → exit(0)。 */
import net from 'node:net';

const address = process.env.DRAMACLIP_SERVICE_ADDRESS ?? '';
const [host, port] = address.split(':');
const socket = net.connect({ host, port: Number(port) });
socket.setEncoding('utf8');
let buffer = '';
socket.on('data', (chunk) => {
  buffer += chunk;
  let idx = buffer.indexOf('\n');
  while (idx >= 0) {
    const line = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 1);
    if (line) handle(line);
    idx = buffer.indexOf('\n');
  }
});

function send(payload) {
  socket.write(`${JSON.stringify(payload)}\n`);
}

function handle(line) {
  const msg = JSON.parse(line);
  if (msg.type === 'hello-ack') return;
  if (msg.method === 'crash.now') {
    socket.destroy();
    process.exit(1);
  }
  if (msg.method === 'system.shutdown') {
    socket.destroy();
    process.exit(0);
  }
  send({ jsonrpc: '2.0', id: msg.id, result: {} });
}

send({
  type: 'hello',
  token: process.env.DRAMACLIP_AUTH_TOKEN ?? '',
  service_version: 'fake',
  protocol_version: 1,
});
