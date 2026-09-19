/** 试听：合成一句固定短句并立刻播放——100 个音色不该靠名字猜（P8）。
 *
 *  出声的必须正是所选的那件引擎与音色，所以服务端拒绝时（未接入的引擎、会被静默
 *  换掉的音色、缺模型）把原因原样摆在按钮旁，不改口说「已播放」也不换个引擎再试。
 */
import { SoundOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { mediaUrl, ttsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

export function TtsPreviewButton({
  engine,
  voice,
  blocked,
}: {
  engine: string;
  voice: string;
  /** 现在还不能试听的原因（如模型未下载）：给出来就不必让人点了才知道。 */
  blocked?: string;
}): ReactElement {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | undefined>(undefined);
  const playing = useRef<HTMLAudioElement | null>(null);
  useEffect(() => {
    return () => {
      playing.current?.pause();
    };
  }, []);

  const start = (): void => {
    setBusy(true);
    setFailed(undefined);
    ttsApi.preview(engine, voice).then(
      (result) => {
        playing.current?.pause(); // 两次试听叠着放就成了杂音，听不出差别
        const element = new Audio(mediaUrl(result.path));
        playing.current = element;
        void Promise.resolve(element.play()).catch(() => undefined);
      },
      (error: unknown) => {
        setFailed(error instanceof Error ? error.message : '试听失败');
      },
    ).finally(() => {
      setBusy(false);
    });
  };

  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <Button
        size="small"
        icon={<SoundOutlined />}
        loading={busy}
        disabled={busy || blocked !== undefined}
        onClick={start}
      >
        {busy ? '合成中' : '试听'}
      </Button>
      {(blocked ?? failed) !== undefined && (
        <Notice text={blocked ?? failed ?? ''} failed={blocked === undefined} />
      )}
    </span>
  );
}

function Notice({ text, failed }: { text: string; failed: boolean }): ReactElement {
  return (
    <span
      style={{
        fontSize: tokens.fontMicro,
        lineHeight: '16px',
        color: failed ? tokens.colorError : tokens.textTertiary,
        maxWidth: 460,
      }}
    >
      {text}
    </span>
  );
}
