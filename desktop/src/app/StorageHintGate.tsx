/** C 盘低空间首启引导：目录在 C 盘且剩余 <20GB 且未自定义/未关闭时提醒一次。
 *
 * 判据在主进程（storage.lowDiskHintActive，与存储卡同源）；这里只做一次性
 * 弹窗与跳转。「不再提醒」落 app-config.json（跨会话记住）。
 */
import { App as AntdApp } from 'antd';
import type { ReactElement } from 'react';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { dismissStorageHint, storageInfo } from '../services/client';

export function StorageHintGate(): ReactElement {
  const { modal } = AntdApp.useApp();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    void storageInfo()
      .then((info) => {
        if (cancelled || !info.lowDiskHint) return;
        modal.confirm({
          title: 'C 盘空间紧张',
          content:
            `数据目录当前在 C 盘（${info.dataDir}），剩余空间不足 20GB。` +
            '模型、运行时与成片会持续增长，建议迁移到其他磁盘。',
          okText: '去设置迁移',
          cancelText: '不再提醒',
          onOk: () => {
            void navigate('/settings');
          },
          onCancel: () => {
            void dismissStorageHint();
          },
        });
      })
      .catch(() => undefined); // 画像取不到不弹（首启失败不该变成打扰）
    return () => {
      cancelled = true;
    };
    // 只在挂载时查一次：lowDiskHint 的四个判据（目录/自定义/剩余/关闭标记）
    // 都不随页面交互变化，订阅刷新没有信息增量。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <></>;
}
