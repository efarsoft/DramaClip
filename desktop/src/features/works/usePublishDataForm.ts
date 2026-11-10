/** 发布数据回流（W8）录入表单逻辑：状态/保存/清除独立成 hook（页面组件保持函数行数纪律）。
 * 低摩擦口径：平台/播放量/完播率三项必填，点赞/分享/前3秒留存/作品ID/发布日期可选；平台记住上次选择。 */
import { useState } from 'react';
import { App as AntdApp } from 'antd';
import dayjs from 'dayjs';
import type { ExportJob } from '@dramaclip/protocol';
import { exportApi } from '../../services/client';
import { errorText } from '../engines/errorText';

/** 发布平台枚举：与服务端 _PUBLISH_PLATFORMS 同表（白名单在服务端，这里只是选项列表）。 */
export const PUBLISH_PLATFORMS = ['抖音', '快手', '视频号', '小红书', 'B站', '其他'];
const PLATFORM_MEMORY_KEY = 'dramaclip.publish-platform';

/** 表单状态 + 录入/清除动作：载荷、平台记忆与提示文案的唯一出处，渲染层只消费返回值。 */
export function usePublishDataForm(job: ExportJob, onReload: () => void) {
  const { message } = AntdApp.useApp();
  const existing = job.publish_data ?? null;
  const [platform, setPlatform] = useState(
    existing?.platform ?? localStorage.getItem(PLATFORM_MEMORY_KEY) ?? '抖音',
  );
  const [plays, setPlays] = useState<number | null>(existing?.plays ?? null);
  const [retention, setRetention] = useState<number | null>(existing?.retention_pct ?? null);
  const [likes, setLikes] = useState<number | null>(existing?.likes ?? null);
  const [shares, setShares] = useState<number | null>(existing?.shares ?? null);
  const [retention3s, setRetention3s] = useState<number | null>(existing?.retention_3s ?? null);
  const [videoId, setVideoId] = useState(existing?.video_id ?? '');
  const [publishedAt, setPublishedAt] = useState<dayjs.Dayjs | null>(
    existing?.published_at ? dayjs(existing.published_at) : null,
  );
  const [saving, setSaving] = useState(false);

  const save = (): void => {
    if (plays === null || retention === null) {
      message.warning('播放量与完播率为必填');
      return;
    }
    setSaving(true);
    exportApi
      .setPublishData(job.id, {
        platform,
        plays,
        retention_pct: retention,
        likes,
        shares,
        retention_3s: retention3s,
        video_id: videoId.trim() === '' ? null : videoId.trim(),
        published_at: publishedAt !== null ? publishedAt.format('YYYY-MM-DD') : null,
      })
      .then(() => {
        localStorage.setItem(PLATFORM_MEMORY_KEY, platform);
        message.success('发布数据已记录');
        onReload();
      })
      .catch((error: unknown) => message.error(errorText(error, '录入失败')))
      .finally(() => { setSaving(false); });
  };

  const clear = (): void => {
    setSaving(true);
    exportApi
      .setPublishData(job.id, null)
      .then(() => {
        message.success('已清除录入');
        onReload();
      })
      .catch((error: unknown) => message.error(errorText(error, '清除失败')))
      .finally(() => { setSaving(false); });
  };

  return {
    existing, platform, setPlatform, plays, setPlays, retention, setRetention,
    likes, setLikes, shares, setShares, retention3s, setRetention3s,
    videoId, setVideoId, publishedAt, setPublishedAt, saving, save, clear,
  };
}
