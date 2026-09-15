import { describe, expect, it } from 'vitest';
import type { ModelInfo } from '@dramaclip/protocol';
import { buildDramas, buildTodos, type DramaState, type FailedJob, type TodoInput } from '../todos';

const NOW = 1_760_000_000_000;
const DAY = 86_400_000;

function model(over: Partial<ModelInfo> = {}): ModelInfo {
  return {
    model_id: 'asr-small', kind: 'asr', engine: 'faster_whisper',
    repo_id: 'Systran/faster-whisper-small', name: 'Whisper small',
    required: true, status: 'installed', ...over,
  };
}

function drama(over: Partial<DramaState> & { id: string }): DramaState {
  return {
    name: `剧${over.id}`, episodeCount: 10, workCount: 0,
    createdAtMs: NOW - 20 * DAY, ...over,
  };
}

function job(over: Partial<FailedJob> = {}): FailedJob {
  return { id: 'j1', type: 'analysis', refId: 'p1', error: 'ffmpeg 退出码 1', ...over };
}

function base(over: Partial<TodoInput> = {}): TodoInput {
  return {
    serviceDown: false, models: [model()], llmConfigured: true,
    dramas: [], failedJobs: [], serverTimeMs: NOW, ...over,
  };
}

describe('buildTodos', () => {
  it('全就绪返回空数组', () => {
    expect(buildTodos(base())).toEqual([]);
  });

  it('服务不可用给重启动作', () => {
    const items = buildTodos(base({ serviceDown: true }));
    expect(items[0]?.severity).toBe('error');
    expect(items[0]?.action).toEqual({ kind: 'restart-service', label: '重启服务' });
  });

  it('缺必需模型 → 去下载', () => {
    const items = buildTodos(base({ models: [model({ status: 'missing' })] }));
    expect(items[0]?.action).toEqual({ kind: 'navigate', label: '去下载', path: '/engines/asr' });
  });

  it('models 为 null 不得谎报缺模型', () => {
    expect(buildTodos(base({ models: null }))).toEqual([]);
  });

  it('未配编剧模型是 error 级', () => {
    const items = buildTodos(base({ llmConfigured: false }));
    expect(items[0]?.severity).toBe('error');
    expect(items[0]?.text).toContain('七个解说模式');
  });

  it('analysis 失败 → 跳分析页', () => {
    const items = buildTodos(base({ failedJobs: [job()] }));
    expect(items[0]?.action?.path).toBe('/projects/p1/analysis');
  });

  it('narration 失败 → 跳出片页', () => {
    const items = buildTodos(base({ failedJobs: [job({ id: 'j2', type: 'narration' })] }));
    expect(items[0]?.action?.path).toBe('/projects/p1/produce');
  });

  it('ref_id 不是 project_id 的三类不进待办', () => {
    const items = buildTodos(base({
      failedJobs: [
        job({ id: 'a', type: 'export', refId: 'e1' }),
        job({ id: 'b', type: 'model_download', refId: 'm1' }),
        job({ id: 'c', type: 'semantic', refId: 'ep1' }),
      ],
    }));
    expect(items).toEqual([]);
  });

  it('停滞剧超过阈值天数才催', () => {
    const items = buildTodos(base({ dramas: [drama({ id: 'p1' })] }));
    expect(items[0]?.severity).toBe('info');
    expect(items[0]?.text).toContain('10 集已就位');
  });

  it('新建的剧不催', () => {
    expect(buildTodos(base({ dramas: [drama({ id: 'p1', createdAtMs: NOW - DAY })] }))).toEqual([]);
  });

  it('有成品的不催', () => {
    expect(buildTodos(base({ dramas: [drama({ id: 'p1', workCount: 3 })] }))).toEqual([]);
  });
});

describe('buildDramas', () => {
  it('按 project_id 归集成片数', () => {
    const projects = [
      { id: 'p1', name: 'A', episode_count: 10, created_at: NOW },
      { id: 'p2', name: 'B', episode_count: 4, created_at: NOW },
    ];
    const works = [
      { id: 'w1', project_id: 'p1' },
      { id: 'w2', project_id: 'p1' },
    ];
    const result = buildDramas(projects, works);
    expect(result[0]?.workCount).toBe(2);
    expect(result[1]?.workCount).toBe(0);
  });
});
