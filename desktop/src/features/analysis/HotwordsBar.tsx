/** 剧级热词条（2026-11-12 业主裁决：人工热词从全局改项目级）：一部剧点名的
 * 专名只喂这一部剧的转写引导，换剧自动隔离——此前全局键让上一部剧的人名
 * 混进下一部的热词表。保存写 projects.settings，下次分析生效。 */
import { App as AntdApp, Input } from 'antd';
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { projectApi } from '../../services/client';
import { tokens } from '../../styles/theme';

export const HOTWORDS_KEY = 'asr.hotwords_extra';

const META = {
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
} as const;

export function HotwordsBar({
  projectId,
  value,
  onSaved,
}: {
  projectId: string;
  /** 当前项目的热词原文（project.settings 里读出）；空串 = 未录入。 */
  value: string;
  onSaved: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);

  const save = async (): Promise<void> => {
    const next = draft.trim();
    if (next === value) return;
    try {
      await projectApi.updateSettings(projectId, { [HOTWORDS_KEY]: next });
      message.success(next === '' ? '本剧热词已清空，下次分析生效' : '本剧热词已保存，下次分析生效');
      onSaved();
    } catch (error) {
      message.error(`本剧热词没存上：${String(error)}`);
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
      <span style={{ ...META, color: tokens.textSecondary }}>本剧热词</span>
      <Input
        size="small"
        style={{ width: 440, maxWidth: '100%' }}
        placeholder="这部剧的人名/专名，顿号、逗号或空格分隔——转写时永远排最前"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        onBlur={() => {
          void save();
        }}
        onPressEnter={(event) => {
          void save();
          event.currentTarget.blur();
        }}
      />
      <span style={{ ...META, color: tokens.textTertiary }}>只对本剧生效（换剧自动隔离）· 保存后下次分析生效</span>
    </div>
  );
}
