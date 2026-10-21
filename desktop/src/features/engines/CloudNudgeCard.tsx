/** 云端引导卡（规划批 A1/A2）：非阻塞提示，一键切到云端配置页签。
 *
 * 计费口径照抄模型规格 notes 的事实（ASR 按音频时长、TTS 按字符），
 * 不写具体价格——价格会变，编造的数字比没有数字更糟。
 */
import { Alert, Button } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

const COPY: Record<'asr' | 'tts', Record<'guide' | 'switch', string>> = {
  asr: {
    guide:
      '本机没有 NVIDIA 显卡，本地转写走 CPU。云端转写免下载免显存，按音频时长计费，'
      + '通常显著更快，还带说话人分离——接一条配置即可用。',
    switch: '已有云端转写配置但未启用：启用后下次分析即走云端。',
  },
  tts: {
    guide:
      '本机没有 NVIDIA 显卡，本地合成走 CPU 较慢。云端合成免下载免显存，按字符计费，'
      + '速度与音色兼得——接一条配置即可用。',
    switch: '已有云端合成配置但未启用：启用后配音即走云端。',
  },
};

export function CloudNudgeCard({
  domain,
  kind,
  onGoCloud,
}: {
  domain: 'asr' | 'tts';
  kind: 'guide' | 'switch';
  onGoCloud: () => void;
}): ReactElement {
  return (
    <Alert
      type="info"
      showIcon
      title={COPY[domain][kind]}
      style={{ borderRadius: tokens.radiusCard }}
      action={
        <Button size="small" type="primary" ghost onClick={onGoCloud}>
          去云端配置
        </Button>
      }
    />
  );
}
