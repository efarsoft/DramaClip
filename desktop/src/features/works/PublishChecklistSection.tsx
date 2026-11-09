/** 发布前自查清单（报告项⑤）：动作清单 + 发布包一键复制；勾选态仅本次访问有效。 */
import { CopyOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Checkbox } from 'antd';
import { useState, type ReactElement } from 'react';
import type { PublishMeta, TitleCandidate } from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { buildPublishCopy, CHECKLIST_ITEMS } from './publishCopy';

export function PublishChecklistSection({
  titles,
  publish,
}: {
  titles: TitleCandidate[];
  publish: PublishMeta | null;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [checked, setChecked] = useState<boolean[]>(CHECKLIST_ITEMS.map(() => false));
  const copy = (): void => {
    void navigator.clipboard.writeText(buildPublishCopy(titles, publish)).then(() => {
      message.success('发布包与自查清单已复制');
    });
  };
  return (
    <PageSection
      title="发布前自查"
      extra={
        <Button size="small" icon={<CopyOutlined />} onClick={copy}>
          一键复制发布包
        </Button>
      }
      dense
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        {CHECKLIST_ITEMS.map((item, index) => (
          <Checkbox
            key={item}
            checked={checked[index]}
            onChange={(event) => {
              setChecked(checked.map((value, i) => (i === index ? event.target.checked : value)));
            }}
          >
            <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
              {item}
            </span>
          </Checkbox>
        ))}
      </div>
      <div style={{ marginTop: tokens.spaceXs, fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
        勾选态仅本次访问有效；清单是动作提醒，不是授权存证
      </div>
    </PageSection>
  );
}
