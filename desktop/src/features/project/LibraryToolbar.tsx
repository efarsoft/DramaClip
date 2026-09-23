/** 剧库工具条：聚合芯片即筛选器（意见 05 同款）+ 搜剧名 + 排序。 */
import { SearchOutlined } from '@ant-design/icons';
import { Input, Segmented } from 'antd';
import type { ReactElement } from 'react';
import { tokens } from '../../styles/theme';
import { FILTERS, type MatrixFilter } from '../home/matrixRows';
import { FilterChip } from '../home/DramaMatrix';
import type { LibraryQuery, SortKey } from './libraryRows';

// Segmented 要可变数组（SegmentedOptions 不吃 readonly），这里不冻
const SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: '最近动静', value: 'activity' },
  { label: '最近创建', value: 'created' },
  { label: '名称', value: 'name' },
];

export function LibraryToolbar({
  query,
  counts,
  onChange,
}: {
  query: LibraryQuery;
  counts: Readonly<Record<MatrixFilter, number>>;
  onChange: (next: LibraryQuery) => void;
}): ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd, flexWrap: 'wrap' }}>
      {FILTERS.map((spec) => (
        <FilterChip
          key={spec.key}
          label={spec.label}
          count={counts[spec.key]}
          active={query.filter === spec.key}
          title=""
          onClick={() => {
            onChange({ ...query, filter: spec.key });
          }}
        />
      ))}
      <Input
        placeholder="搜剧名"
        allowClear
        prefix={<SearchOutlined />}
        value={query.search}
        onChange={(event) => {
          onChange({ ...query, search: event.target.value });
        }}
        style={{ width: 200, marginLeft: 'auto' }}
      />
      <Segmented
        value={query.sort}
        options={SORT_OPTIONS}
        onChange={(value) => {
          onChange({ ...query, sort: value });
        }}
      />
    </div>
  );
}
