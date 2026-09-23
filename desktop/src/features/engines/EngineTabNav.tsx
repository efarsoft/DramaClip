/** 引擎中心左侧 tab 导航：与素材列表行同构（当前查看 = 左 3px 竖条 + 主色，不铺底，DSS §3.2）。 */
import {
  ApiOutlined,
  AudioOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  ProfileOutlined,
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
  prompts: ProfileOutlined,
};

const TAB_LABELS: Record<EngineTabKey, string> = {
  overview: '总览',
  asr: '语音识别 ASR',
  tts: '配音 TTS',
  llm: '文案 LLM',
  prompts: '提示词',
};

const TAB_ORDER: readonly EngineTabKey[] = ['overview', 'asr', 'tts', 'llm', 'prompts'];

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
              ...mixins.listRow({ active }),
              width: '100%',
              border: 'none',
              borderRadius: tokens.radiusControl,
              color: active ? tokens.colorPrimary : tokens.textSecondary,
              fontSize: tokens.text.body.size,
              lineHeight: tokens.text.body.leading,
              fontWeight: active ? tokens.text.body.weightActive : tokens.text.body.weight,
              cursor: 'pointer',
            }}
          >
            <Icon style={{ fontSize: tokens.glyph.iconMd }} />
            {TAB_LABELS[key]}
          </button>
        );
      })}
      <div
        style={{
          padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: tokens.textTertiary,
        }}
      >
        云端与本地引擎随时切换
      </div>
    </nav>
  );
}
