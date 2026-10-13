/** 工具箱页：Tabs 选项卡组织三个工具（视频文案提取/语音转文字/文字转语音）。
 * 文案改写是提取/转写产出文案之后的加工步骤：结果区内置「选风格 → 改写 → 审查标注」，
 * 改写稿可直接送配音，形成提取→改写→配音闭环。 */
import {
  AudioOutlined,
  CopyOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  PlaySquareOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import { App as AntdApp, Button, Input, Select, Spin, Tabs } from 'antd';
import type { ReactElement } from 'react';
import { useCallback, useState } from 'react';
import type { ToolsExtractPayload } from '@dramaclip/protocol';
import {
  mediaUrl,
  pickAudioFile,
  pickVideoFile,
  revealInFolder,
  toolsApi,
} from '../../services/client';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';

const PAGE_DESC = '不依赖项目流程的独立小工具：贴视频/音频出文案，一键改写，文字转语音。';

/** 工具箱页。 */
export function ToolsPage(): ReactElement {
  const [activeTab, setActiveTab] = useState('extract');
  const [ttsDraft, setTtsDraft] = useState('');
  const sendToTts = (text: string): void => {
    setTtsDraft(text);
    setActiveTab('tts');
  };
  return (
    <PageShell>
      <PageHeader title="工具箱" desc={PAGE_DESC} />
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'extract',
            label: '视频文案提取',
            children: <CopyExtractTool onSendToTts={sendToTts} />,
          },
          {
            key: 'asr',
            label: '语音转文字',
            children: <AsrTool onSendToTts={sendToTts} />,
          },
          {
            key: 'tts',
            label: '文字转语音',
            children: <TextToSpeechTool draft={ttsDraft} onDraft={setTtsDraft} />,
          },
        ]}
      />
    </PageShell>
  );
}

/** 工具一：视频文案提取（ASR + 硬字幕 OCR 融合，短剧文案的金标准链路）。 */
function CopyExtractTool({ onSendToTts }: { onSendToTts: (text: string) => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const [videoPath, setVideoPath] = useState('');
  const [status, setStatus] = useState<'idle' | 'queued' | 'running' | 'failed'>('idle');
  const [result, setResult] = useState<ToolsExtractPayload | null>(null);

  const busy = status === 'queued' || status === 'running';

  const onPick = (): void => {
    void pickVideoFile().then((picked) => {
      if (picked) setVideoPath(picked);
    });
  };

  const onExtract = (): void => {
    if (videoPath === '') {
      message.warning('先选择视频文件');
      return;
    }
    setResult(null);
    setStatus('queued');
    void toolsApi
      .extractStart(videoPath)
      .then((r) => {
        const poll = setInterval(() => {
          void toolsApi
            .getResult(r.job_id)
            .then((detail) => {
              if (detail.status === 'running' || detail.status === 'pending') {
                setStatus('running');
                return;
              }
              clearInterval(poll);
              if (detail.status === 'completed' && detail.result) {
                setStatus('idle');
                setResult(detail.result);
              } else {
                setStatus('failed');
                message.error(detail.error ?? '提取失败');
              }
            })
            .catch(() => undefined);
        }, 2000);
      })
      .catch((error: unknown) => {
        setStatus('idle');
        message.error(error instanceof Error ? error.message : String(error));
      });
  };

  const onDownloadSrt = (): void => {
    if (result === null) return;
    void fetch(mediaUrl(result.srt_path))
      .then((resp) => resp.text())
      .then((content) => navigator.clipboard.writeText(content))
      .then(() => message.success('SRT 内容已复制（可直接存为 .srt 文件）'))
      .catch(() => {
        void navigator.clipboard
          .writeText(result.srt_path)
          .then(() => message.success('SRT 文件路径已复制'));
      });
  };

  return (
    <PageSection
      title="视频文案提取"
      extra={<FileSearchOutlined style={{ color: tokens.textTertiary }} />}
    >
      <div style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
        <Input
          style={{ flex: 1 }}
          value={videoPath}
          placeholder="选择一个视频文件（自动识别语音与硬字幕，输出全文与 SRT）"
          readOnly
        />
        <Button onClick={onPick}>选择视频</Button>
        <Button
          type="primary"
          icon={<FileSearchOutlined />}
          loading={busy}
          onClick={onExtract}
        >
          开始提取
        </Button>
      </div>
      <ExtractStatus busy={busy} failed={status === 'failed'} />
      {result !== null && (
        <CopyResultPanel
          text={result.text}
          meta={`提取 ${String(result.chars)} 字 · ${String(result.lines)} 行 · 视频 ${String(result.duration_s)} 秒`}
          onSendToTts={onSendToTts}
          srtAction={
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={onDownloadSrt}
            >
              复制 SRT
            </Button>
          }
        />
      )}
    </PageSection>
  );
}

/** 提取中的进度占位与失败提示（两个互斥状态，闲时都不渲染）。 */
function ExtractStatus({ busy, failed }: { busy: boolean; failed: boolean }): ReactElement | null {
  if (busy) {
    return (
      <div
        style={{
          marginTop: tokens.spaceMd,
          display: 'flex',
          gap: tokens.spaceSm,
          alignItems: 'center',
        }}
      >
        <Spin size="small" />
        <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
          转写与硬字幕识别中，耗时与视频时长成正比；完成后结果出现在下方
        </span>
      </div>
    );
  }
  if (failed) {
    return (
      <div style={{ marginTop: tokens.spaceMd, color: tokens.errorText }}>
        提取失败，请重试或更换文件
      </div>
    );
  }
  return null;
}

/** 工具二：语音文件转文字（纯 ASR，无 OCR）。 */
function AsrTool({ onSendToTts }: { onSendToTts: (text: string) => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const [audioPath, setAudioPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState('');
  const [meta, setMeta] = useState('');

  const onPick = (): void => {
    void pickAudioFile().then((picked) => {
      if (picked) setAudioPath(picked);
    });
  };

  const onStart = (): void => {
    if (audioPath === '') {
      message.warning('先选择音频文件');
      return;
    }
    setBusy(true);
    setText('');
    void toolsApi
      .asrStart(audioPath)
      .then((r) => {
        const poll = setInterval(() => {
          void toolsApi
            .getResult(r.job_id)
            .then((detail) => {
              if (detail.status === 'running' || detail.status === 'pending') return;
              clearInterval(poll);
              setBusy(false);
              if (detail.status === 'completed' && detail.result) {
                setText(detail.result.text);
                setMeta(
                  `转写 ${String(detail.result.chars)} 字 · 音频 ${String(detail.result.duration_s)} 秒`,
                );
              } else {
                message.error(detail.error ?? '转写失败');
              }
            })
            .catch(() => undefined);
        }, 2000);
      })
      .catch((error: unknown) => {
        setBusy(false);
        message.error(error instanceof Error ? error.message : String(error));
      });
  };

  return (
    <PageSection title="语音转文字" extra={<SoundOutlined style={{ color: tokens.textTertiary }} />}>
      <div style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
        <Input
          style={{ flex: 1 }}
          value={audioPath}
          placeholder="选择一个音频文件（mp3/wav/m4a 等，纯语音转写）"
          readOnly
        />
        <Button onClick={onPick}>选择音频</Button>
        <Button type="primary" icon={<SoundOutlined />} loading={busy} onClick={onStart}>
          开始转写
        </Button>
      </div>
      {busy && (
        <div style={{ marginTop: tokens.spaceMd, display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
          <Spin size="small" />
          <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
            转写中，耗时与音频时长成正比
          </span>
        </div>
      )}
      {text !== '' && (
        <CopyResultPanel text={text} meta={meta} onSendToTts={onSendToTts} />
      )}
    </PageSection>
  );
}

type RewriteStyle = 'paraphrase' | 'card';

/** 产出文案结果区的改写子面板：选风格→改写→审查标注→改写稿动作（自含触发）。 */
function RewritePanel({ sourceText, onSendToTts }: { sourceText: string; onSendToTts: (text: string) => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const [rewriteStyle, setRewriteStyle] = useState<RewriteStyle>('paraphrase');
  const [rewritten, setRewritten] = useState('');
  const [notes, setNotes] = useState<readonly string[]>([]);
  const [rewriting, setRewriting] = useState(false);

  const onRewrite = (): void => {
    setRewriting(true);
    void toolsApi
      .rewrite(sourceText, rewriteStyle)
      .then((r) => {
        setRewritten(r.text);
        setNotes(r.notes);
        if (r.notes.length > 0) {
          message.warning(`改写完成，但有 ${String(r.notes.length)} 条审查标注`);
        } else {
          message.success('改写完成');
        }
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setRewriting(false);
      });
  };

  return (
    <div style={{ marginTop: tokens.spaceSm }}>
      <div style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
        <Select<RewriteStyle>
          size="small"
          style={{ width: 190 }}
          value={rewriteStyle}
          options={[
            { label: '原文复述（换说法不换事实）', value: 'paraphrase' },
            { label: '按文风卡重写（对齐解说文风）', value: 'card' },
          ]}
          onChange={setRewriteStyle}
        />
        <Button size="small" loading={rewriting} onClick={onRewrite}>
          改写
        </Button>
      </div>
      {rewritten !== '' && (
        <div style={{ marginTop: tokens.spaceSm }}>
          <Input.TextArea rows={6} value={rewritten} readOnly />
          {notes.length > 0 && (
            <ul
              style={{
                margin: `${tokens.spaceSm} 0 0`,
                paddingLeft: tokens.spaceLg,
                fontSize: tokens.text.meta.size,
                color: tokens.textTertiary,
              }}
            >
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          <div style={{ marginTop: tokens.spaceSm, display: 'flex', gap: tokens.spaceSm }}>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => {
                void navigator.clipboard.writeText(rewritten).then(() => message.success('改写稿已复制'));
              }}
            >
              复制改写稿
            </Button>
            <Button
              size="small"
              type="primary"
              ghost
              onClick={() => {
                onSendToTts(rewritten);
              }}
            >
              送改写稿配音
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 产出文案结果区：原文全文 + 元信息动作行 + 改写子面板。
 * 提取与语音转文字两个工具共用；改写是文案的加工步骤，不是独立工具。 */
function CopyResultPanel(props: {
  text: string;
  meta: string;
  srtAction?: ReactElement;
  onSendToTts: (text: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();

  const copy = useCallback((content: string, tip: string): void => {
    void navigator.clipboard.writeText(content).then(() => message.success(tip));
  }, []);

  return (
    <div style={{ marginTop: tokens.spaceMd }}>
      <Input.TextArea rows={8} value={props.text} readOnly />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spaceSm,
          marginTop: tokens.spaceSm,
        }}
      >
        <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>{props.meta}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
          {props.srtAction}
          <Button
            size="small"
            icon={<CopyOutlined />}
            onClick={() => {
              copy(props.text, '全文已复制');
            }}
          >
            复制全文
          </Button>
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => {
              props.onSendToTts(props.text);
            }}
          >
            送文字转语音
          </Button>
        </span>
      </div>
      <RewritePanel sourceText={props.text} onSendToTts={props.onSendToTts} />
    </div>
  );
}

/** 工具三：文字转语音（当前引擎 + 默认音色，长文由引擎内部分块）。 */
function TextToSpeechTool({
  draft,
  onDraft,
}: {
  draft: string;
  onDraft: (text: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [audioPath, setAudioPath] = useState('');
  const [synthesizing, setSynthesizing] = useState(false);

  const onSynthesize = (): void => {
    if (draft.trim() === '') {
      message.warning('先粘贴文案');
      return;
    }
    setSynthesizing(true);
    void toolsApi
      .tts(draft)
      .then((r) => {
        setAudioPath(r.path);
        message.success(`合成完成（${String(r.chars)} 字，引擎 ${r.engine}）`);
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        setSynthesizing(false);
      });
  };

  return (
    <PageSection title="文字转语音" extra={<AudioOutlined style={{ color: tokens.textTertiary }} />}>
      <Input.TextArea
        rows={6}
        value={draft}
        placeholder="粘贴文案全文，用当前配音引擎和音色合成语音（长文自动分块）"
        onChange={(event) => {
          onDraft(event.target.value);
        }}
      />
      <div style={{ marginTop: tokens.spaceSm, display: 'flex', gap: tokens.spaceSm }}>
        <Button type="primary" icon={<AudioOutlined />} loading={synthesizing} onClick={onSynthesize}>
          合成语音
        </Button>
        {audioPath !== '' && (
          <>
            <Button
              icon={<PlaySquareOutlined />}
              onClick={() => {
                new Audio(mediaUrl(audioPath)).play().catch(() => message.warning('播放失败'));
              }}
            >
              播放
            </Button>
            <Button
              icon={<FolderOpenOutlined />}
              onClick={() => {
                void revealInFolder(audioPath).then((r) => {
                  if (!r.ok) message.warning(r.reason);
                });
              }}
            >
              打开所在位置
            </Button>
          </>
        )}
      </div>
    </PageSection>
  );
}
