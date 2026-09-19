/**
 * 外部资产：登记本里认不出内置身份的那几条（model_id 为 null）。
 *
 * 这一组压根没有「选为生效」——不是没做，是引擎工厂里没有承接它的构造分支，
 * 这件事由后端的登记本说（model_id 为 null），前端一处都不猜。能给的只有撤销登记：
 * 文件从头到尾留在业主自己的盘上，「删除」那个词会撒谎。
 */
import type { ReactElement } from 'react';
import { Button, Popconfirm } from 'antd';
import type { ImportRecord } from '@dramaclip/protocol';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { GroupHead } from './AssetKit';
import { MODE_LABEL } from './importWizard';

export function ExternalAssets({
  items,
  onForget,
}: {
  items: readonly ImportRecord[];
  onForget: (path: string) => void;
}): ReactElement | null {
  if (items.length === 0) return null;
  return (
    <div>
      <GroupHead
        title="外部资产 · 引擎未接入"
        count={items.length}
        hint="登记在案的本地目录，工厂里还没有承接它的构造分支：看得到路径，不能选为生效"
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {items.map((record) => (
          <ExternalRow key={record.path} record={record} onForget={onForget} />
        ))}
      </div>
    </div>
  );
}

function ExternalRow({
  record,
  onForget,
}: {
  record: ImportRecord;
  onForget: (path: string) => void;
}): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        <span style={{ fontSize: tokens.fontBody, fontWeight: 600, color: tokens.textPrimary }}>
          {record.label ?? record.path}
        </span>
        {record.incomplete && (
          <span style={{ marginLeft: tokens.spaceSm, fontSize: tokens.fontMicro, color: tokens.colorError }}>
            按现状登记，当时体检未通过
          </span>
        )}
        <div
          style={{
            ...mixins.chip(),
            marginTop: tokens.spaceXs,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={record.path}
        >
          {record.path}
        </div>
      </div>
      <span style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary, flexShrink: 0 }}>
        {MODE_LABEL[record.mode]}
      </span>
      <Popconfirm
        title="撤销登记"
        description="只从登记本里划掉这一条：目录还在你自己的盘上，一个字节都没动过。"
        okText="确认撤销"
        cancelText="取消"
        onConfirm={() => {
          onForget(record.path);
        }}
      >
        <Button size="small">撤销登记</Button>
      </Popconfirm>
    </div>
  );
}
