/** 发布数据回流（W8）：完播率是系统唯一的外部真相源——录一次十秒，攒的是自进化的原料。
 * 低摩擦口径：平台/播放量/完播率三项必填，点赞/分享/前3秒留存/作品ID/发布日期可选；平台记住上次选择。 */
import { Button, DatePicker, Input, InputNumber, Select } from 'antd';
import type { ReactElement } from 'react';
import type { ExportJob } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { PUBLISH_PLATFORMS, usePublishDataForm } from './usePublishDataForm';
import { formatDate } from './worksView';

export function PublishDataSection({ job, onReload }: { job: ExportJob; onReload: () => void }): ReactElement {
  const {
    existing, platform, setPlatform, plays, setPlays, retention, setRetention,
    likes, setLikes, shares, setShares, retention3s, setRetention3s,
    videoId, setVideoId, publishedAt, setPublishedAt, saving, save, clear,
  } = usePublishDataForm(job, onReload);

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