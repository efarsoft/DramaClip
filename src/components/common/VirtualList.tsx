/**
 * 虚拟列表组件（轻量级原生实现）
 * 用于兼容无额外第三方库（如 react-window）的纯净环境，提供平滑且类型安全的滚动容器
 */

import React from 'react';

export interface VirtualListProps {
  items: any[];
  height: number;
  itemHeight?: number; // 兼容旧接口，此处保留
  renderItem: (item: any, index: number) => React.ReactNode;
  overscanCount?: number; // 兼容旧接口，此处保留
}

export const VirtualList: React.FC<VirtualListProps> = ({
  items,
  height,
  renderItem,
}) => {
  return (
    <div className="virtual-list-container" style={{ height, overflowY: 'auto' }}>
      {items.map((item, index) => (
        <div key={index} className="virtual-list-item">
          {renderItem(item, index)}
        </div>
      ))}
    </div>
  );
};

export default VirtualList;
