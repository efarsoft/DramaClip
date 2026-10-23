/** 工具箱页：Tabs 选项卡组织三个工具（视频文案提取/语音转文字/文字转语音）。
 * 视频文案提取是左播放器 + 右逐句文案的两栏核对屏；文案改写是提取/转写产出文案之后的加工步骤，
 * 改写稿可直接送配音，形成提取→改写→配音闭环。 */
import {
  AudioOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  PlaySquareOutlined,
  ProfileOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import { App as AntdApp, Button, Empty, Input, Spin, Tabs } from 'antd';
import type { ReactElement } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ToolsExtractPayload, ToolsGetResultResult } from '@dramaclip/protocol';
import {
  mediaUrl,
  pickAudioFile,
  pickVideoFile,
  revealInFolder,
  saveTextFile,
  toolsApi,
} from '../../services/client';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { CopyResultPanel } from './CopyResultPanel';

const PAGE_DESC = '不依赖项目流程的独立小工具：贴视频/音频出文案，一键改写，文字转语音。';

/** 作业轮询：每 2s 查一次直至终态；连续 3 次查询失败判为异常终止（组件卸载即停）。 */
function useJobPoll(): { start: (jobId: string, onDone: (detail: ToolsGetResultResult) => void) => void } {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const failures = useRef(0);
  const stop = useCallback((): void => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);
  useEffect(() => stop, [stop]);
  const start = useCallback(
    (jobId: string, onDone: (detail: ToolsGetResultResult) => void): void => {
      stop();
      failures.current = 0;
      timer.current = setInterval(() => {
        void toolsApi
          .getResult(jobId)
          .then((detail) => {
            if (detail.status === 'running' || detail.status === 'pending') return;
            stop();
            onDone(detail);
          })
          .catch(() => {
            failures.current += 1;
            if (failures.current >= 3) {
              stop();
              onDone({
                status: 'failed',
                error: '查询作业状态失败（服务无响应），请重试',
              });
            }
          });
      }, 2000);
    },
    [stop],
  );
  return { start };
}

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

/** 工具一：视频文案提取（ASR + 硬字幕 OCR 融合，短剧文案的金标准链路）。
 * 左栏选片与播放，右栏逐句核对——点右栏某句，播放器跳到该句起点。 */
function CopyExtractTool({ onSendToTts }: { onSendToTts: (text: string) => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const poll = useJobPoll();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [videoPath, setVideoPath] = useState('');
  const [status, setStatus] = useState<'idle' | 'queued' | 'running' | 'failed'>('idle');
  const [failReason, setFailReason] = useState('');
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
    setFailReason('');
    setStatus('queued');
    void toolsApi
      .extractStart(videoPath)
      .then((r) => {
        poll.start(r.job_id, (detail) => {
          if (detail.status === 'completed' && detail.result) {
            setStatus('idle');
            setResult(detail.result);
          } else {
            setStatus('failed');
            setFailReason(detail.error ?? '提取失败');
          }
        });
      })
      .catch((error: unknown) => {
        setStatus('idle');
        message.error(error instanceof Error ? error.message : String(error));
      });
  };

  const onSeek = (seconds: number): void => {
    const video = videoRef.current;
    if (video) video.currentTime = seconds;
  };

  const onDownloadSrt = (): void => {
    if (result === null) return;
    void fetch(mediaUrl(result.srt_path))
      .then((resp) => resp.text())
      .then((content) => {
        const base = videoPath.replaceAll('\\', '/').split('/').pop() ?? '文案';
        const dot = base.lastIndexOf('.');
        const stem = dot > 0 ? base.slice(0, dot) : base;
        return saveTextFile(`${stem}.srt`, content);
      })
      .then((saved) => {
        if (saved !== null) message.success('SRT 已保存');
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : 'SRT 保存失败');
      });
  };

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(300px, 420px) minmax(0, 1fr)',
        gap: tokens.spaceLg,
        alignItems: 'start',
      }}
    >
      <ExtractSourceCard
        videoPath={videoPath}
        busy={busy}
        failReason={failReason}
        videoSrc={result === null ? '' : mediaUrl(result.video_path)}
        videoRef={videoRef}
        onPick={onPick}
        onExtract={onExtract}
      />
      <PageSection title="提取文案" extra={<ProfileOutlined style={{ color: tokens.textTertiary }} />}>
        {result === null ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="提取完成后，逐句文案出现在这里"
            style={{ paddingBlock: tokens.spaceLg }}
          />
        ) : (
          <CopyResultPanel
            text={result.text}
            meta={`提取 ${String(result.chars)} 字 · ${String(result.lines)} 行 · 视频 ${String(result.duration_s)} 秒`}
            srtPath={result.srt_path}
            onSeek={onSeek}
            onSendToTts={onSendToTts}
            srtAction={
              <Button size="small" icon={<DownloadOutlined />} onClick={onDownloadSrt}>
                保存 SRT
              </Button>
            }
          />
        )}
      </PageSection>
    </div>
  );
}

/** 左栏：选片、发起提取、播放器（videoSrc 为空表示还没出结果，播放器不上屏）。 */
function ExtractSourceCard({
  videoPath,
  busy,
  failReason,
  videoSrc,
  videoRef,
  onPick,
  onExtract,
}: {
  videoPath: string;
  busy: boolean;
  failReason: string;
  videoSrc: string;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onPick: () => void;
  onExtract: () => void;
}): ReactElement {
  return (
    <PageSection title="视频文案提取" extra={<FileSearchOutlined style={{ color: tokens.textTertiary }} />}>
      <div style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
        <Input
          style={{ flex: 1 }}
          value={videoPath}
          placeholder="选择一个视频文件（自动识别语音与硬字幕，输出全文与 SRT）"
          readOnly
        />
        <Button onClick={onPick}>选择视频</Button>
      </div>
      <div style={{ marginTop: tokens.spaceSm }}>
        <Button type="primary" icon={<FileSearchOutlined />} loading={busy} onClick={onExtract} block>
          开始提取
        </Button>
      </div>
      <ExtractStatus
        busy={busy}
        failReason={failReason}
        runningHint="转写与硬字幕识别中，耗时与视频时长成正比；完成后文案出现在右侧"
      />
      {videoSrc !== '' && (
        <video
          ref={videoRef}
          src={videoSrc}
          controls
          style={{
            width: '100%',
            maxHeight: 380,
            marginTop: tokens.spaceMd,
            borderRadius: tokens.radiusControl,
            background: tokens.posterBase,
          }}
        />
      )}
    </PageSection>
  );
}

/** 运行中的进度占位与失败常驻提示（互斥状态，闲时都不渲染；失败原因常驻可读）。 */
function ExtractStatus({
  busy,
  failReason,
  runningHint,
}: {
  busy: boolean;
  failReason: string;
  runningHint: string;
}): ReactElement | null {
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
          {runningHint}
        </span>
      </div>
    );
  }
  if (failReason !== '') {
    return (
      <div style={{ marginTop: tokens.spaceMd, color: tokens.errorText }}>
        失败：{failReason}（请重试或更换文件）
      </div>
    );
  }
  return null;
}

/** 工具二：语音文件转文字（纯 ASR，无 OCR）。没有画面可播，逐句时间轴只读。 */
function AsrTool({ onSendToTts }: { onSendToTts: (text: string) => void }): ReactElement {
  const { message } = AntdApp.useApp();
  const poll = useJobPoll();
  const [audioPath, setAudioPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [failReason, setFailReason] = useState('');
  const [result, setResult] = useState<ToolsExtractPayload | null>(null);

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
    setResult(null);
    setFailReason('');
    void toolsApi
      .asrStart(audioPath)
      .then((r) => {
        poll.start(r.job_id, (detail) => {
          setBusy(false);
          if (detail.status === 'completed' && detail.result) {
            setResult(detail.result);
          } else {
            setFailReason(detail.error ?? '转写失败');
          }
        });
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
      <ExtractStatus busy={busy} failReason={failReason} runningHint="转写中，耗时与音频时长成正比" />
      {result !== null && (
        <CopyResultPanel
          text={result.text}
          meta={`转写 ${String(result.chars)} 字 · 音频 ${String(result.duration_s)} 秒`}
          srtPath={result.srt_path}
          onSendToTts={onSendToTts}
        />
      )}
    </PageSection>
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
      <div style={{ marginTop: tokens.spaceSm, display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
        <Button type="primary" icon={<AudioOutlined />} loading={synthesizing} onClick={onSynthesize}>
          合成语音
        </Button>
        {synthesizing && (
          <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
            合成中，长文自动分块逐段合成
          </span>
        )}
        {audioPath !== '' && !synthesizing && (
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
