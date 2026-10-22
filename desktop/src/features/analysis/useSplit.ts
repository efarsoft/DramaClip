/** 分栏拖拽 hook：返回 [宽度百分比, 拖拽把手事件]。默认值与带宽同读 layout.split（§2）。 */
import { layout } from '../../styles/theme';
import { useCallback, useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'dramaclip.split-pct';

export function useSplitDrag(initialPct: number = layout.split.initial): {
  pct: number;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onHandleDown: () => void;
} {
  const [pct, setPct] = useState<number>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored !== null ? Math.min(layout.split.max, Math.max(layout.split.min, Number(stored))) : initialPct;
    } catch {
      return initialPct;
    }
  });
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
      const clamped = Math.min(layout.split.max, Math.max(layout.split.min, next));
      setPct(clamped);
      try {
        localStorage.setItem(STORAGE_KEY, String(clamped));
      } catch {
        // 隐私模式/配额满——不阻塞拖拽
      }
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
