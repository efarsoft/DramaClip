/** 候选标题区：LLM 生成/再生成 + 单条选用（星标互斥，落库 `narration.update_titles`）+ 复制；
 *  下方发布文案/话题标签随生成一并产出。坏消息（生成失败、选用没存上）常驻本区。 */
import { CopyOutlined, ReloadOutlined, StarFilled } from '@ant-design/icons';
import { App as AntdApp, Button } from 'antd';
import type { ReactElement } from 'react';
import type { PublishMeta, TitleCandidate } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

export function TitlesSection({
  titles,
  publish,
  generating,
  saving,
  hasPlan,
  problem,
  onGenerate,
  onSelect,
}: {
  titles: TitleCandidate[];
  publish?: PublishMeta | null;
  generating: boolean;
  saving: boolean;
  hasPlan: boolean;
  /** 本区常驻的坏消息原文；空串＝没有。 */
  problem: string;
  onGenerate: () => void;
  onSelect: (titles: TitleCandidate[]) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const copy = (text: string, tip: string): void => {
    void navigator.clipboard.writeText(text).then(() => message.success(tip));
  };
  const toggle = (index: number): void => {
    onSelect(titles.map((t, i) => ({ ...t, selected: i === index ? !t.selected : false })));
  };
  const caption = publish?.caption ?? '';
  const tagLine = publish?.tags.length ? publish.tags.map((t) => `#${t}`).join(' ') : '';
  return (
    <PageSection
      title="候选标题"
      extra={
        hasPlan && (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={generating}
            onClick={onGenerate}
          >
            {titles.length === 0 ? '生成候选标题' : '重新生成'}
          </Button>
        )
      }
      dense
    >
      {titles.length === 0 ? (
        <div style={{ padding: tokens.spaceMd, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {!hasPlan
            ? '方案已删除，候选标题与发布文案无从生成'
            : generating
              ? '生成中…'
              : '点击「生成候选标题」，LLM 将一并产出 8 条标题、发布文案与话题标签'}
        </div>
      ) : (
        titles.map((t, index) => (
          <TitleRow
            key={`${String(index)}-${t.text.slice(0, 8)}`}
            title={t}
            onToggle={() => {
              toggle(index);
            }}
            onCopy={() => {
              copy(t.text, '标题已复制');
            }}
          />
        ))
      )}
      {saving && (
        <div style={{ marginTop: tokens.spaceXs, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
          选用保存中…
        </div>
      )}
      {problem !== '' && (
        <div style={{ marginTop: tokens.spaceXs, fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.errorText }}>
          {problem}
        </div>
      )}
      {(caption !== '' || tagLine !== '') && (
        <div style={{ marginTop: tokens.spaceSm, borderTop: `1px solid ${tokens.border}`, paddingTop: tokens.spaceSm }}>
          {caption !== '' && (
            <PublishRow
              label="发布文案"
              text={caption}
              onCopy={() => {
                copy(caption, '发布文案已复制');
              }}
            />
          )}
          {tagLine !== '' && (
            <PublishRow
              label="话题标签"
              text={tagLine}
              onCopy={() => {
                copy(tagLine, '话题标签已复制');
              }}
            />
          )}
        </div>
      )}
    </PageSection>
  );
}

function PublishRow({ label, text, onCopy }: { label: string; text: string; onCopy: () => void }): ReactElement {
  return (
    <div style={{ ...mixins.listRow(), alignItems: 'center' }}>
      <span style={{ flexShrink: 0, width: 64, fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>{label}</span>
      <span style={{ flex: 1, minWidth: 0, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textSecondary }}>
        {text}
      </span>
      <Button size="small" type="text" icon={<CopyOutlined />} onClick={onCopy} />
    </div>
  );
}

function TitleRow({
  title,
  onToggle,
  onCopy,
}: {
  title: TitleCandidate;
  onToggle: () => void;
  onCopy: () => void;
}): ReactElement {
  return (
    <div style={{ ...mixins.listRow(), alignItems: 'center' }}>
      <span
        onClick={onToggle}
        style={{
          flex: 1, minWidth: 0, fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading,
          color: title.selected ? tokens.colorPrimary : tokens.textSecondary,
          fontWeight: title.selected ? tokens.text.body.weightActive : tokens.text.body.weight, cursor: 'pointer',
        }}
      >
        {title.selected && <StarFilled style={{ marginRight: tokens.spaceXs }} />}
        {title.text}
      </span>
      <Button size="small" type="text" icon={<CopyOutlined />} onClick={onCopy} />
    </div>
  );
}
