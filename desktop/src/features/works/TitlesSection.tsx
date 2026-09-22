/** 候选标题区：LLM 生成/再生成 + 单条选用（星标互斥）+ 复制。 */
import { CopyOutlined, ReloadOutlined, StarFilled } from '@ant-design/icons';
import { App as AntdApp, Button } from 'antd';
import type { ReactElement } from 'react';
import type { TitleCandidate } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

export function TitlesSection({
  titles,
  generating,
  hasPlan,
  onGenerate,
  onChange,
}: {
  titles: TitleCandidate[];
  generating: boolean;
  hasPlan: boolean;
  onGenerate: () => void;
  onChange: (titles: TitleCandidate[]) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const copy = (text: string): void => {
    void navigator.clipboard.writeText(text).then(() => message.success('标题已复制'));
  };
  const toggle = (index: number): void => {
    onChange(titles.map((t, i) => ({ ...t, selected: i === index ? !t.selected : false })));
  };
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
          {generating ? '生成中…' : '点击「生成候选标题」，LLM 将基于解说文案产出 8 条风格多样的标题'}
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
              copy(t.text);
            }}
          />
        ))
      )}
    </PageSection>
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
