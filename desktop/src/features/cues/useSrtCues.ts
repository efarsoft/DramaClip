/** 读取 SRT 产物并解析为逐句（工具箱 copy.srt 与成片旁挂 output.srt 共用同一份判读口径）。
 * 「没有」与「读不到」分开报：前者是旧成片/不烧字幕的正常状态，后者要常驻。 */
import { useEffect, useState } from 'react';
import { mediaUrl } from '../../services/client';
import { parseSrt } from './srt';
import type { Cue } from './srt';

export interface CueState {
  readonly cues: readonly Cue[] | null;
  readonly error: string;
  /** 旁挂文件确实不在（media 协议 404 / 根本没给路径）：是「没有」，不是失败。 */
  readonly missing: boolean;
}

function emptyState(srtPath: string): CueState {
  return { cues: null, error: '', missing: srtPath === '' };
}

export function useSrtCues(srtPath: string): CueState {
  const [state, setState] = useState<CueState>(() => emptyState(srtPath));
  useEffect(() => {
    setState(emptyState(srtPath));
    if (srtPath === '') return;
    let alive = true;
    void fetch(mediaUrl(srtPath))
      .then((resp) => {
        if (!alive) return null;
        if (resp.status === 404) {
          setState({ cues: null, error: '', missing: true });
          return null;
        }
        if (!resp.ok) {
          setState({
            cues: null,
            error: `逐句时间轴加载失败：读取失败（HTTP ${String(resp.status)}）`,
            missing: false,
          });
          return null;
        }
        return resp.text();
      })
      .then((body) => {
        if (!alive || body === null) return;
        const parsed = parseSrt(body);
        setState(
          parsed.length > 0
            ? { cues: parsed, error: '', missing: false }
            : { cues: null, error: '逐句时间轴加载失败：SRT 里没有可解析的句子', missing: false },
        );
      })
      .catch((error: unknown) => {
        if (alive) {
          setState({
            cues: null,
            error: `逐句时间轴加载失败：${error instanceof Error ? error.message : String(error)}`,
            missing: false,
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [srtPath]);
  return state;
}
