// @vitest-environment node
/** 存储管理（数据目录重定向+迁移）纯逻辑与编排：配置往返、判据矩阵、小样本真迁移。 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import {
  dirBytes,
  freeBytes,
  loadAppConfig,
  lowDiskHintActive,
  migrateDataDir,
  resolveDataDir,
  saveAppConfig,
  storageUsage,
} from './storage';

const TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'dc-storage-'));
const dir = (name: string): string => path.join(TMP_ROOT, name);

afterAll(async () => {
  await fsp.rm(TMP_ROOT, { recursive: true, force: true });
});

describe('app-config 往返与容错', () => {
  it('缺失/坏 JSON 回全默认（首装常态不是错误）', () => {
    const userData = dir('cfg-empty');
    fs.mkdirSync(userData, { recursive: true });
    expect(loadAppConfig(userData)).toEqual({});
    fs.writeFileSync(path.join(userData, 'app-config.json'), '{bad json', 'utf8');
    expect(loadAppConfig(userData)).toEqual({});
  });

  it('保存往返保自定义目录与提醒标记；非字符串 dataDir 归未配置', async () => {
    const userData = dir('cfg-rw');
    fs.mkdirSync(userData, { recursive: true });
    await saveAppConfig(userData, { dataDir: 'D:\\DramaClipData', storageHintDismissed: true });
    expect(loadAppConfig(userData)).toEqual({
      dataDir: 'D:\\DramaClipData',
      storageHintDismissed: true,
    });
    await saveAppConfig(userData, {});
    expect(loadAppConfig(userData)).toEqual({});
    fs.writeFileSync(
      path.join(userData, 'app-config.json'),
      JSON.stringify({ dataDir: 123 }),
      'utf8',
    );
    expect(loadAppConfig(userData).dataDir).toBeUndefined();
  });
});

describe('resolveDataDir：配置目录被删时回退默认并留痕', () => {
  it('存在则自定义生效；不存在回退默认', () => {
    const userData = dir('resolve');
    fs.mkdirSync(userData, { recursive: true });
    const defaultDir = path.join(userData, 'data');
    expect(resolveDataDir(userData, defaultDir, { dataDir: userData })).toEqual({
      dataDir: userData,
      customized: true,
    });
    expect(resolveDataDir(userData, defaultDir, { dataDir: dir('gone') })).toEqual({
      dataDir: defaultDir,
      customized: false,
    });
  });
});

describe('lowDiskHintActive 判据矩阵', () => {
  const gb = (n: number): number => n * 1024 ** 3;
  it('四判据全过才提醒：C 盘+未自定义+未关闭+剩余<20GB', () => {
    expect(lowDiskHintActive('C:\\x\\data', false, false, gb(10), 'win32')).toBe(true);
    expect(lowDiskHintActive('C:\\x\\data', false, false, gb(25), 'win32')).toBe(false);
    expect(lowDiskHintActive('C:\\x\\data', true, false, gb(10), 'win32')).toBe(false);
    expect(lowDiskHintActive('C:\\x\\data', false, true, gb(10), 'win32')).toBe(false);
    expect(lowDiskHintActive('D:\\x\\data', false, false, gb(10), 'win32')).toBe(false);
    expect(lowDiskHintActive('/home/x/data', false, false, gb(10), 'linux')).toBe(false);
    expect(lowDiskHintActive('C:\\x\\data', false, false, null, 'win32')).toBe(false);
  });
});

describe('占用统计', () => {
  it('子目录递归求和 + 根散件并账，按大小降序', async () => {
    const dataDir = dir('usage');
    fs.mkdirSync(path.join(dataDir, 'models', 'nested'), { recursive: true });
    fs.mkdirSync(path.join(dataDir, 'outputs'), { recursive: true });
    fs.writeFileSync(path.join(dataDir, 'models', 'big.bin'), Buffer.alloc(2000));
    fs.writeFileSync(path.join(dataDir, 'models', 'nested', 'small.bin'), Buffer.alloc(100));
    fs.writeFileSync(path.join(dataDir, 'outputs', 'mid.bin'), Buffer.alloc(500));
    fs.writeFileSync(path.join(dataDir, 'data.db'), Buffer.alloc(50));
    const usage = await storageUsage(dataDir);
    const byName = Object.fromEntries(usage.map((entry) => [entry.name, entry.bytes]));
    expect(byName.models).toBe(2100);
    expect(byName.outputs).toBe(500);
    expect(byName['数据库与散件']).toBe(50);
    expect(usage[0]?.name).toBe('models'); // 降序
    expect(await dirBytes(dir('no-such'))).toBe(0);
  });
});

describe('freeBytes：真盘探测量（回归冒烟）', () => {
  it('系统临时目录返回正数', async () => {
    const free = await freeBytes(TMP_ROOT);
    expect(free === null || free > 0).toBe(true);
  });
});

describe('migrateDataDir 编排', () => {
  const idle = { ensureIdle: () => Promise.resolve(true) };
  const makeSource = (name: string): string => {
    const source = dir(name);
    fs.mkdirSync(path.join(source, 'models'), { recursive: true });
    fs.writeFileSync(path.join(source, 'data.db'), Buffer.alloc(64));
    fs.writeFileSync(path.join(source, 'models', 'm.bin'), Buffer.alloc(128));
    return source;
  };

  it('成功路径：复制+校验+写配置+旧目录改名 .bak-日期', async () => {
    const userData = dir('mig-user');
    fs.mkdirSync(userData, { recursive: true });
    const source = makeSource('mig-src');
    const target = dir('mig-dst');
    const result = await migrateDataDir(userData, source, target, idle);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(fs.existsSync(path.join(target, 'data.db'))).toBe(true);
      expect(result.backupDir.startsWith(`${source}.bak-`)).toBe(true);
      expect(fs.existsSync(result.backupDir)).toBe(true);
      expect(fs.existsSync(source)).toBe(false);
      expect(loadAppConfig(userData).dataDir).toBe(target);
    }
  });

  it('相同目录与非空目标拒绝', async () => {
    const userData = dir('mig-user2');
    const source = makeSource('mig-src2');
    const same = await migrateDataDir(userData, source, source, idle);
    expect(same.ok).toBe(false);
    if (!same.ok) expect(same.reason).toContain('相同');
    const occupied = dir('mig-occupied');
    fs.mkdirSync(occupied, { recursive: true });
    fs.writeFileSync(path.join(occupied, 'keep.txt'), 'x', 'utf8');
    const busy = await migrateDataDir(userData, source, occupied, idle);
    expect(busy.ok).toBe(false);
    if (!busy.ok) expect(busy.reason).toContain('空目录');
  });

  it('有任务在跑拒绝（宁可拒绝不可带任务搬家）', async () => {
    const userData = dir('mig-user3');
    const source = makeSource('mig-src3');
    const target = dir('mig-dst3');
    const result = await migrateDataDir(userData, source, target, {
      ensureIdle: () => Promise.resolve(false),
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain('任务');
    expect(fs.existsSync(target) ? (await fsp.readdir(target)).length > 0 : false).toBe(false);
  });

  it('缺 data.db 校验失败：判迁移失败且不写配置（等于没迁移）', async () => {
    const userData = dir('mig-user4');
    const source = dir('mig-src4'); // 无 data.db 的坏源
    fs.mkdirSync(path.join(source, 'models'), { recursive: true });
    fs.writeFileSync(path.join(source, 'models', 'm.bin'), Buffer.alloc(8));
    const target = dir('mig-dst4');
    const result = await migrateDataDir(userData, source, target, idle);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain('data.db');
    expect(loadAppConfig(userData).dataDir).toBeUndefined();
  });
});
