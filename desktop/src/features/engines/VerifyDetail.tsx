/** 体检详情：逐条列出后端判据（models.verify 的 checks），没跑过的先跑一次。 */
import { useEffect } from 'react';
import type { ReactElement } from 'react';
import type { VerifyCheck, VerifyReport } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';

const CHECK_COLOR: Record<VerifyCheck['status'], string> = {
  pass: tokens.colorSuccess,
  warn: tokens.colorWarning,
  fail: tokens.colorError,
  skip: tokens.textTertiary,
};

const CHECK_LABEL: Record<VerifyCheck['status'], string> = {
  pass: '通过',
  warn: '存疑',
  fail: '不通过',
  skip: '未执行',
};

export function VerifyDetail({
  report,
  modelId,
  onVerify,
}: {
  report: VerifyReport | undefined;
  modelId: string;
  onVerify: (modelId: string) => void;
}): ReactElement {
  useEffect(() => {
    if (report === undefined) onVerify(modelId);
  }, [report, modelId, onVerify]);
  if (report === undefined) {
    return (
      <div style={{ padding: `0 ${tokens.spaceMd} ${tokens.spaceMd}`, fontSize: tokens.fontMicro }}>
        <span style={{ color: tokens.textTertiary }}>体检中…</span>
      </div>
    );
  }
  return (
    <div
      style={{
        margin: `0 ${tokens.spaceMd} ${tokens.spaceMd}`,
        padding: tokens.spaceMd,
        borderRadius: tokens.radiusControl,
        background: tokens.bgElevated,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceXs,
      }}
    >
      {report.checks.map((check) => (
        <CheckRow key={check.name} check={check} />
      ))}
    </div>
  );
}

/** 一条判据：名字 + 结论 + 后端原话。导入向导第 ② 步共用同一份翻译。 */
export function CheckRow({ check }: { check: VerifyCheck }): ReactElement {
  return (
    <div style={{ display: 'flex', gap: tokens.spaceMd, fontSize: tokens.fontMicro }}>
      <span style={{ width: 96, flexShrink: 0, color: tokens.textTertiary }}>{check.name}</span>
      <span style={{ width: 40, flexShrink: 0, color: CHECK_COLOR[check.status] }}>
        {CHECK_LABEL[check.status]}
      </span>
      <span style={{ color: tokens.textSecondary }}>{check.detail ?? ''}</span>
    </div>
  );
}
