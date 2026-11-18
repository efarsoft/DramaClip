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
    taskRef, setTaskRef, dramaName, setDramaName, packVersion, setPackVersion,
    publishAccount, setPublishAccount, settlementAmount, setSettlementAmount,
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
        {/* 五个对账维度（W14·条件③）：片→任务→号→结算的锚，只记录不做对账逻辑。 */}
        <SettlementInputs
          taskRef={taskRef} onTaskRef={setTaskRef}
          dramaName={dramaName} onDramaName={setDramaName}
          packVersion={packVersion} onPackVersion={setPackVersion}
          publishAccount={publishAccount} onPublishAccount={setPublishAccount}
          settlementAmount={settlementAmount} onSettlementAmount={setSettlementAmount}
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

/** 对账维度输入组（W14·条件③）：拆出主函数为行帽留位，五个输入一行排布。 */
function SettlementInputs({
  taskRef, onTaskRef, dramaName, onDramaName, packVersion, onPackVersion,
  publishAccount, onPublishAccount, settlementAmount, onSettlementAmount,
}: {
  taskRef: string; onTaskRef: (v: string) => void;
  dramaName: string; onDramaName: (v: string) => void;
  packVersion: string; onPackVersion: (v: string) => void;
  publishAccount: string; onPublishAccount: (v: string) => void;
  settlementAmount: number | null; onSettlementAmount: (v: number | null) => void;
}): ReactElement {
  return (
    <>
      <Input size="small" placeholder="任务编号" value={taskRef} onChange={(e) => { onTaskRef(e.target.value); }} style={{ width: 140 }} />
      <Input size="small" placeholder="剧目" value={dramaName} onChange={(e) => { onDramaName(e.target.value); }} style={{ width: 120 }} />
      <Input size="small" placeholder="素材包版本" value={packVersion} onChange={(e) => { onPackVersion(e.target.value); }} style={{ width: 130 }} />
      <Input size="small" placeholder="发布账号" value={publishAccount} onChange={(e) => { onPublishAccount(e.target.value); }} style={{ width: 120 }} />
      <InputNumber size="small" min={0} precision={2} placeholder="结算(选填)" value={settlementAmount} onChange={(v) => { onSettlementAmount(typeof v === 'number' ? v : null); }} style={{ width: 112 }} />
    </>
  );
}

