/** 解说风格选择卡：自动匹配（默认）+ 风格库，切换即保存。 */
import { App as AntdApp, Card, Select } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { StyleInfo } from '@dramaclip/protocol';
import { narrationApi, settingsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

const AUTO_ID = 'auto';
const DEFAULT_ID = AUTO_ID;
const AUTO_STYLE: StyleInfo = {
  style_id: AUTO_ID,
  name: '自动匹配（推荐）',
  desc: '按剧情题材自动选择最合适的风格',
  directives: '',
};

function persistStyle(
  next: string,
  message: { error: (text: string) => void },
  setStyleId: (id: string) => void,
  setSaving: (saving: boolean) => void,
): void {
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
}

export function StyleSelectCard(): React.ReactElement {
  const { message } = AntdApp.useApp();
  const [styles, setStyles] = useState<StyleInfo[]>([]);
  const [styleId, setStyleId] = useState(DEFAULT_ID);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void narrationApi
      .listStyles()
      .then(setStyles)
      .catch(() => {
        setStyles([]);
      });
    void settingsApi
      .get()
      .then((values) => {
        setStyleId(values['narration.style_id'] ?? DEFAULT_ID);
      })
      .catch(() => undefined);
  }, []);

  const change = useCallback(
    (next: string): void => {
      persistStyle(next, message, setStyleId, setSaving);
    },
    [message],
  );

  const current =
    styleId === AUTO_ID
      ? AUTO_STYLE
      : styles.find((style) => style.style_id === styleId);

  return (
    <Card
      size="small"
      title="解说风格"
      styles={{ body: { padding: '10px 14px' } }}
      loading={styles.length === 0 && !saving}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
        <Select
          style={{ width: 220 }}
          value={styleId}
          loading={saving}
          disabled={saving}
          onChange={change}
          options={[AUTO_STYLE, ...styles].map((style) => ({
            label: style.name,
            value: style.style_id,
          }))}
        />
        {current !== undefined && (
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary, minWidth: 0 }}>
            {current.desc}
          </span>
        )}
      </div>
      <div style={{ marginTop: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        自动匹配按分析阶段的题材判定（如 悬疑→悬疑反转、逆袭→爽感逆袭）；风格注入 AI 编剧，对话解说模式生效，仅 LLM 已配置时可用。
      </div>
    </Card>
  );
}
