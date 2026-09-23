/** 成品预览弹层：剧院黑（posterBase）+ 原生 controls。结案规格见 DSS §4「播放弹层」（09-10 §8⑦）：
 * 逐帧/倍速由 Chromium 原生控件提供，不自造播放控件；解码失败换诚实文案，不留黑盒。 */
import { useState, type ReactElement } from 'react';
import { Modal } from 'antd';
import type { WorkItem } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

const MODAL_WIDTH = 960;

export function PreviewModal({
  work,
  onClose,
}: {
  work: WorkItem | null;
  onClose: () => void;
}): ReactElement {
  const title =
    work === null
      ? ''
      : work.angle !== null && work.angle !== undefined && work.angle !== ''
        ? work.angle
        : modeLabel(work.narration_mode);
  return (
    <Modal
      open={work !== null}
      title={title}
      footer={null}
      width={MODAL_WIDTH}
      onCancel={onClose}
      destroyOnHidden
      styles={{
        root: { background: tokens.posterBase, padding: 0, overflow: 'hidden', maxWidth: '92vw' },
        body: { padding: 0 },
      }}
    >
      {work !== null && <VideoStage path={work.output_path} />}
    </Modal>
  );
}

/** 播放面：成功 = 原生控件；失败 = 现象 + 路径原文 + 两种可能——取不到 ≠ 不存在，两种都列。 */
function VideoStage({ path }: { path: string }): ReactElement {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div
        style={{
          padding: tokens.spaceXl,
          display: 'flex',
          flexDirection: 'column',
          gap: tokens.spaceSm,
        }}
      >
        <span style={{ color: tokens.colorError }}>播放失败：内置播放器解不出这个文件</span>
        <span style={{ fontFamily: tokens.fontFamilyMono, wordBreak: 'break-all', color: tokens.textSecondary }}>
          {path}
        </span>
        <span
          style={{
            fontSize: tokens.text.meta.size,
            lineHeight: tokens.text.meta.leading,
            color: tokens.textTertiary,
          }}
        >
          两种可能：文件已被移动或删除；或编码格式超出内置播放器能力。列表与账目不受影响，
          回成品库用「打开文件夹」核对文件是否还在盘上最快。
        </span>
      </div>
    );
  }
  return (
    <video
      src={mediaUrl(path)}
      controls
      autoPlay
      onError={() => {
        setFailed(true);
      }}
      style={{ width: '100%', display: 'block', background: tokens.posterBase }}
    />
  );
}
