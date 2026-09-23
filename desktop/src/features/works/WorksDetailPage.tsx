/** 成片详情页：预览 + 文件（完整路径）+ 追溯（角度·取材集·方案区）+ 自检四项 + 文案与标题。 */
import { CopyOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Empty, Tag } from 'antd';
import type { ReactElement } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { Episode, ExportJob } from '@dramaclip/protocol';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { modeLabel } from '../../components/modeMeta';
import { copyFiles, mediaUrl, pickFolder, revealInFolder } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';
import { SelfCheckSection } from './SelfCheckSection';
import { TitlesSection } from './TitlesSection';
import { useWorkDetail } from './useWorkDetail';
import { episodeLabel } from './worksView';

function formatDuration(s: number | undefined): string {
  if (s === undefined || s <= 0) return '—';
  const m = Math.floor(s / 60);
  return `${String(m)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
}

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '—';
  const d = new Date(ms);
  return `${String(d.getFullYear())}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
}

export function WorksDetailPage(): ReactElement {
  const { exportId = '' } = useParams();
  const detail = useWorkDetail(exportId);

  if (detail.failed) {
    return (
      <PageShell>
        <Empty description="成片不存在或已被删除" style={{ paddingBlock: tokens.space3xl }} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={`${detail.projectName} · ${detail.job === null ? '…' : modeLabel(detail.job.narration_mode)}`}
        desc="成片详情：预览、文件、追溯、自检与文案"
        onBack={() => {
          window.history.back();
        }}
      />
      {detail.job === null ? (
        <Empty description="加载中…" />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(300px, 420px) minmax(0, 1fr)',
            gap: tokens.spaceLg,
            alignItems: 'start',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
            <PreviewColumn job={detail.job} />
            <TraceSection
              projectId={detail.job.project_id}
              angle={detail.angle}
              episodeIds={detail.episodeIds}
              episodes={detail.episodes}
              hasPlan={detail.planId !== ''}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg, minWidth: 0 }}>
            <SelfCheckSection
              selfcheck={detail.job.selfcheck}
              onSelfcheck={detail.onSelfcheck}
              onReload={detail.reload}
            />
            <NarrationSection texts={detail.narrationTexts} mode={detail.job.narration_mode} />
            <TitlesSection
              titles={detail.titles}
              generating={detail.generating}
              hasPlan={detail.planId !== ''}
              onGenerate={detail.onGenerate}
              onChange={detail.setTitles}
            />
          </div>
        </div>
      )}
    </PageShell>
  );
}

function PreviewColumn({ job }: { job: ExportJob }): ReactElement {
  const { message } = AntdApp.useApp();
  const onReveal = (): void => {
    const path = job.output_path;
    if (path === undefined || path === '') return;
    void revealInFolder(path).then((result) => {
      if (!result.ok) message.error(result.reason ?? '打开文件夹失败');
    });
  };
  const onCopyTo = (): void => {
    const path = job.output_path;
    if (path === undefined || path === '') return;
    void pickFolder()
      .then((dest) => {
        if (dest === null || dest === '') return null;
        return copyFiles([path], dest).then((result) => {
          if (result.copied.length > 0) message.success(`已复制到 ${dest}`);
          for (const fail of result.failed) message.error(`复制失败：${fail.reason}`);
        });
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      });
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <PageSection title="预览" dense>
        <video
          src={mediaUrl(job.output_path ?? '')}
          controls
          style={{ width: '100%', aspectRatio: '9 / 16', objectFit: 'contain', background: tokens.posterBase, display: 'block' }}
        />
      </PageSection>
      <PageSection title="文件">
        <MetaRow label="模式" value={modeLabel(job.narration_mode)} />
        <MetaRow label="时长" value={formatDuration(job.duration_s)} />
        <MetaRow label="大小" value={formatSize(job.size_bytes)} />
        <MetaRow label="完成时间" value={formatDate(job.completed_at)} />
        <PathRow path={job.output_path ?? ''} />
        <div style={{ display: 'flex', gap: tokens.spaceSm, marginTop: tokens.spaceSm }}>
          <Button block icon={<FolderOpenOutlined />} onClick={onReveal}>
            打开文件夹
          </Button>
          <Button block icon={<CopyOutlined />} onClick={onCopyTo}>
            复制到…
          </Button>
        </div>
      </PageSection>
    </div>
  );
}

/** 追溯（09-10 §4.5）：角度名（金）+ 取材集区间 + 跳回出片中心方案区；方案已删如实说断链。 */
function TraceSection({
  projectId,
  angle,
  episodeIds,
  episodes,
  hasPlan,
}: {
  projectId: string;
  angle: string | null;
  episodeIds: string[] | null;
  episodes: Episode[];
  hasPlan: boolean;
}): ReactElement {
  const navigate = useNavigate();
  const trace = episodeLabel(episodeIds, episodes);
  return (
    <PageSection title="追溯">
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
          {angle !== null && angle !== '' ? (
            <Tag color="gold" style={{ marginRight: 0 }}>{angle}</Tag>
          ) : (
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
              {hasPlan ? '该方案无角度标签' : '方案已删除，追溯链断'}
            </span>
          )}
        </div>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
          {trace === '' ? (hasPlan ? '取材集未知' : '取材集随方案一并不可考') : trace}
        </span>
        <Button
          block
          disabled={!hasPlan}
          onClick={() => {
            void navigate(`/projects/${projectId}/produce?focus=planning`);
          }}
          style={{ marginTop: tokens.spaceXs }}
        >
          去方案区
        </Button>
      </div>
    </PageSection>
  );
}

function NarrationSection({ texts, mode }: { texts: { id: string; text: string }[]; mode: string | undefined }): ReactElement {
  const { message } = AntdApp.useApp();
  const all = texts.map((t) => t.text).join('\n\n');
  const noCopy = texts.length === 0;
  return (
    <PageSection
      title="解说文案"
      extra={
        !noCopy && (
          <Button
            size="small"
            icon={<CopyOutlined />}
            onClick={() => {
              void navigator.clipboard.writeText(all).then(() => message.success('解说文案已复制'));
            }}
          >
            复制全文
          </Button>
        )
      }
      dense
    >
      {noCopy ? (
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {mode === 'raw_clip' || mode === 'subtitle_flow'
            ? '该模式无解说文案（纯原片/字幕流）'
            : '解说文案加载中或为空'}
        </div>
      ) : (
        texts.map((t) => <NarrationRow key={t.id} id={t.id} text={t.text} />)
      )}
    </PageSection>
  );
}

function NarrationRow({ id, text }: { id: string; text: string }): ReactElement {
  return (
    <div style={{ ...mixins.listRow(), alignItems: 'flex-start' }}>
      <span
        style={{
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          color: tokens.textTertiary,
          fontFamily: tokens.fontFamilyMono,
          flexShrink: 0,
          paddingTop: layout.monoAlignTop,
        }}
      >
        {id}
      </span>
      <span
        style={{
          fontSize: tokens.text.body.size,
          color: tokens.textSecondary,
          lineHeight: tokens.text.body.leading,
          minWidth: 0,
          whiteSpace: 'pre-wrap',
        }}
      >
        {text}
      </span>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: `${tokens.spaceXs} 0` }}>
      <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>{label}</span>
      <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary, fontFamily: tokens.fontFamilyMono }}>
        {value}
      </span>
    </div>
  );
}

/** 完整路径（§4.5 单片动作「显示完整路径」）：mono 可换行，不截断不省略。 */
function PathRow({ path }: { path: string }): ReactElement {
  const { message } = AntdApp.useApp();
  if (path === '') {
    return <MetaRow label="路径" value="—" />;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, padding: `${tokens.spaceXs} 0` }}>
      <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>路径</span>
      <span
        onClick={() => {
          void navigator.clipboard.writeText(path).then(() => message.success('路径已复制'));
        }}
        title="点击复制完整路径"
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textSecondary,
          fontFamily: tokens.fontFamilyMono,
          wordBreak: 'break-all',
          cursor: 'pointer',
        }}
      >
        {path}
      </span>
    </div>
  );
}
