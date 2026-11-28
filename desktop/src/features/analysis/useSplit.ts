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
  // 拖拽中的最新值进 ref 不进盘：localStorage 同步 IO 不该跟手——每个 mousemove
  // 写一次盘是主线程抖动源，松手落一次账即可（§2：布局偏好落盘）。
  const lastClampedRef = useRef<number>(pct);

  const onHandleDown = useCallback(() => {
    draggingRef.current = true;
  }, []);

  useEffect(() => {
    const move = (event: MouseEvent): void => {
      if (!draggingRef.current || containerRef.current === null) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = ((event.clientX - rect.left) / rect.width) * 100;
      const clamped = Math.min(layout.split.max, Math.max(layout.split.min, next));
      lastClampedRef.current = clamped;
      setPct(clamped);
    };
    const up = (): void => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      try {
        localStorage.setItem(STORAGE_KEY, String(lastClampedRef.current));
      } catch {
        // 隐私模式/配额满——不阻塞松手
      }
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
