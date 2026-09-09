import { useEffect } from 'react';
import { AppLayout } from '../components/layout/AppLayout';
import { onServiceEvent, systemApi } from '../services/client';
import { subscribeAnalysisProgress, subscribeModelDownloadProgress, useUiStore } from '../stores/ui';

/** 应用壳：装配全局事件订阅 + 布局（docs/desktop/01 §1）。 */
export function App() {
  const setServiceState = useUiStore((state) => state.setServiceState);

  useEffect(
    () =>
      onServiceEvent((event) => {
        if (event.type === 'service-state') setServiceState(event.state);
      }),
    [setServiceState],
  );
  useEffect(() => subscribeAnalysisProgress(), []);
  useEffect(() => subscribeModelDownloadProgress(), []);

  // 刷新后补发事件可能早于订阅，主动校准一次服务状态
  useEffect(() => {
    void systemApi.health()
      .then(() => {
        setServiceState('ready');
      })
      .catch(() => {
        setServiceState('unavailable');
      });
  }, [setServiceState]);

  return <AppLayout />;
}
