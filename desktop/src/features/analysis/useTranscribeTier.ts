/** 转写档位持久化：project.settings 覆盖（project.update_settings 真存真读）；
 * 乐观更新，保存失败回滚并把错误原文说出来——档位悄悄没存上比报错更糟。 */
import { useCallback, useEffect, useState } from 'react';
import type { Project } from '@dramaclip/protocol';
import { projectApi } from '../../services/client';
import { parseTier, TIER_KEY, type TranscribeTier } from './analysisView';

export interface TierState {
  tier: TranscribeTier;
  saving: boolean;
  setTier: (next: TranscribeTier) => void;
}

export function useTranscribeTier(
  projectId: string,
  project: Project | null,
  onError: (message: string) => void,
): TierState {
  const persisted = project === null ? undefined : project.settings[TIER_KEY];
  const [tier, setTierState] = useState<TranscribeTier>(() => parseTier(persisted));
  const [saving, setSaving] = useState(false);

  // 项目载入（或别处改了设置）后回读：界面以持久化值为准
  useEffect(() => {
    setTierState(parseTier(persisted));
  }, [persisted]);

  const setTier = useCallback(
    (next: TranscribeTier): void => {
      const prev = tier;
      if (next === prev) return;
      setTierState(next);
      setSaving(true);
      projectApi
        .updateSettings(projectId, { [TIER_KEY]: next })
        .catch((error: unknown) => {
          setTierState(prev);
          onError(error instanceof Error ? error.message : String(error));
        })
        .finally(() => {
          setSaving(false);
        });
    },
    [onError, projectId, tier],
  );

  return { tier, saving, setTier };
}
