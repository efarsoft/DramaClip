/** 无剧时的主区引导（规格 §4.1 空态 + §4.2 首启三步）。
 *
 * 带完成度的首启三步（装 ASR 模型 / 配 LLM / 新增项目）在 OnboardingSteps，
 * 就绪判定与右栏「环境就绪度」同源（models.list + llmBaseUrl）。
 *
 * 本页唯一的 primary 在这里，不在 PageHeader 上——两处都放会违反 DSS §3.1
 * 「每屏 primary 至多 1 个」。HomePage 据此在有剧/无剧之间切换 primary 的落点。
 *
 * 文案纪律：不承诺拖放（全库无 dataTransfer）、不承诺下载与网盘（规格 §1 产品边界：
 * 软件从素材已在本地开始）、不承诺授权留痕（§7 已整体移除）。
 */
import { FolderAddOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { OnboardingSteps } from './OnboardingSteps';

export function EmptyWorkbench({
  creating,
  onCreate,
  models,
  llmBaseUrl,
}: {
  creating: boolean;
  onCreate: () => void;
  models: ModelInfo[] | null;
  llmBaseUrl: string;
}): ReactElement {
  return (
    <section
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spaceLg,
        padding: `${tokens.space4xl} ${tokens.space2xl}`,
        background: tokens.bgContainer,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusCard,
        textAlign: 'center',
      }}
    >
      <FolderAddOutlined style={{ fontSize: tokens.glyph.empty, color: tokens.textTertiary, opacity: 0.4 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <div style={{ fontSize: tokens.text.cardTitle.size, lineHeight: tokens.text.cardTitle.leading, fontWeight: 600, color: tokens.textPrimary }}>还没有剧</div>
        <div
          style={{
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: tokens.textTertiary,
            maxWidth: 420,
          }}
        >
          三步开始：装一个识别模型、配文案引擎、选素材文件夹建剧。
        </div>
      </div>
      <OnboardingSteps models={models} llmBaseUrl={llmBaseUrl} />
      <Button type="primary" icon={<FolderAddOutlined />} loading={creating} disabled={creating} onClick={onCreate}>
        新增项目
      </Button>
    </section>
  );
}
