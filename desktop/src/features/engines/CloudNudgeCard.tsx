/** 云端优先档引导卡（W4）：非 NVIDIA 主机在 ASR/TTS 页看到的引导卡。
 *
 * 内嵌 API Key 快速接入——输入 Key 即完成「创建配置→测连接→启用」，零跳页。
 * 百炼标准端点由后端兜底，用户只需粘贴 Key。按量计费口径照实写（不编价格）。
 */
import { App, Button, Input } from 'antd';
import { useState, type ReactElement } from 'react';
import { engineConfigsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

const COPY: Record<'asr' | 'tts', { hint: string; placeholder: string }> = {
  asr: {
    hint: '本机没有 NVIDIA 显卡，本地转写走 CPU。云端转写免下载免显存，按音频时长计费，通常显著更快，还带说话人分离——粘贴百炼 API Key 即可接通。',
    placeholder: '粘贴百炼 API Key（sk-…）',
  },
  tts: {
    hint: '本机没有 NVIDIA 显卡，本地合成走 CPU 较慢。云端合成免下载免显存，按字符计费，速度与音色兼得——粘贴百炼 API Key 即可接通。',
    placeholder: '粘贴百炼 API Key（sk-…）',
  },
};

const DEFAULT_MODELS: Record<'asr' | 'tts', string> = {
  asr: 'qwen3.8-asr-flash',
  tts: 'cosyvoice-v2',
};

const DOMAINS: Record<'asr' | 'tts', string> = { asr: 'asr_cloud', tts: 'tts_cloud' };

export function CloudNudgeCard({
  domain,
  onConnected,
}: {
  domain: 'asr' | 'tts';
  onConnected: () => void;
}): ReactElement {
  const { message } = App.useApp();
  const [apiKey, setApiKey] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState('');

  const connect = (): void => {
    const key = apiKey.trim();
    if (key === '' || connecting) return;
    setConnecting(true);
    setConnectError('');
    engineConfigsApi
      .create({
        domain: DOMAINS[domain],
        name: '百炼（云端）',
        base_url: '',
        api_key: key,
        model: DEFAULT_MODELS[domain],
        enable: true,
      })
      .then(() => {
        message.success('云端已接通');
        onConnected();
      })
      .catch((cause: unknown) => {
        const reason = cause instanceof Error ? cause.message : String(cause);
        setConnectError(reason);
      })
      .finally(() => setConnecting(false));
  };

  return (
    <div
      style={{
        padding: tokens.spaceMd,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.border}`,
        background: tokens.bgContainer,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceSm,
      }}
    >
      <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>
        {COPY[domain].hint}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
        <Input.Password
          size="small"
          placeholder={COPY[domain].placeholder}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          style={{ maxWidth: 320 }}
          disabled={connecting}
        />
        <Button size="small" type="primary" loading={connecting} onClick={connect}>
          一键接通
        </Button>
      </div>
      {connectError !== '' && (
        <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.colorError }}>
          {connectError}
        </span>
      )}
    </div>
  );
}
