import { message } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { PingResult } from '@dramaclip/protocol';
import { appVersion, restartService, systemApi } from '../../services/client';
import { useUiStore } from '../../stores/ui';
import { tokens } from '../../styles/theme';

const STATE_LABELS: Record<string, string> = {
  starting: '启动中',
  ready: '运行中',
  restarting: '重启中',
  unavailable: '不可用',
};

/** W1 状态页：验证 端到端链路（渲染层 → 主进程 → 管道 → Python → 原路返回）。 */
export function StatusPage() {
  const [ping, setPing] = useState<PingResult | null>(null);
  const [version, setVersion] = useState('');
  const [error, setError] = useState<string | null>(null);
  const serviceState = useUiStore((state) => state.serviceState);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [pingResult, appVer] = await Promise.all([systemApi.ping(), appVersion()]);
      setPing(pingResult);
      setVersion(appVer);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, serviceState]);

  const onRestart = useCallback(async () => {
    await restartService();
    void message.success('已请求重启 Python 服务');
  }, []);

  return (
    <section style={{ maxWidth: 720 }}>
      <h2 style={{ color: tokens.textPrimary, marginBottom: 16 }}>服务状态</h2>
      <dl style={{ display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: 8 }}>
        <Item label="应用版本" value={version || '…'} />
        <Item label="服务状态" value={STATE_LABELS[serviceState] ?? serviceState} />
        <Item
          label="服务版本"
          value={ping ? `${ping.service_version}（协议 v${String(ping.protocol_version)}）` : '…'}
        />
        <Item label="链路验证" value={ping ? 'Python 往返正常 ✅' : (error ?? '获取中…')} />
      </dl>
      <footer style={{ marginTop: 16, color: tokens.textTertiary, fontSize: 12 }}>
        版本号经命名管道真实 RPC 往返（ADR-002）。
        <button type="button" onClick={() => void onRestart()} style={{ marginLeft: 12 }}>
          重启服务
        </button>
      </footer>
    </section>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: tokens.textSecondary }}>{label}</dt>
      <dd style={{ margin: 0, color: tokens.textPrimary, fontFamily: tokens.fontFamilyMono }}>
        {value}
      </dd>
    </>
  );
}
