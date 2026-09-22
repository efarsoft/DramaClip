/** 分栏拖拽 hook：返回 [宽度百分比, 拖拽把手事件]。默认值与带宽同读 layout.split（§2）。 */
import { layout } from '../../styles/theme';
import { useCallback, useEffect, useRef, useState } from 'react';

export function useSplitDrag(initialPct: number = layout.split.initial): {
  pct: number;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onHandleDown: () => void;
} {
  const [pct, setPct] = useState<number>(initialPct);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);

  const onHandleDown = useCallback(() => {
    draggingRef.current = true;
  }, []);

  useEffect(() => {
    const move = (event: MouseEvent): void => {
      if (!draggingRef.current || containerRef.current === null) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = ((event.clientX - rect.left) / rect.width) * 100;
      setPct(Math.min(layout.split.max, Math.max(layout.split.min, next)));
    };
    const up = (): void => {
      draggingRef.current = false;
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
  }, []);

  return { pct, containerRef, onHandleDown };
}
