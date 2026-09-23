/** 阶段条 ?focus= 段内导航（卷三意见 06 第二刀）：滚到出片页对应卡片区。
 *
 * 只滚动、不改页内任何状态——域页的选中/表单/队列一概不碰（属主纪律的第二刀
 * 边界：壳负责带路，域内的事域自己管）。非法 focus 值沉默：认不出的值不滚。
 */
import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { useSearchParams } from 'react-router-dom';

export type FocusSection = 'planning' | 'export';

/** focus 参数 → 区段；认不出的值返回 null（缺席而非假动作）。 */
export function focusSectionId(focus: string | null): FocusSection | null {
  if (focus === 'planning' || focus === 'export') return focus;
  return null;
}

export function useFocusScroll(): {
  planningRef: RefObject<HTMLDivElement | null>;
  exportRef: RefObject<HTMLDivElement | null>;
} {
  const [searchParams] = useSearchParams();
  const planningRef = useRef<HTMLDivElement | null>(null);
  const exportRef = useRef<HTMLDivElement | null>(null);
  const focus = focusSectionId(searchParams.get('focus'));

  useEffect(() => {
    const target = focus === 'planning' ? planningRef.current : focus === 'export' ? exportRef.current : null;
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [focus]);

  return { planningRef, exportRef };
}
