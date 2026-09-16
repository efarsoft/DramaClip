/** 继续上次：最近打开过的那部剧，一键回到它（规格 §4.1 主区第四块）。
 *
 * 没有记录时整块不渲染——一个写着"还没有最近项目"的卡片是噪音。
 * 路径经 routes.ts 的 dramaEntryPath 生成，P-3.2 合并剧空间时只改那一处；
 * 已存的旧路径届时由 §2.2 的一次性重定向接住（一跳）。
 *
 * 用 `<a href="#…">` 而不是 useNavigate：HashRouter 下 hash 链接天然可用，
 * 组件因此不需要 Router 上下文，也不必在测试里包 MemoryRouter。
 */
import { RightOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import type { Project } from '@dramaclip/protocol';
import { dramaEntryPath } from '../../app/routes';
import { mixins } from '../../styles/mixins';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';
import { whenLabel } from './relativeTime';
import { readLastDrama } from '../../stores/lastDrama';

export function ContinueCard({ projects, nowMs }: { projects: Project[]; nowMs: number }): ReactElement | null {
  const last = readLastDrama();
  if (last === null) return null;
  const cover = projects.find((project) => project.id === last.id)?.cover_path;
  return (
    <a
      href={`#${dramaEntryPath(last.id)}`}
      style={{
        ...mixins.listRow(),
        gap: tokens.spaceMd,
        borderRadius: tokens.radiusCard,
        border: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
        padding: `${String(tokens.spaceMd)} ${String(tokens.spaceLg)}`,
        textDecoration: 'none',
      }}
    >
      <span
        style={{
          width: 72, height: 44, borderRadius: tokens.radiusThumb, overflow: 'hidden',
          flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: tokens.accentSoft, color: tokens.colorPrimary,
        }}
      >
        {cover !== undefined ? (
          <img src={mediaUrl(cover)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
        ) : (
          <span style={{ fontSize: tokens.fontBody }}>▶</span>
        )}
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, gap: 2 }}>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>继续上次</span>
        <span
          style={{
            fontSize: tokens.fontBodyLg,
            fontWeight: 600,
            color: tokens.textPrimary,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {last.name}
        </span>
      </span>
      <span
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spaceSm,
          flexShrink: 0,
          fontSize: tokens.fontMicro,
          color: tokens.textTertiary,
        }}
      >
        {whenLabel(last.visitedAtMs, nowMs)}
        <RightOutlined style={{ fontSize: tokens.fontIcon }} />
      </span>
    </a>
  );
}
