/** IndexTTS 的音色=参考音频：文件选择代替下拉（零样本克隆任意人声）。 */
import { Button } from 'antd';
import type { ReactElement } from 'react';
import { pickAudioFile } from '../../services/client';
import { tokens } from '../../styles/theme';
import type { DomainTabProps } from './EnginesPage';
import { voiceSettingKey } from './ttsVoices';

export function RefVoiceSelect({
  settings,
  onSave,
}: {
  settings: DomainTabProps['settings'];
  onSave: DomainTabProps['onSave'];
}): ReactElement {
  const key = voiceSettingKey('indextts2');
  const value = settings[key] ?? '';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spaceSm }}>
      <Button
        size="small"
        onClick={() => {
          void pickAudioFile().then((path) => {
            if (path !== null) onSave({ [key]: path });
          });
        }}
      >
        {value === '' ? '选择参考音频' : '更换参考音频'}
      </Button>
      <span
        style={{
          maxWidth: 220,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: value === '' ? tokens.colorWarning : tokens.textTertiary,
        }}
        title={value}
      >
        {value === '' ? '未选择——合成需要一段 3~10 秒人声' : value}
      </span>
    </span>
  );
}
