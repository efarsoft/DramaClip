/**
 * 引擎中心·总览：开工就绪度（四环节 + 待修清单）→ 三域现状 → 本机条件 + 模型资产。
 *
 * 每张卡上的「就绪 / 缺模型 / 不完整」都出自 workReadiness 与 assetState，
 * 也就是 models.list + models.verify + system.health 三份真实数据；
 * 原两张路线卡（P4）与按 model_id 猜引擎的写法一并删掉。
 */
import { AudioOutlined, EditOutlined, RightOutlined, SoundOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { mixins } from '../../styles/mixins';
import type { SettingsMap } from './EnginesPage';
import { type DomainStats, type EngineTab, type Reports, assetSummary, domainStats, formatBytes } from './assetState';
import type { ReadinessStep } from './workReadiness';
import { workReadiness } from './workReadiness';
import { SectionCard } from './AssetKit';
import { ReadinessCard } from './ReadinessCard';
import { MachinePanel } from './MachinePanel';

/** 总览 tab。 */
export function OverviewTab({
  models,
  settings,
  reports,
  ffmpegVersion,
}: {
  models: readonly ModelInfo[];
  settings: SettingsMap;
  reports: Reports;
  ffmpegVersion: string;
}): React.ReactElement {
  const navigate = useNavigate();
  const steps = workReadiness({ models, reports, settings, ffmpegVersion });
  const go = (tab: EngineTab): void => {
    void navigate(`/engines/${tab}`);
  };
  const stepOf = (key: ReadinessStep['key']): ReadinessStep | undefined =>
    steps.find((step) => step.key === key);
  const domains: readonly { tab: EngineTab; name: string; icon: ReactNode; step?: ReadinessStep; stats?: DomainStats }[] = [
    { tab: 'asr', name: '语音识别 ASR', icon: <AudioOutlined />, step: stepOf('asr'), stats: domainStats(models, reports, 'asr') },
    { tab: 'tts', name: '配音 TTS', icon: <SoundOutlined />, step: stepOf('tts'), stats: domainStats(models, reports, 'tts') },
    { tab: 'llm', name: '文案 LLM', icon: <EditOutlined />, step: stepOf('llm') },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <ReadinessCard steps={steps} models={models} reports={reports} onGo={go} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spaceLg }}>
        {domains.map((domain) => (
          <DomainCard
            key={domain.tab}
            name={domain.name}
            icon={domain.icon}
            step={domain.step}
            stats={domain.stats}
            onGo={() => {
              go(domain.tab);
            }}
          />
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: tokens.spaceLg }}>
        <MachinePanel models={models} />
        <AssetSummaryCard models={models} reports={reports} />
      </div>
    </div>
  );
}

function DomainCard({
  name,
  icon,
  step,
  stats,
  onGo,
}: {
  name: string;
  icon: ReactNode;
  step: ReadinessStep | undefined;
  stats: DomainStats | undefined;
  onGo: () => void;
}): React.ReactElement {
  const ok = step?.ok ?? false;
  const tint = ok ? tokens.colorSuccess : tokens.colorWarning;
  return (
    <SectionCard onClick={onGo}>
      <div style={{ display: 'flex', gap: tokens.spaceMd, height: '100%' }}>
        <DomainIcon>{icon}</DomainIcon>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
            <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>{name}</span>
            <span style={{ ...mixins.statusDot(tint), marginLeft: 'auto' }} />
          </div>
          <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tint }}>{step?.detail ?? '—'}</div>
          <div
            style={{
              marginTop: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: tokens.spaceXs,
              fontSize: tokens.text.meta.size,
              lineHeight: tokens.text.meta.leading,
              color: tokens.colorPrimary,
            }}
          >
            {ok ? '去调整' : step?.key === 'llm' ? '去配置' : '去处理'}
            <RightOutlined style={{ fontSize: tokens.glyph.icon }} />
            {stats !== undefined && (
              <span style={{ marginLeft: 'auto', fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
                {`${String(stats.wired)} 可用`}
                {stats.incomplete > 0 ? ` · ${String(stats.incomplete)} 待修` : ''}
              </span>
            )}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function DomainIcon({ children }: { children: ReactNode }): React.ReactElement {
  return (
    <span
      style={{
        width: 38,
        height: 38,
        borderRadius: tokens.radiusControl,
        background: tokens.accentSoft,
        color: tokens.colorPrimary,
        fontSize: tokens.glyph.chipIcon,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      {children}
    </span>
  );
}

/** 模型资产：装了几件、占多少盘、几件待修、几件还是储备。 */
function AssetSummaryCard({
  models,
  reports,
}: {
  models: readonly ModelInfo[];
  reports: Reports;
}): React.ReactElement {
  const summary = assetSummary(models, reports);
  const cells: readonly { label: string; value: string; color: string }[] = [
    {
      label: '已装 / 清单',
      value: `${String(summary.installed)} / ${String(summary.total)}`,
      color: tokens.textPrimary,
    },
    { label: '磁盘实占', value: formatBytes(summary.bytes), color: tokens.textPrimary },
    {
      label: '不完整',
      value: String(summary.incomplete),
      color: summary.incomplete > 0 ? tokens.colorError : tokens.textPrimary,
    },
    {
      label: '引擎未接入',
      value: String(summary.reserve),
      color: summary.reserve > 0 ? tokens.colorWarning : tokens.textPrimary,
    },
  ];
  return (
    <SectionCard>
      <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>模型资产</div>
      <div style={{ display: 'flex', gap: tokens.space2xl, marginTop: tokens.spaceMd, flexWrap: 'wrap' }}>
        {cells.map((cell) => (
          <div key={cell.label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: cell.color }}>{cell.value}</span>
            <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>{cell.label}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary, marginTop: tokens.spaceMd }}>
        磁盘实占按落盘文件真实字节统计，与清单标称体积不是一回事；逐件判据在域内资产库的「体检」里。
      </div>
    </SectionCard>
  );
}
