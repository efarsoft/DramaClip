/** 剧集顺序管理：本地拖拽/移动产生的临时顺序与落库回调。 */
import { useCallback, useRef, useState } from 'react';
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

  const orderedIds = order ?? episodes.map((episode) => episode.id);
  const byId = new Map(episodes.map((episode) => [episode.id, episode]));

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
