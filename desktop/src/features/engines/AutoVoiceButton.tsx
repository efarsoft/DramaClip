/** 从剧集自动提取主角参考音色：声纹聚类选主角最清晰一段 → 人声分离 → 直接设为参考。
 *  解决「IndexTTS 要参考音色，用户还得自己去剧集里找一段 wav」的摩擦——
 *  剧集本身就是最好的音色库，分析数据里连谁在什么时候说了什么都有。 */
import { App, Button } from 'antd';
import { useState, type ReactElement } from 'react';
import { ttsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

export function AutoVoiceButton({
  onSave,
  disabled,
}: {
  onSave: (voicePath: string) => void;
  disabled?: boolean;
}): React.ReactElement {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="small"
      loading={busy}
      disabled={disabled}
      style={{ color: tokens.textSecondary }}
      onClick={() => {
        setBusy(true);
        ttsApi
          .autoVoice()
          .then((result) => {
            onSave(result.path);
            const grade =
              result.quality === 'good' ? '优' : result.quality === 'fair' ? '中' : '差';
            message.success(
              `已从剧集提取主角音色（${result.speaker}，${String(result.seconds)} 秒，质检 ${grade}），并设为参考音色`,
              6,
            );
          })
          .catch((cause: unknown) => {
            message.error(cause instanceof Error ? cause.message : '自动提取失败', 6);
          })
          .finally(() => {
            setBusy(false);
          });
      }}
    >
      从剧集提取
    </Button>
  );
}
