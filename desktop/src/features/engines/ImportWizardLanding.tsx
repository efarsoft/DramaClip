/**
 * 第 ③④ 步：落位方式与收尾。
 *
 * 第 ③ 步只说文件会去哪儿、要占多少余量（全部出自第 ② 步的实测字段）；
 * 第 ④ 步只念登记本与作业给的事实——落位路径出自登记本，失败原因出自作业，这里不拼话术。
 */
import type { ReactElement } from 'react';
import { Button, Radio } from 'antd';
import type { ImportInspection, ImportRecord } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import {
  type ImportDraft,
  MODE_LABEL,
  VERDICT_LABEL,
  activatableAfterImport,
  effectiveMode,
  modeChoices,
  modeHint,
} from './importWizard';
import { Chip, Field, Hint } from './ImportBits';

export function LandStep({
  report,
  draft,
  onChange,
}: {
  report: ImportInspection;
  draft: ImportDraft;
  onChange: (draft: ImportDraft) => void;
}): ReactElement {
  const mode = effectiveMode(draft, report);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <b>落位方式</b>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {modeChoices(report).map((choice) => (
          <Radio
            key={choice}
            checked={mode === choice}
            onChange={() => {
              onChange({ ...draft, mode: choice });
            }}
          >
            {MODE_LABEL[choice]}
            <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
              {modeHint(choice, report)}
            </div>
          </Radio>
        ))}
      </div>
      {report.conflict != null && mode !== 'register' && draft.onConflict !== '' && (
        <Hint>{`冲突已裁决：${VERDICT_LABEL[draft.onConflict]}`}</Hint>
      )}
      {!report.recognized && (
        <Hint>仅登记：文件留在业主自己的盘上，资产库里它是「外部资产 · 引擎未接入」，只能移除、不能选为生效。</Hint>
      )}
    </div>
  );
}

export function DoneStep({
  report,
  placed,
  percent,
  running,
  onActivate,
}: {
  report: ImportInspection;
  placed: ImportRecord | null;
  percent: number;
  running: boolean;
  onActivate: (modelId: string) => void;
}): ReactElement {
  if (running) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        <b>{`落位中 ${String(Math.floor(percent))}%`}</b>
        <Hint>GB 级复制中途停不下来；关闭此窗作业照旧跑完。</Hint>
      </div>
    );
  }
  if (placed === null) {
    return (
      <Hint>作业已结束，但登记本里没有这次导入的登记——回资产库核对它的实际状态，这里不当成功。</Hint>
    );
  }
  const externalAsset = placed.model_id === null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
      <Field label="结果">
        <b>{`${externalAsset ? '已登记' : '已导入'} · ${placed.path}`}</b>
      </Field>
      <div style={{ display: 'flex', gap: tokens.spaceSm, flexWrap: 'wrap' }}>
        <Chip>来源标记：本地导入</Chip>
        {externalAsset && <Chip>外部资产 · 引擎未接入</Chip>}
        {!externalAsset && !report.engine_ready && (
          <Chip>引擎未接入 · 待接入后才能生效</Chip>
        )}
        {placed.incomplete && <Chip>不完整 · 待补齐</Chip>}
      </div>
      {!externalAsset && activatableAfterImport(report) && (
        <div>
          <Button
            size="small"
            type="primary"
            onClick={() => {
              onActivate(placed.model_id ?? '');
            }}
          >
            选为生效
          </Button>
        </div>
      )}
    </div>
  );
}
