/** 卡内无边框下拉：一个设置项对应一个下拉，即改即存（生效卡的参数就地改，P6）。 */
import { Select } from 'antd';
import type { DefaultOptionType } from 'antd/es/select';
import type { ReactElement } from 'react';

export function SettingSelect({
  value,
  options,
  onChange,
  placeholder,
  searchable = false,
  width = '100%',
  variant = 'borderless',
}: {
  value: string | undefined;
  options: readonly DefaultOptionType[];
  onChange: (value: string) => void;
  placeholder?: string;
  searchable?: boolean;
  width?: number | string;
  variant?: 'borderless' | 'outlined';
}): ReactElement {
  return (
    <Select
      size="small"
      variant={variant}
      style={{ width }}
      placeholder={placeholder}
      value={value}
      options={[...options]}
      showSearch={searchable ? { optionFilterProp: 'label' } : false}
      onChange={(next: string) => {
        onChange(next);
      }}
    />
  );
}
