/** 逐平台发布包：平台切换 → 标题适配/文案/话题/AI 声明指引 + 封面重裁 + 一键复制。
 *  规格与话题注入在服务端（publish_pack），本组件只渲染与搬运。 */
import { CopyOutlined, PictureOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Select } from 'antd';
import type { MessageInstance } from 'antd/es/message/interface';
import { useEffect, useState, type ReactElement } from 'react';
import type { ChecklistItem, PlatformPack, TitleCandidate, PlatformPackEntry } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { exportApi, mediaUrl, titlesApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

const PLATFORMS = ['抖音', '视频号', '快手', '小红书', 'B站'];

/** 发布包文本组装（拆出组件为行帽留位）：标题+文案+话题三段拼切。 */
function buildPackText(entry: PlatformPackEntry): string {
  return [entry.title, entry.caption ?? '', entry.tags.map((t) => `#${t}`).join(' ')]
    .filter((part) => part !== '')
    .join('\n');
}

/** 封面重裁（拆出组件为行帽留位）：依赖注入（setState 回调与通知实例）保持纯调用。 */
async function recropCovers(
  exportId: string,
  ports: {
    setCovers: (covers: Record<string, string>) => void;
    setCropping: (cropping: boolean) => void;
    notify: MessageInstance;
  },
): Promise<void> {
  ports.setCropping(true);
  try {
    const result = await exportApi.platformCovers(exportId);
    ports.setCovers(result.covers);
    const skippedNames = Object.keys(result.skipped);
    if (skippedNames.length > 0) {
      ports.notify.warning(`部分平台封面未生成：${skippedNames.join('、')}`);
    } else {
      ports.notify.success('平台封面已生成');
    }
  } catch (error: unknown) {
    ports.notify.error(errorText(error, '封面重裁失败'));
  } finally {
    ports.setCropping(false);
  }
}

export function PlatformPackSection({
  planId,
  exportId,
  titles,
}: {
  planId: string;
  exportId: string;
  /** 详情页的候选标题：选用/重生成/重拉都会换数组身份 → 发布包随之重拉，不留旧标题。 */
  titles: TitleCandidate[];
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [platform, setPlatform] = useState('抖音');
  const [pack, setPack] = useState<PlatformPack | null>(null);
  const [covers, setCovers] = useState<Record<string, string>>({});
  const [cropping, setCropping] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadFailedReason, setLoadFailedReason] = useState('');
  const [retryTick, setRetryTick] = useState(0);
  useEffect(() => {
    if (planId === '') return;
    let active = true;
    setLoadFailed(false);
    void titlesApi.publishPack(planId)
      .then((result) => { if (active) setPack(result); })
      .catch((error: unknown) => {
        // 失败原文上屏（h3FailureCopyGate 同纪律）：「加载失败」不告诉用户该修什么
        if (active) {
          setLoadFailed(true);
          setLoadFailedReason(error instanceof Error && error.message !== '' ? error.message : String(error));
        }
      });
    return () => {
      active = false;
    };
  }, [planId, titles, retryTick]);
  const entry = pack?.platforms[platform];
  const copy = (): void => {
    if (entry === undefined) return;
    const text = buildPackText(entry);
    void navigator.clipboard
      .writeText(text)
      .then(() => message.success(`${platform}发布包已复制`))
      .catch(() => message.error('复制到剪贴板失败'));
  };
  const crop = (): void => {
    void recropCovers(exportId, { setCovers, setCropping, notify: message });
  };
  const coverPath = covers[platform];
  return (
    <PageSection
      title="逐平台发布包"
      extra={
        <span style={{ display: 'flex', gap: tokens.spaceSm }}>
          <Select
            size="small"
            value={platform}
            onChange={setPlatform}
            options={PLATFORMS.map((name) => ({ value: name, label: name }))}
            style={{ width: 96 }}
          />
          <Button size="small" icon={<CopyOutlined />} disabled={entry === undefined} onClick={copy}>
            复制
          </Button>
          <Button size="small" icon={<PictureOutlined />} loading={cropping} onClick={crop}>
            生成平台封面
          </Button>
        </span>
      }
      dense
    >
      {loadFailed || entry === undefined ? (
        <PackPlaceholder
          planId={planId}
          loadFailed={loadFailed}
          reason={loadFailedReason}
          onRetry={() => {
            setRetryTick((tick) => tick + 1);
          }}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
          <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>
            {entry.title === '' ? '（无标题）' : entry.title}
            {!entry.title_fits && (
              <span style={{ marginLeft: tokens.spaceXs, color: tokens.errorText }}>
                超出该平台标题字数上限
              </span>
            )}
          </div>
          {entry.caption !== null && entry.caption !== '' && (
            <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              {entry.caption}
            </div>
          )}
          <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
            {entry.tags.map((t) => `#${t}`).join(' ')}
          </div>
          <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
            AI 声明：{entry.ai_declaration}
          </div>
          {coverPath !== undefined && (
            <img
              src={mediaUrl(coverPath)}
              alt={`${platform}封面`}
              style={{ maxWidth: 240, borderRadius: tokens.radiusThumb, display: 'block' }}
            />
          )}
          <PublishChecklist items={pack?.checklist ?? []} />
        </div>
      )}
    </PageSection>
  );
}

/** 发布前自查清单：五动作项上屏 + 一键复制。满足项（☑）灰字，未满足项带补充说明；
 *  空清单时「复制清单」按钮禁用（如实不假绿）。 */
function PublishChecklist({ items }: { items: readonly ChecklistItem[] }): ReactElement {
  const { message } = AntdApp.useApp();
  const copy = (): void => {
    const text = items.map((item) =>
      item.satisfied ? item.label : `${item.label}（${item.note}）`,
    ).join('\n');
    void navigator.clipboard
      .writeText(text)
      .then(() => message.success('自查清单已复制'))
      .catch(() => message.error('复制清单失败'));
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: tokens.text.meta.size, color: tokens.textSecondary }}>发布前自查</span>
        <Button
          size="small"
          icon={<CopyOutlined />}
          disabled={items.length === 0}
          onClick={copy}
        >
          复制清单
        </Button>
      </div>
      {items.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
          {items.map((item, idx) => (
            <div key={idx} style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: item.satisfied ? tokens.textTertiary : tokens.textSecondary }}>
              {item.label}
              {!item.satisfied && item.note !== '' && (
                <span style={{ color: tokens.textTertiary }}>（{item.note}）</span>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** 无条目时的如实占位：方案已删 / 加载失败（可重试）/ 加载中——失败不伪装成永久加载中。 */
function PackPlaceholder({
  planId,
  loadFailed,
  reason,
  onRetry,
}: {
  planId: string;
  loadFailed: boolean;
  reason: string;
  onRetry: () => void;
}): ReactElement {
  return (
    <div style={{ padding: tokens.spaceMd, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: loadFailed ? tokens.errorText : tokens.textTertiary }}>
      {planId === '' ? (
        '方案已删除，发布包无从生成'
      ) : loadFailed ? (
        <>
          {`发布包加载失败${reason !== '' ? `：${reason}` : ''}`}
          <Button size="small" type="link" onClick={onRetry}>
            重试
          </Button>
        </>
      ) : (
        '发布包加载中…（先生成候选标题）'
      )}
    </div>
  );
}
