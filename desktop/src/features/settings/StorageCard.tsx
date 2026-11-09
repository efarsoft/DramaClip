/** 存储卡片：数据目录画像 + 迁移（客户端层能力，不进 settings.get 服务端体系）。
 *
 * 迁移编排全在主进程（复制→校验→写配置→旧目录改名留痕），这里只做：
 * 展示（目录/占用/剩余）、确认对话、结果反馈；成功后整应用重启归零
 * （dataDir 锚点分散在 Electron 三处闭包，只重启服务不够）。
 */
import { App as AntdApp, Button, Modal, Tag, Tooltip } from 'antd';
import type { ReactElement } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { PageSection } from '../../components/layout/PageKit';
import { migrateDataDir, pickFolder, relaunchApp, storageInfo } from '../../services/client';
import type { StorageInfo } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 GB';
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

export function StorageCard(): ReactElement {
  const { message } = AntdApp.useApp();
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [migrating, setMigrating] = useState(false);

  const load = useCallback(async () => {
    try {
      setInfo(await storageInfo());
    } catch {
      setInfo(null); // 画像取不到：卡片显示不可用，不装死
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const startMigrate = useCallback(async () => {
    if (info === null) return;
    const target = await pickFolder();
    if (target === null || target.length === 0) return;
    const totalBytes = info.usage.reduce((sum, entry) => sum + entry.bytes, 0);
    Modal.confirm({
      title: '迁移数据目录',
      content:
        `将把 ${formatBytes(totalBytes)} 数据从\n${info.dataDir}\n复制到\n${target}\n\n` +
        '迁移期间请不要操作应用（有任务在跑会被拒绝）；完成后应用自动重启，' +
        '旧目录会改名为 .bak-日期 保留，确认无误后可手动删除。',
      okText: '开始迁移',
      cancelText: '取消',
      onOk: async () => {
        setMigrating(true);
        try {
          const result = await migrateDataDir(target);
          if (result.ok) {
            message.success(`迁移完成，应用即将重启（旧目录：${result.backupDir ?? ''}）`);
            await relaunchApp();
          } else {
            message.error(result.reason ?? '迁移失败');
          }
        } catch (error) {
          message.error(error instanceof Error ? error.message : String(error));
        } finally {
          setMigrating(false);
        }
      },
    });
  }, [info, message]);

  return (
    <PageSection
      title="存储"
      dense
      extra={
        info?.migrationAvailable ? (
          <Tooltip title="选择一个空目录（其他磁盘），复制迁移后自动重启生效">
            <Button size="small" loading={migrating} onClick={() => { void startMigrate(); }}>
              更改数据目录…
            </Button>
          </Tooltip>
        ) : undefined
      }
    >
      {info === null ? (
        <div style={{ ...mixins.listRow(), padding: `${tokens.spaceSm} ${tokens.spaceLg}` }}>
          存储信息不可用
        </div>
      ) : (
        <>
          <div style={{ ...mixins.listRow(), padding: `${tokens.spaceSm} ${tokens.spaceLg}` }}>
            <span style={{ ...tokens.text.body, color: tokens.textSecondary, display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
              数据目录
              {info.customized && <Tag color="blue">自定义</Tag>}
            </span>
            <span style={{ ...tokens.text.body, marginLeft: 'auto', wordBreak: 'break-all', maxWidth: 360 }}>
              {info.dataDir}
            </span>
          </div>
          <div style={{ ...mixins.listRow(), padding: `${tokens.spaceSm} ${tokens.spaceLg}` }}>
            <span style={{ ...tokens.text.body, color: tokens.textSecondary }}>所在盘剩余</span>
            <span style={{ ...tokens.text.body, marginLeft: 'auto' }}>
              {formatBytes(info.freeBytes)}
              {info.lowDiskHint && (
                <Tag color="red" style={{ marginLeft: tokens.spaceSm }}>
                  空间紧张
                </Tag>
              )}
            </span>
          </div>
          {info.usage.map((entry) => (
            <div
              key={entry.name}
              style={{ ...mixins.listRow(), padding: `${tokens.spaceSm} ${tokens.spaceLg}` }}
            >
              <span style={{ ...tokens.text.body, color: tokens.textSecondary }}>{entry.name}</span>
              <span style={{ ...tokens.text.body, marginLeft: 'auto' }}>{formatBytes(entry.bytes)}</span>
            </div>
          ))}
          {!info.migrationAvailable && (
            <div
              style={{
                ...mixins.listRow(),
                padding: `${tokens.spaceSm} ${tokens.spaceLg}`,
                color: tokens.textSecondary,
                fontSize: tokens.text.meta.size,
              }}
            >
              开发态数据目录由 DRAMACLIP_DATA_DIR 环境变量决定，迁移仅在安装版可用
            </div>
          )}
        </>
      )}
    </PageSection>
  );
}
