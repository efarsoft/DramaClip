/** 封面角位/行尾的「⋯」管理菜单触发钮：卡档与列表档同一颗钮。 */
import { Button } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';

export function MoreButton(props: React.ComponentProps<typeof Button>): ReactElement {
  return (
    <Button
      type="text"
      size="small"
      style={{ background: tokens.posterPlate, color: tokens.colorWhite }}
      {...props}
    >
      ⋯
    </Button>
  );
}
