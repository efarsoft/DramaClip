/** 成品库批量操作条（卷二 §4.5 批量三件 + §3.4 危险操作规矩）：
 * 吸底常驻，量化文案「已选 N 条 · 共 X GB」；删除是唯一的 danger，同屏无第二个 primary/danger。 */
import type { CSSProperties, ReactElement } from 'react';
import { Button } from 'antd';
import { CopyOutlined, DeleteOutlined, FolderOpenOutlined } from '@ant-design/icons';
import type { WorkItem } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { formatTotalGb, selectedBytes } from './worksView';

export interface BatchBarActions {
  readonly onOpenFolders: () => void;
  readonly onCopyTo: () => void;
  readonly onDelete: () => void;
  readonly onClear: () => void;
}

const monoSpan: CSSProperties = { fontFamily: tokens.fontFamilyMono };

/** 量化文案：中文与数字分 span（mono 栈无汉字字形，§1.3）。 */
function SelectionSummary({ count, totalGb }: { count: number; totalGb: string }): ReactElement {
  return (
    <span
      style={{
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
        color: tokens.textSecondary,
      }}
    >
      已选 <span style={monoSpan}>{String(count)}</span> 条 · 共 <span style={monoSpan}>{totalGb}</span>
    </span>
  );
}

export function BatchBar({
  selected,
  actions,
}: {
  selected: readonly WorkItem[];
  actions: BatchBarActions;
}): ReactElement | null {
  if (selected.length === 0) return null;
  return (
    <div
      style={{
        position: 'sticky',
        bottom: 0,
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: `${tokens.spaceSm} ${tokens.spaceLg}`,
        background: tokens.bgSidebar,
        borderTop: `1px solid ${tokens.borderSecondary}`,
        boxShadow: tokens.shadowSticky,
      }}
    >
      <SelectionSummary count={selected.length} totalGb={formatTotalGb(selectedBytes(selected))} />
      <Button size="small" onClick={actions.onClear} style={{ marginLeft: 'auto' }}>
        取消选择
      </Button>
      <Button size="small" icon={<FolderOpenOutlined />} onClick={actions.onOpenFolders}>
        打开所在文件夹
      </Button>
      <Button size="small" icon={<CopyOutlined />} onClick={actions.onCopyTo}>
        复制到…
      </Button>
      <Button size="small" danger icon={<DeleteOutlined />} onClick={actions.onDelete}>
        删除
      </Button>
    </div>
  );
}
