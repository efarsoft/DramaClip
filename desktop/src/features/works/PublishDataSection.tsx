/** 发布数据回流（W8）：完播率是系统唯一的外部真相源——录一次十秒，攒的是自进化的原料。
 * 低摩擦口径：平台/播放量/完播率三项必填，点赞/分享/前3秒留存/作品ID/发布日期可选；平台记住上次选择。 */
import { App as AntdApp, Button, DatePicker, Input, InputNumber, Select } from 'antd';
import { useState, type ReactElement } from 'react';
import dayjs from 'dayjs';
import type { ExportJob } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { exportApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

/** 发布平台枚举：与服务端 _PUBLISH_PLATFORMS 同表（白名单在服务端，这里只是选项列表）。 */
const PUBLISH_PLATFORMS = ['抖音', '快手', '视频号', '小红书', 'B站', '其他'];
const PLATFORM_MEMORY_KEY = 'dramaclip.publish-platform';

function formatDate(ms: number | undefined): string {
  if (ms === undefined) return '—';
  const d = new Date(ms);
  return `${String(d.getFullYear())}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
}

// 平铺录入表单整体自包含（147 行）：本波行为保持只搬家，拆子组件需钻十几个 props 反增间接层。
// 函数上限门禁点名豁免留档，待后续表单抽象波统一分解。
// eslint-disable-next-line max-lines-per-function
export function PublishDataSection({ job, onReload }: { job: ExportJob; onReload: () => void }): ReactElement {
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

  return (
    <PageSection
      title="发布数据"
      extra={
        existing !== null && (
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
            录于 {formatDate(existing.recorded_at)}
          </span>
        )
      }
      dense
    >
      <div style={{ display: 'flex', gap: tokens.spaceSm, flexWrap: 'wrap', alignItems: 'center' }}>
        <Select
          size="small"
          value={platform}
          onChange={setPlatform}
          options={PUBLISH_PLATFORMS.map((name) => ({ value: name, label: name }))}
          style={{ width: 104 }}
        />
        <InputNumber
          size="small"
          min={0}
          step={100}
          precision={0}
          placeholder="播放量*"
          value={plays}
          onChange={(value) => { setPlays(typeof value === 'number' ? value : null); }}
          style={{ width: 128 }}
        />
        <InputNumber
          size="small"
          min={0}
          max={100}
          placeholder="完播率*"
          value={retention}
          onChange={(value) => { setRetention(typeof value === 'number' ? value : null); }}
          suffix="%"
          style={{ width: 112 }}
        />
        <InputNumber
          size="small"
          min={0}
          placeholder="赞(选填)"
          value={likes}
          onChange={(value) => { setLikes(typeof value === 'number' ? value : null); }}
          style={{ width: 112 }}
        />
        <InputNumber
          size="small"
          min={0}
          placeholder="分享(选填)"
          value={shares}
          onChange={(value) => { setShares(typeof value === 'number' ? value : null); }}
          style={{ width: 112 }}
        />
        <InputNumber
          size="small"
          min={0}
          max={100}
          placeholder="前3秒留存(选填)"
          value={retention3s}
          onChange={(value) => { setRetention3s(typeof value === 'number' ? value : null); }}
          suffix="%"
          style={{ width: 160 }}
        />
        <Input
          size="small"
          placeholder="作品ID/链接(选填)"
          value={videoId}
          onChange={(event) => { setVideoId(event.target.value); }}
          style={{ width: 180 }}
        />
        <DatePicker
          size="small"
          placeholder="发布日期(选填)"
          value={publishedAt}
          onChange={(value) => { setPublishedAt(value); }}
          style={{ width: 150 }}
        />
        <Button type="primary" size="small" loading={saving} onClick={save}>
          保存
        </Button>
        {existing !== null && (
          <Button size="small" type="text" danger loading={saving} onClick={clear}>
            清除
          </Button>
        )}
      </div>
      <div style={{ marginTop: tokens.spaceXs, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
        完播率是观众的真实投票，也是成片质量唯一的外部判据——按方案回溯后用于选题与评分的反馈
      </div>
    </PageSection>
  );
}