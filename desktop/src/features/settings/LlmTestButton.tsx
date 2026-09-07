/** LLM 连通性测试按钮：按已保存配置探测端点（提示先保存再测试）。 */
import { App as AntdApp, Button, Tag } from 'antd';
import { useState, type ReactElement } from 'react';
import { rpc } from '../../services/client';

interface TestResult {
  readonly ok: boolean;
  readonly latency_ms: number;
  readonly model: string;
}

export function LlmTestButton(): ReactElement {
  const { message } = AntdApp.useApp();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  const test = (): void => {
    setTesting(true);
    setResult(null);
    rpc<TestResult>('settings.test_llm', {})
      .then((res) => {
        setResult(res);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setTesting(false);
      });
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {result !== null && (
        <Tag color="success" style={{ marginRight: 0 }}>
          连接正常 · {result.model} · {String(result.latency_ms)}ms
        </Tag>
      )}
      <Button size="small" loading={testing} onClick={test}>
        测试连接
      </Button>
    </div>
  );
}
