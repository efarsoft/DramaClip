/** 成品预览弹层：剧院黑（posterBase）+ 原生 controls。规格上属 P-E「剧院黑预览」的第一期形态，
 * 这里先把「点开就能看片」做真；密度档/快捷键等打磨不在本批。 */
import type { ReactElement } from 'react';
import { Modal } from 'antd';
import type { WorkItem } from '@dramaclip/protocol';
import { modeLabel } from '../../components/modeMeta';
import { mediaUrl } from '../../services/client';
import { tokens } from '../../styles/theme';

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
      width={480}
      onCancel={onClose}
      destroyOnHidden
      styles={{ root: { background: tokens.posterBase, padding: 0, overflow: 'hidden' }, body: { padding: 0 } }}
    >
      {work !== null && (
        <video
          src={mediaUrl(work.output_path)}
          controls
          autoPlay
          style={{ width: '100%', display: 'block', background: tokens.posterBase }}
        />
      )}
    </Modal>
  );
}
