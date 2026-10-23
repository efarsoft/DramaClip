/** 工具箱产出文案的结果区：默认逐句时间轴（点击行定位播放进度），可切全文；下接改写加工面板。
 * 时间戳来自后端已产出的 copy.srt，不新增协议字段；SRT 读不到就常驻说明原因，不静默退回。 */
import { CopyOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Input, Segmented, Select } from 'antd';
import type { ReactElement } from 'react';
import { useCallback, useState } from 'react';
import { CueList } from '../cues/CueList';
import { useSrtCues } from '../cues/useSrtCues';
import { toolsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

type CueView = 'cues' | 'full';

/** 产出文案结果区。 */
export function CopyResultPanel(props: {
  text: string;
  meta: string;
  srtPath: string;
  srtAction?: ReactElement;
  /** 传了才允许点击定位：音频工具没有画面，时间戳只读。 */
  onSeek?: (seconds: number) => void;
  onSendToTts: (text: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const { cues, error } = useSrtCues(props.srtPath);
  const [view, setView] = useState<CueView>('cues');
  const showCues = cues !== null && view === 'cues';

  const copy = useCallback(
    (content: string, tip: string): void => {
      void navigator.clipboard.writeText(content).then(() => message.success(tip));
    },
    [message],
  );

  return (
    <div>
      {cues !== null && (
        <Segmented<CueView>
          size="small"
          value={view}
          options={[
            { label: '逐句时间轴', value: 'cues' },
            { label: '全文', value: 'full' },
          ]}
          onChange={setView}
        />
      )}
      {showCues ? <CueList cues={cues} onSeek={props.onSeek} /> : <Input.TextArea rows={8} value={props.text} readOnly />}
      {error !== '' && (
        <div style={{ marginTop: tokens.spaceSm, color: tokens.errorText }}>{error}</div>
      )}
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

type RewriteStyle = 'paraphrase' | 'card';

/** 结果区的改写子面板：选风格→改写→审查标注→改写稿动作（自含触发）。 */
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
