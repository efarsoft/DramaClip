/** 引擎中心左侧 tab 导航：与素材列表行同构（主色左条 + 选中底色，DSS §4.2）。 */
import {
  ApiOutlined,
  AudioOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
} from '@ant-design/icons';
import type { ReactElement } from 'react';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import type { EngineTabKey } from './EnginesPage';

const TAB_ICONS: Record<EngineTabKey, typeof DashboardOutlined> = {
  overview: DashboardOutlined,
  asr: AudioOutlined,
  tts: CustomerServiceOutlined,
  llm: ApiOutlined,
};

const TAB_LABELS: Record<EngineTabKey, string> = {
  overview: '总览',
  asr: '语音识别 ASR',
  tts: '配音 TTS',
  llm: '文案 LLM',
};

const TAB_ORDER: readonly EngineTabKey[] = ['overview', 'asr', 'tts', 'llm'];

export function EngineTabNav({
  tab,
  onPick,
}: {
  tab: EngineTabKey;
  onPick: (key: EngineTabKey) => void;
}): ReactElement {
  return (
    <nav
      style={{
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        padding: tokens.spaceSm,
      }}
    >
      {TAB_ORDER.map((key) => {
        const active = tab === key;
        const Icon = TAB_ICONS[key];
        return (
          <button
            key={key}
            type="button"
            onClick={() => {
              onPick(key);
            }}
            style={{
              ...mixins.listRow(active),
              height: 38,
              width: '100%',
              border: 'none',
              borderLeft: `3px solid ${active ? tokens.colorPrimary : 'transparent'}`,
              borderRadius: tokens.radiusControl,
              color: active ? tokens.colorPrimary : tokens.textSecondary,
              fontSize: tokens.fontBody,
              fontWeight: active ? 600 : 400,
              cursor: 'pointer',
              marginBottom: 2,
            }}
          >
            <Icon style={{ fontSize: tokens.fontBodyLg }} />
            {TAB_LABELS[key]}
          </button>
        );
      })}
      <div
        style={{
          padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        云端与本地引擎随时切换
      </div>
    </nav>
  );
}
