/** 成片详情页：播放器 + 元数据 + 解说文案 + 候选标题（规格 §七 成片详情设计）。 */
import { FolderOpenOutlined, CopyOutlined, ReloadOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Empty } from 'antd';
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { useParams } from 'react-router-dom';
import type { ExportJob, TitleCandidate } from '@dramaclip/protocol';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { MODE_INFO } from '../../components/modeMeta';
import { exportApi, mediaUrl, projectApi, rpc, titlesApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

function modeLabel(mode: string | undefined): string {
  return MODE_INFO.find((item) => item.mode === mode)?.label ?? mode ?? '成片';
}

function formatDuration(s: number | undefined): string {
  if (s === undefined || s <= 0) return '—';
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`;
}

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || bytes <= 0) return '—';
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '—';
  const d = new Date(ms);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
}

export function WorksDetailPage(): ReactElement {
  const { exportId = '' } = useParams();
  const { message } = AntdApp.useApp();
  const [job, setJob] = useState<ExportJob | null>(null);
  const [failed, setFailed] = useState(false);
  const [projectName, setProjectName] = useState('…');
  const [cover, setCover] = useState<string | undefined>(undefined);
  const [titles, setTitles] = useState<TitleCandidate[]>([]);
  const [narrationTexts, setNarrationTexts] = useState<{ id: string; text: string }[]>([]);
  const [planId, setPlanId] = useState('');
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (exportId === '') return;
    void exportApi
      .get(exportId)
      .then((row) => {
        setJob(row);
        void projectApi
          .get(row.project_id)
          .then((detail) => {
            setProjectName(detail.project.name);
            setCover(detail.project.cover_path);
          })
          .catch(() => undefined);
        if (row.narration_plan_id) {
          setPlanId(row.narration_plan_id);
          void rpc<{ plan: { titles?: TitleCandidate[]; plan_data?: { narration_texts?: { id: string; text: string }[] } } }>(
            'narration.get_plan',
            { plan_id: row.narration_plan_id },
          )
            .then((detail) => {
              setTitles(detail.plan.titles ?? []);
              setNarrationTexts(detail.plan.plan_data?.narration_texts ?? []);
            })
            .catch(() => undefined);
        }
      })
      .catch(() => setFailed(true));
  }, [exportId]);

  const onGenerate = (): void => {
    setGenerating(true);
    void titlesApi
      .generate(planId)
      .then((r) => setTitles(r.titles))
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => setGenerating(false));
  };

  if (failed) {
    return (
      <PageShell>
        <Empty description="成片不存在或已被删除" style={{ paddingBlock: tokens.space3xl }} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={`${projectName} · ${job === null ? '…' : modeLabel(job.narration_mode)}`}
        desc="成片详情：预览、解说文案与候选标题"
        onBack={() => {
          window.history.back();
        }}
      />
      {job === null ? (
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
            <PageSection title="预览" dense>
              <video
                src={mediaUrl(job.output_path ?? '')}
                controls
                style={{ width: '100%', aspectRatio: '9 / 16', objectFit: 'contain', background: '#000', display: 'block' }}
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg, minWidth: 0 }}>
            <NarrationSection texts={narrationTexts} mode={job.narration_mode} />
            <TitlesSection
              titles={titles}
              generating={generating}
              hasPlan={planId !== ''}
              onGenerate={onGenerate}
              onChange={setTitles}
            />
          </div>
        </div>
      )}
    </PageShell>
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
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          {mode === 'raw_clip' || mode === 'subtitle_flow'
            ? '该模式无解说文案（纯原片/字幕流）'
            : '解说文案加载中或为空'}
        </div>
      ) : (
        texts.map((t) => (
          <div key={t.id} style={{ ...mixins.listRow(), alignItems: 'flex-start' }}>
            <span
              style={{
                fontSize: tokens.fontMicro,
                color: tokens.textTertiary,
                fontFamily: tokens.fontFamilyMono,
                flexShrink: 0,
                paddingTop: 2,
              }}
            >
              {t.id}
            </span>
            <span
              style={{
                fontSize: tokens.fontCaption,
                color: tokens.textSecondary,
                lineHeight: '19px',
                minWidth: 0,
                whiteSpace: 'pre-wrap',
              }}
            >
              {t.text}
            </span>
          </div>
        ))
      )}
    </PageSection>
  );
}

function TitlesSection({
  titles,
  generating,
  hasPlan,
  onGenerate,
  onChange,
}: {
  titles: TitleCandidate[];
  generating: boolean;
  hasPlan: boolean;
  onGenerate: () => void;
  onChange: (titles: TitleCandidate[]) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const copy = (text: string): void => {
    void navigator.clipboard.writeText(text).then(() => message.success('标题已复制'));
  };
  const toggle = (index: number): void => {
    onChange(titles.map((t, i) => ({ ...t, selected: i === index ? !t.selected : false })));
  };
  return (
    <PageSection
      title="候选标题"
      extra={
        hasPlan && (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={generating}
            onClick={onGenerate}
          >
            {titles.length === 0 ? '生成候选标题' : '重新生成'}
          </Button>
        )
      }
      dense
    >
      {titles.length === 0 ? (
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          {generating ? '生成中…' : '点击「生成候选标题」，LLM 将基于解说文案产出 8 条风格多样的标题'}
        </div>
      ) : (
        titles.map((t, index) => (
          <div key={`${String(index)}-${t.text.slice(0, 8)}`} style={{ ...mixins.listRow(), alignItems: 'center' }}>
            <span
              onClick={() => {
                toggle(index);
              }}
              style={{
                flex: 1, minWidth: 0, fontSize: tokens.fontCaption,
                color: t.selected ? tokens.colorPrimary : tokens.textSecondary,
                fontWeight: t.selected ? 600 : 400, cursor: 'pointer',
              }}
            >
              {t.selected ? '★ ' : ''}
              {t.text}
            </span>
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(t.text)} />
          </div>
        ))
      )}
    </PageSection>
  );
}

function MetaRow({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: `${tokens.spaceXs}px 0` }}>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>{label}</span>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary, fontFamily: tokens.fontFamilyMono }}>
        {value}
      </span>
    </div>
  );
}
