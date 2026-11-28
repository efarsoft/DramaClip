/** 剧集顺序管理：本地拖拽/移动产生的临时顺序与落库回调。 */
import { useCallback, useMemo, useRef, useState } from 'react';
import type { Episode } from '@dramaclip/protocol';

export function useEpisodeOrder(
  episodes: Episode[],
  onCommit: (orderedIds: string[]) => void,
): {
  orderedIds: string[];
  byId: Map<string, Episode>;
  dragIndex: React.RefObject<number | null>;
  overIndex: number | null;
  setOverIndex: (index: number | null) => void;
  onDragStart: (index: number) => void;
  drop: (targetIndex: number) => void;
  move: (index: number, direction: -1 | 1) => void;
} {
  const dragIndex = useRef<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [order, setOrder] = useState<string[] | null>(null);

  // 引用稳定挂 useMemo：分栏拖拽的每次 mousemove 都会重渲染本 hook 的宿主，
  // 新数组/新 Map 的引用会把下游 memo 击穿（集行连坐重渲染的来源之一）。
  const orderedIds = useMemo(
    () => order ?? episodes.map((episode) => episode.id),
    [order, episodes],
  );
  const byId = useMemo(
    () => new Map(episodes.map((episode) => [episode.id, episode])),
    [episodes],
  );

  const applyNext = useCallback(
    (next: string[]): void => {
      setOrder(next);
      onCommit(next);
    },
    [onCommit],
  );

  const drop = useCallback(
    (targetIndex: number): void => {
      const from = dragIndex.current;
      dragIndex.current = null;
      setOverIndex(null);
      if (from === null || from === targetIndex) return;
      const next = [...orderedIds];
      const [moved] = next.splice(from, 1);
      if (moved === undefined) return;
      next.splice(targetIndex, 0, moved);
      applyNext(next);
    },
    [applyNext, orderedIds],
  );

  const move = useCallback(
    (index: number, direction: -1 | 1): void => {
      const target = index + direction;
      if (target < 0 || target >= orderedIds.length) return;
      const next = [...orderedIds];
      const [moved] = next.splice(index, 1);
      if (moved === undefined) return;
      next.splice(target, 0, moved);
      applyNext(next);
    },
    [applyNext, orderedIds],
  );

  const onDragStart = useCallback((index: number): void => {
    dragIndex.current = index;
  }, []);

  return { orderedIds, byId, dragIndex, overIndex, setOverIndex, onDragStart, drop, move };
}
