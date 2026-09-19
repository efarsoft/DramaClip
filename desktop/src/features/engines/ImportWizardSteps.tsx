/**
 * 第 ①② 步：选来源、把只读体检的结果摆给业主看。
 *
 * 第 ② 步说的是后端已经说过的事：识别依据、体检逐项判据、库里冲突的那一份长什么样。
 * 三种异常态（体检不通过 / 库里撞车 / 认不出身份）各自还缺哪个选择，由闸门话术点出来。
 */
import type { ReactElement } from 'react';
import { Button, Checkbox, Input, Radio } from 'antd';
import type { ImportInspection } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { formatBytes } from './assetState';
import {
  type ConflictVerdict,
  type ExternalKind,
  type ImportDraft,
  EXTERNAL_KIND_LABEL,
  VERDICT_HINT,
  VERDICT_LABEL,
  failedCheckNames,
} from './importWizard';
import { Chip, ChoiceRow, Field, Hint } from './ImportBits';
import { CheckRow } from './VerifyDetail';

export function SourceStep({ scanning, onPick }: { scanning: boolean; onPick: () => void }): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <Hint>
        选一个业主自己放的模型目录。第 ② 步只读地认它、体检它，一个字节都不动；体检通过（或你显式同意按现状导入）才谈落位。
      </Hint>
      <div>
        <Button type="primary" loading={scanning} onClick={onPick}>
          选择目录
        </Button>
      </div>
    </div>
  );
}

export function IdentifyStep({
  report,
  draft,
  onChange,
}: {
  report: ImportInspection;
  draft: ImportDraft;
  onChange: (draft: ImportDraft) => void;
}): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <Field label="源目录">
        <Chip style={{ wordBreak: 'break-all' }}>{report.source_path}</Chip>
        <Chip>{`${String(report.file_count)} 个文件 · ${formatBytes(report.total_bytes)}`}</Chip>
      </Field>
      <Field label="识别结果">
        <span style={{ fontWeight: 600 }}>{report.name ?? '未识别出内置模型'}</span>
        <Chip>{report.engine_ready ? '引擎已接入' : '引擎未接入'}</Chip>
        <Hint>依据：{report.basis}</Hint>
      </Field>
      <Field label="资产体检">
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
          {report.checks.map((check) => (
            <CheckRow key={check.name} check={check} />
          ))}
        </div>
      </Field>
      {report.conflict != null && <ConflictRow clash={report.conflict} draft={draft} onChange={onChange} />}
      {!report.recognized && <ExternalRow draft={draft} onChange={onChange} />}
      {!report.ok && <IncompleteRow report={report} draft={draft} onChange={onChange} />}
    </div>
  );
}

/** 库里已有同一件资产：把那一份的实测状况摆出来，裁决才有依据。 */
function ConflictRow({
  clash,
  draft,
  onChange,
}: {
  clash: NonNullable<ImportInspection['conflict']>;
  draft: ImportDraft;
  onChange: (draft: ImportDraft) => void;
}): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <Hint>
        {`库里已有 ${clash.model_id}（${clash.path} · ${formatBytes(clash.size_bytes)}${
          clash.ok ? '' : ` · 体检不通过：${(clash.failed_checks ?? []).join(' · ')}`
        }）`}
      </Hint>
      <ChoiceRow
        value={draft.onConflict || undefined}
        labels={VERDICT_LABEL}
        hints={VERDICT_HINT}
        onPick={(verdict: ConflictVerdict) => {
          onChange({ ...draft, onConflict: verdict });
        }}
      />
    </div>
  );
}

/** 认不出身份的目录：只让业主声明它属于哪类能力、叫什么，落哪儿由后端按能力给。 */
function ExternalRow({
  draft,
  onChange,
}: {
  draft: ImportDraft;
  onChange: (draft: ImportDraft) => void;
}): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <Hint>这个目录不在内置清单里：先声明它属于哪一类能力，不认身份就不猜它该放哪。</Hint>
      <Radio.Group
        value={draft.externalKind || undefined}
        onChange={(event) => {
          onChange({ ...draft, externalKind: event.target.value as ExternalKind });
        }}
      >
        <Radio value="asr">{EXTERNAL_KIND_LABEL.asr}</Radio>
        <Radio value="tts">{EXTERNAL_KIND_LABEL.tts}</Radio>
      </Radio.Group>
      <Input
        size="small"
        placeholder="名称（留空用目录名）"
        value={draft.label}
        style={{ maxWidth: 260 }}
        onChange={(event) => {
          onChange({ ...draft, label: event.target.value });
        }}
      />
    </div>
  );
}

/** 体检不通过的出口只有一个：业主显式同意「按现状导入」，缺项一路带着走。 */
function IncompleteRow({
  report,
  draft,
  onChange,
}: {
  report: ImportInspection;
  draft: ImportDraft;
  onChange: (draft: ImportDraft) => void;
}): ReactElement {
  return (
    <Checkbox
      checked={draft.allowIncomplete}
      onChange={(event) => {
        onChange({ ...draft, allowIncomplete: event.target.checked });
      }}
    >
      {`按现状导入，并标记为不完整（缺：${failedCheckNames(report).join(' · ')}；补齐前不能生效）`}
    </Checkbox>
  );
}
