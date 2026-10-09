/** LLM 往返留痕查看器：清单（新→旧）→ 点开看 system/user/attempts 原文。
 *  留痕是服务端尽力而为写的文件——清单拉不到就诚实说空，不造数据。 */
import { Button, Modal, Spin } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import { narrationApi } from '../../services/client';
import { tokens } from '../../styles/theme';

interface TraceEntry {
  name: string;
  size: number;
  mtime: number;
}

export function LlmTraceModal({ open, onClose }: { open: boolean; onClose: () => void }): ReactElement {
  const [traces, setTraces] = useState<TraceEntry[] | null>(null);
  const [reading, setReading] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setTraces(null);
    setError('');
    narrationApi
      .llmTraces()
      .then((result) => {
        setTraces([...result.traces]);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [open]);

  const read = (name: string): void => {
    setReading(name);
    setError('');
    narrationApi
      .planTrace(name)
      .then((result) => {
        setContent(result.content);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  };

  return (
    <Modal
      title="LLM 往返记录"
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      styles={{ body: { maxHeight: '70vh', overflow: 'auto' } }}
    >
      <TraceBody
        traces={traces}
        content={content}
        error={error}
        reading={reading}
        onRead={(name) => {
          read(name);
        }}
        onBack={() => {
          setContent('');
        }}
      />
    </Modal>
  );
}

/** 弹窗正文：原文视图 > 加载中 > 空态 > 清单，四态互斥按序判。 */
function TraceBody({
  traces,
  content,
  error,
  reading,
  onRead,
  onBack,
}: {
  traces: TraceEntry[] | null;
  content: string;
  error: string;
  reading: string | null;
  onRead: (name: string) => void;
  onBack: () => void;
}): ReactElement {
  return (
    <>
      {error !== '' && (
        <div style={{ color: tokens.colorError, fontSize: tokens.text.meta.size, marginBottom: tokens.spaceSm }}>
          {error}
        </div>
      )}
      {content !== '' ? (
        <TraceContent content={content} onBack={onBack} />
      ) : traces === null ? (
        <div style={{ textAlign: 'center', padding: tokens.spaceXl }}>
          <Spin />
        </div>
      ) : traces.length === 0 ? (
        <div style={{ color: tokens.textTertiary, textAlign: 'center', padding: tokens.spaceXl }}>
          还没有留痕——LLM 往返发生时才会写文件
        </div>
      ) : (
        traces.map((trace) => (
          <TraceRow
            key={trace.name}
            trace={trace}
            onRead={() => {
              onRead(trace.name);
            }}
          />
        ))
      )}
      {reading !== null && content === '' && error === '' && (
        <div style={{ textAlign: 'center', padding: tokens.spaceSm }}>
          <Spin size="small" />
        </div>
      )}
    </>
  );
}

/** 原文视图：返回清单 + 等宽 pre 全文。 */
function TraceContent({ content, onBack }: { content: string; onBack: () => void }): ReactElement {
  return (
    <>
      <Button
        size="small"
        style={{ marginBottom: tokens.spaceSm }}
        onClick={() => {
          onBack();
        }}
      >
        ← 返回清单
      </Button>
      <pre
        style={{
          margin: 0,
          padding: tokens.spaceSm,
          background: tokens.bgContainer,
          border: `1px solid ${tokens.borderSecondary}`,
          borderRadius: tokens.radiusControl,
          fontSize: tokens.text.badge.size,
          lineHeight: tokens.text.badge.leading,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          maxHeight: '56vh',
          overflow: 'auto',
        }}
      >
        {content}
      </pre>
    </>
  );
}

/** 清单行：点文件名读原文，右侧时间与体积。 */
function TraceRow({ trace, onRead }: { trace: TraceEntry; onRead: () => void }): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceSm,
        padding: `${tokens.spaceXs} 0`,
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <button
        type="button"
        onClick={() => {
          onRead();
        }}
        style={{
          background: 'none',
          border: 'none',
          color: tokens.colorPrimary,
          cursor: 'pointer',
          padding: 0,
          fontSize: tokens.text.meta.size,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          textAlign: 'left',
          flex: 1,
        }}
        title={trace.name}
      >
        {trace.name}
      </button>
      <span style={{ fontSize: tokens.text.badge.size, color: tokens.textTertiary, flexShrink: 0 }}>
        {new Date(trace.mtime).toLocaleString()} · {(trace.size / 1024).toFixed(0)}KB
      </span>
    </div>
  );
}
