/** 参考音频清洗（彻底档=MDX-Net 人声分离）：剥掉 BGM/音效只留干声。
 *
 *  产物自动接替为当前参考——清洗的意义就是让下一次克隆用干净的那份，把产物
 *  路径留在通知里等人手动换等于白洗。失败原文上屏不换档重试：分离要装运行
 *  环境、首次要下模型，这些前提坏了就该说破，而不是悄悄退回 ffmpeg 快速档
 *  让人以为洗过了。
 */
import { ClearOutlined } from '@ant-design/icons';
import { App, Button } from 'antd';
import { useState, type ReactElement } from 'react';
import { ttsApi } from '../../services/client';
import { tokens } from '../../styles/theme';

const GRADE_LABEL: Record<string, string> = { good: '优', fair: '中', poor: '差' };

export function RefCleanButton({
  path,
  onCleaned,
}: {
  path: string;
  onCleaned: (path: string) => void;
}): ReactElement {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="small"
      icon={<ClearOutlined />}
      loading={busy}
      onClick={() => {
        setBusy(true);
        ttsApi
          .cleanReference(path, 'separate')
          .then((result) => {
            const snr = result.quality.metrics.snr_db;
            message.success(
              `清洗完成（${GRADE_LABEL[result.quality.grade] ?? result.quality.grade}）` +
                (snr === undefined ? '' : ` · 信噪比 ${String(snr)}dB`) +
                '，已换用清洗后的参考',
            );
            onCleaned(result.path);
          })
          .catch((error: unknown) => {
            message.error(error instanceof Error ? error.message : '清洗失败');
          })
          .finally(() => {
            setBusy(false);
          });
      }}
      style={{ color: tokens.textSecondary }}
    >
      人声分离
    </Button>
  );
}
