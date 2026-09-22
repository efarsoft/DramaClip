/** 阶段①（规格 §6 的 ③）：选模式、定每个模式出几条，发起规划并显示进度。 */
import { Alert, Button, Card, Select, Tag } from 'antd';
import { PageSection } from '../../components/layout/PageKit';
import type { NarrationMode } from '@dramaclip/protocol';
import { MODE_INFO } from '../../components/modeMeta';
import { layout, tokens } from '../../styles/theme';
import type { PlanBatch } from './usePlanBatch';
import { StageProgress } from './StageProgress';

/** 与服务端 `_MAX_VARIANTS` 同口径；默认 3 = config 的 narration.variants_per_mode。 */
const K_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8];

export function ModePicker({
  batch,
  modes,
  k,
  onToggleMode,
  onSelectAll,
  onKChange,
}: {
  batch: PlanBatch;
  modes: NarrationMode[];
  k: number;
  onToggleMode: (mode: NarrationMode) => void;
  onSelectAll: () => void;
  onKChange: (k: number) => void;
}) {
  return (
    <PageSection title="① 选模式，出方案">
      <ModeGrid modes={modes} onToggleMode={onToggleMode} />
      <PlanToolbar batch={batch} modes={modes} k={k} onSelectAll={onSelectAll} onKChange={onKChange} />
      {batch.error !== '' && <Alert style={{ marginTop: tokens.spaceMd }} type="error" showIcon title={batch.error} />}
    </PageSection>
  );
}

function PlanToolbar({
  batch,
  modes,
  k,
  onSelectAll,
  onKChange,
}: {
  batch: PlanBatch;
  modes: NarrationMode[];
  k: number;
  onSelectAll: () => void;
  onKChange: (k: number) => void;
}) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: tokens.spaceLg, gap: tokens.spaceMd, flexWrap: 'wrap' }}>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          已选 {String(modes.length)} / {String(MODE_INFO.length)} 个模式
        </span>
        <Button size="small" disabled={batch.planning} onClick={onSelectAll}>
          全选
        </Button>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary, marginLeft: tokens.spaceMd }}>每个模式</span>
        <Select
          size="small"
          style={{ width: 92 }}
          disabled={batch.planning}
          value={k}
          onChange={(value: number) => {
            onKChange(value);
          }}
          options={K_OPTIONS.map((n) => ({ value: n, label: `${String(n)} 条` }))}
        />
        <Button
          type="primary"
          style={{ marginLeft: 'auto' }}
          disabled={modes.length === 0}
          loading={batch.planning}
          onClick={() => {
            void batch.run(modes, k);
          }}
        >
          {batch.planning ? '规划中…' : '生成方案'}
        </Button>
        {batch.planning && (
          <Button
            onClick={() => {
              void batch.cancel();
            }}
          >
            取消规划
          </Button>
        )}
      </div>
      {batch.planning && <StageProgress percent={batch.percent} stageText={batch.stageText} />}
    </>
  );
}

function ModeGrid({ modes, onToggleMode }: { modes: NarrationMode[]; onToggleMode: (mode: NarrationMode) => void }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: tokens.spaceMd }}>
      {MODE_INFO.map((item) => (
        <ModeTile
          key={item.mode}
          label={item.label}
          desc={item.desc}
          needs={item.needs}
          checked={modes.includes(item.mode as NarrationMode)}
          onToggle={() => {
            onToggleMode(item.mode as NarrationMode);
          }}
        />
      ))}
    </div>
  );
}

function ModeTile({
  label,
  desc,
  needs,
  checked,
  onToggle,
}: {
  label: string;
  desc: string;
  needs: ('copy' | 'voice')[];
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      size="small"
      hoverable
      onClick={onToggle}
      style={{
        borderColor: checked ? tokens.colorPrimary : tokens.border,
        background: checked ? tokens.accentSoft : undefined,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
          <strong style={{ color: tokens.textPrimary, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading }}>{label}</strong>
          {checked && (
            <Tag color="blue" style={{ marginRight: 0 }}>
              已选
            </Tag>
          )}
        </div>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>{desc}</span>
        <span style={{ display: 'flex', gap: tokens.spaceSm, marginTop: 'auto' }}>
          {needs.includes('copy') ? <NeedBadge text="含 AI 文案" /> : <NeedBadge text="无需文案" muted />}
          {needs.includes('voice') ? <NeedBadge text="含 AI 配音" /> : <NeedBadge text="原声" muted />}
        </span>
      </div>
    </Card>
  );
}

function NeedBadge({ text, muted = false }: { text: string; muted?: boolean }): React.ReactElement {
  return (
    <span
      style={{
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        padding: `${String(layout.chip.paddingBlock)}px ${layout.chip.paddingInline}`,
        borderRadius: tokens.radiusChip,
        color: muted ? tokens.textTertiary : tokens.colorSuccess,
        border: `1px solid ${tokens.border}`,
        background: muted ? 'transparent' : tokens.successSoft,
      }}
    >
      {text}
    </span>
  );
}
