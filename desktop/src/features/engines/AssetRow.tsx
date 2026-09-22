/**
 * 资产库的一行：名称 / 引擎接入 / 安装态 / 大小 / 评级 / 说明 / 动作。
 *
 * 每格只翻译一个真实字段：安装态出自 status + 体检结论，大小出自落盘字节，
 * 可行性出自 system.health 的容量余量——前端不写死任何一格。
 */
import { useState } from 'react';
import type { ReactElement } from 'react';
import type { ModelInfo, VerifyReport } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { type AssetState, assetState, failureNote, formatBytes } from './assetState';
import { RatingDots, StateBadge, StateDot } from './AssetKit';
import { FIT_VERDICT_COLOR, judgeModelFit, type MachineSpecs, parseSizeGb } from './machineFit';
import { GRID } from './assetGrid';
import { RowActions } from './RowActions';
import { VerifyDetail } from './VerifyDetail';
import { useDownloadProgress } from './useDownloadProgress';

export interface AssetRowProps {
  model: ModelInfo;
  report: VerifyReport | undefined;
  specs: MachineSpecs;
  active: boolean;
  onActivate: (model: ModelInfo) => void;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
  /** 域自带的行内动作（配音 = 试听）：由调用方造好节点，这一行只管摆哪儿。 */
  preview?: ReactElement;
  table?: boolean;
}

export function AssetRow({
  model,
  report,
  specs,
  active,
  onActivate,
  onChanged,
  onVerify,
  preview,
  table = false,
}: AssetRowProps): ReactElement {
  const [detail, setDetail] = useState(false);
  const state = assetState(model, report);
  return (
    <div style={{ borderTop: `1px solid ${tokens.borderSecondary}` }}>
      <div
        style={{
          display: table ? 'grid' : 'flex',
          gridTemplateColumns: table ? GRID : undefined,
          alignItems: 'center',
          gap: tokens.spaceMd,
          padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
        }}
      >
        <NameCell model={model} state={state} active={active} table={table} />
        <WiredCell ok={model.engine_ready} />
        <StateCell model={model} state={state} report={report} />
        <SizeCell model={model} />
        <RatingCell model={model} />
        <DescCell model={model} state={state} specs={specs} table={table} />
        <RowActions
          model={model}
          state={state}
          report={report}
          detail={detail}
          onToggleDetail={() => {
            setDetail(!detail);
            if (!detail) onVerify(model.model_id);
          }}
          onActivate={onActivate}
          onChanged={onChanged}
          onVerify={onVerify}
          preview={preview}
        />
      </div>
      {detail && <VerifyDetail report={report} modelId={model.model_id} onVerify={onVerify} />}
    </div>
  );
}

function NameCell({
  model,
  state,
  active,
  table,
}: {
  model: ModelInfo;
  state: AssetState;
  active: boolean;
  table: boolean;
}): ReactElement {
  const imported = model.imported;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd, minWidth: 0 }}>
      <StateDot state={state} />
      <div style={{ minWidth: 0 }}>
        <span style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, fontWeight: 600, color: tokens.textPrimary }}>{model.name}</span>
        {active && (
          <span style={{ marginLeft: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.colorPrimary }}>
            使用中
          </span>
        )}
        {imported !== undefined && imported !== null && (
          <span
            style={{ marginLeft: tokens.spaceSm, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.colorInfo }}
            title={`不是下载来的，是导入向导落位的：${imported.path}`}
          >
            本地导入
          </span>
        )}
        {!table && (
          <span style={{ marginLeft: tokens.spaceSm, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
            {model.desc ?? model.repo_id}
          </span>
        )}
      </div>
    </div>
  );
}

/** 未接入的资产不参与「生效」，所以这一列只是事实，不是邀请。 */
function WiredCell({ ok }: { ok: boolean }): ReactElement {
  return (
    <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: ok ? tokens.colorSuccess : tokens.textTertiary }}>
      {ok ? '已接入' : '未接入'}
    </span>
  );
}

function StateCell({
  model,
  state,
  report,
}: {
  model: ModelInfo;
  state: AssetState;
  report: VerifyReport | undefined;
}): ReactElement {
  const progress = useDownloadProgress(model);
  const note = failureNote(report);
  return (
    <span style={{ minWidth: 0 }}>
      <StateBadge state={state} progress={progress} />
      {note !== undefined && (
        <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.colorError }}>{note}</div>
      )}
    </span>
  );
}

function SizeCell({ model }: { model: ModelInfo }): ReactElement {
  return (
    <span style={mixins.chip()} title="实占为磁盘真实字节，未下载时显示标称体积">
      {model.status === 'installed' ? formatBytes(model.size_bytes ?? 0) : (model.size_label ?? '—')}
    </span>
  );
}

function RatingCell({ model }: { model: ModelInfo }): ReactElement {
  if ((model.speed ?? 0) === 0 && (model.quality ?? 0) === 0) {
    return <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>—</span>;
  }
  return (
    <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {(model.speed ?? 0) > 0 && <RatingDots label="速度" level={model.speed ?? 0} />}
      {(model.quality ?? 0) > 0 && <RatingDots label="精度" level={model.quality ?? 0} />}
    </span>
  );
}

/** 说明格：只在「还没装且本机装不下」时占用为警示，否则是登记的一句话描述。 */
function DescCell({
  model,
  state,
  specs,
  table,
}: {
  model: ModelInfo;
  state: AssetState;
  specs: MachineSpecs;
  table: boolean;
}): ReactElement {
  const fit = judgeModelFit(specs, parseSizeGb(model.size_label));
  const blocked = state === 'missing' && (fit.verdict === 'disk' || fit.verdict === 'ram');
  return (
    <span
      style={{
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        color: blocked ? FIT_VERDICT_COLOR[fit.verdict] : tokens.textTertiary,
        minWidth: 0,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {blocked ? `⚠ ${fit.reason}` : (table ? (model.desc ?? '') : '')}
    </span>
  );
}
