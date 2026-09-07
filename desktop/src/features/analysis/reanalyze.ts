/** 重新分析单集（覆盖该集转写与语义）。 */
import { analysisApi } from '../../services/client';

/** 重新分析单集（覆盖该集转写与语义）。 */

export function reanalyzeEpisode(
  projectId: string,
  episodeId: string,
  episodeNumber: number,
  onNotify: (text: string) => void,
  onError: (text: string) => void,
): void {
  analysisApi
    .start(projectId, [episodeId])
    .then(() => {
      onNotify(`第${String(episodeNumber)}集 重新分析已提交`);
    })
    .catch((error: unknown) => {
      onError(error instanceof Error ? error.message : String(error));
    });
}
