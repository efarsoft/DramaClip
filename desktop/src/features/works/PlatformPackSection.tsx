/** 逐平台发布包：平台切换 → 标题适配/文案/话题/AI 声明指引 + 封面重裁 + 一键复制。
 *  规格与话题注入在服务端（publish_pack），本组件只渲染与搬运。 */
import { CopyOutlined, PictureOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Select } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import type { PlatformPack } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { exportApi, mediaUrl, titlesApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

const PLATFORMS = ['抖音', '视频号', '快手', '小红书', 'B站'];

export function PlatformPackSection({
  planId,
  exportId,
}: {
  planId: string;
  exportId: string;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [platform, setPlatform] = useState('抖音');
  const [pack, setPack] = useState<PlatformPack | null>(null);
  const [covers, setCovers] = useState<Record<string, string>>({});
  const [cropping, setCropping] = useState(false);
  useEffect(() => {
    if (planId === '') return;
    void titlesApi.publishPack(planId).then(setPack).catch(() => undefined);
  }, [planId]);
  const entry = pack?.platforms[platform];
  const copy = (): void => {
    if (entry === undefined) return;
    const text = [entry.title, entry.caption ?? '', entry.tags.map((t) => `#${t}`).join(' ')]
      .filter((part) => part !== '')
      .join('\n');
    void navigator.clipboard.writeText(text).then(() => message.success(`${platform}发布包已复制`));
  };
  const crop = (): void => {
    setCropping(true);
    void exportApi
      .platformCovers(exportId)
      .then((result) => {
        setCovers(result.covers);
        const skippedNames = Object.keys(result.skipped);
        if (skippedNames.length > 0) {
          message.warning(`部分平台封面未生成：${skippedNames.join('、')}`);
        } else {
          message.success('平台封面已生成');
        }
      })
      .catch((error: unknown) => message.error(errorText(error, '封面重裁失败')))
      .finally(() => { setCropping(false); });
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
      {entry === undefined ? (
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {planId === '' ? '方案已删除，发布包无从生成' : '发布包加载中…（先生成候选标题）'}
        </div>
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
              style={{ maxWidth: 240, borderRadius: 4, display: 'block' }}
            />
          )}
        </div>
      )}
    </PageSection>
  );
}
