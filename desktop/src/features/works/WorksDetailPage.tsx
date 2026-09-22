/** 成片详情页：播放器 + 元数据 + 解说文案 + 候选标题（规格 §七 成片详情设计）。 */
import { FolderOpenOutlined, CopyOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Empty } from 'antd';
import type { ReactElement } from 'react';
import { useParams } from 'react-router-dom';
import type { ExportJob } from '@dramaclip/protocol';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { modeLabel } from '../../components/modeMeta';
import { mediaUrl } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { TitlesSection } from './TitlesSection';
import { useWorkDetail } from './useWorkDetail';

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
        desc="成片详情：预览、解说文案与候选标题"
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
          <PreviewColumn job={detail.job} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg, minWidth: 0 }}>
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
        <Button
          block
          icon={<FolderOpenOutlined />}
          onClick={() => {
            if (job.output_path) {
              void import('../../services/client').then(({ revealInFolder }) =>
                revealInFolder(job.output_path ?? ''),
              );
            }
          }}
          style={{ marginTop: tokens.spaceSm }}
        >
          打开文件夹
        </Button>
      </PageSection>
    </div>
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
          paddingTop: 2,
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
