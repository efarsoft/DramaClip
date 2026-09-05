import { useEffect } from 'react';
import { AppLayout } from '../components/layout/AppLayout';
import { onServiceEvent } from '../services/client';
import { subscribeAnalysisProgress, useUiStore } from '../stores/ui';

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

  return <AppLayout />;
}
