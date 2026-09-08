/** 解说风格选择卡：读取风格库 + 当前偏好，切换即保存。 */
import { App as AntdApp, Card, Select } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { StyleInfo } from '@dramaclip/protocol';
import { narrationApi, settingsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

const DEFAULT_ID = 'general';

export function StyleSelectCard(): React.ReactElement {
  const { message } = AntdApp.useApp();
  const [styles, setStyles] = useState<StyleInfo[]>([]);
  const [styleId, setStyleId] = useState(DEFAULT_ID);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void narrationApi
      .listStyles()
      .then(setStyles)
      .catch(() => setStyles([]));
    void settingsApi
      .get()
      .then((values) => {
        setStyleId(values['narration.style_id'] ?? DEFAULT_ID);
      })
      .catch(() => undefined);
  }, []);

  const current = styles.find((style) => style.style_id === styleId);

  const change = useCallback(
    (next: string): void => {
      setSaving(true);
      settingsApi
        .update({ 'narration.style_id': next })
        .then(() => {
          setStyleId(next);
        })
        .catch((error: unknown) => {
          message.error(error instanceof Error ? error.message : String(error));
        })
        .finally(() => {
          setSaving(false);
        });
    },
    [message],
  );

  return (
    <Card
      size="small"
      title="解说风格"
      styles={{ body: { padding: '10px 14px' } }}
      loading={styles.length === 0 && saving === false}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Select
          style={{ width: 220 }}
          value={styleId}
          loading={saving}
          disabled={saving}
          onChange={change}
          options={styles.map((style) => ({
            label: style.name,
            value: style.style_id,
          }))}
        />
        {current !== undefined && (
          <span style={{ fontSize: 12.5, color: tokens.textTertiary, minWidth: 0 }}>
            {current.desc}
          </span>
        )}
      </div>
      <div style={{ marginTop: 8, fontSize: 11.5, color: tokens.textTertiary }}>
        风格注入 AI 编剧（解说类模式生效）；纯剪辑模式不受影响。仅 LLM 已配置时可用。
      </div>
    </Card>
  );
}
