/** 无剧时的主区引导（规格 §4.1 空态：「无剧时主区整块替换为「新增项目」引导」）。
 *
 * 两处刻意的取舍：
 * 1. 带完成度的首启三步（装 ASR 模型 / 配 LLM / 新增项目）是 §4.2 **剧库页**的空态，
 *    依赖 project.list 的阶段聚合，归 P-3.2。本组件只做 §4.1 要求的那一件事。
 *    首启信息没有丢：新装机同时缺模型与凭据时，**今日待办**恰恰就是首启引导
 *    （缺模型→去下载、未配编剧模型→去配置），所以 HomePage 在空态下保留待办。
 * 2. 本页唯一的 primary 在这里，不在 PageHeader 上——两处都放会违反 DSS §3.1
 *    「每屏 primary 至多 1 个」。HomePage 据此在有剧/无剧之间切换 primary 的落点。
 *
 * 文案纪律：不承诺拖放（全库无 dataTransfer）、不承诺下载与网盘（规格 §1 产品边界：
 * 软件从素材已在本地开始）、不承诺授权留痕（§7 已整体移除）。
 */
import { FolderAddOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

export function EmptyWorkbench({
  creating,
  onCreate,
}: {
  creating: boolean;
  onCreate: () => void;
}): ReactElement {
  return (
    <section
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceLg,
        padding: `${String(tokens.space3xl * 2)} ${String(tokens.space2xl)}`,
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        textAlign: 'center',
      }}
    >
      <FolderAddOutlined style={{ fontSize: tokens.fontEmptyIcon, color: tokens.textTertiary, opacity: 0.4 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <div style={{ fontSize: tokens.fontTitle, fontWeight: 600, color: tokens.textPrimary }}>还没有剧</div>
        <div
          style={{
            fontSize: tokens.fontCaption,
            lineHeight: '20px',
            color: tokens.textTertiary,
            maxWidth: 420,
          }}
        >
          选择素材所在文件夹即可开始——一部剧对应一个文件夹，文件夹名就是剧名。
          素材已在本地，无需任何额外录入。
        </div>
      </div>
      <Button type="primary" icon={<FolderAddOutlined />} loading={creating} disabled={creating} onClick={onCreate}>
        新增项目
      </Button>
    </section>
  );
}
