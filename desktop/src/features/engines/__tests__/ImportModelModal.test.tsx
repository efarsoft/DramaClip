// @vitest-environment jsdom
/**
 * 导入向导四步的行为判据（D 案验收标准第 ③④ 条）。
 *
 * 三条规矩逐条钉住：
 * 1. **第 ② 步不通过就进不了第 ③ 步**：下一步禁用，且理由点出还缺什么选择。
 * 2. **异常态各有各的出口**：不完整要业主显式勾选、冲突要裁决、未识别要声明能力。
 * 3. **完成页只念后端给的事实**：落位路径出自登记本，失败原因出自作业，前端不拼话术。
 *
 * 闸门判据本身在 importWizard.test.ts 逐条钉死；这里验的是它接到按钮上之后还灵不灵。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ImportInspection, ImportRecord, JobInfo } from '@dramaclip/protocol';
import { ImportModelModal } from '../ImportModelModal';
import { externalInspection as external, importJob as job, importRecord, inspection } from './fixtures';

const pick = vi.hoisted(() => vi.fn());
const inspectImport = vi.hoisted(() => vi.fn());
const commitImport = vi.hoisted(() => vi.fn());
const getJob = vi.hoisted(() => vi.fn());
const getRecords = vi.hoisted(() => vi.fn());

vi.mock('../../../services/client', () => ({
  pickFolder: (): unknown => pick(),
  modelsApi: {
    inspectImport: (path: string): unknown => inspectImport(path),
    commitImport: (payload: Record<string, unknown>): unknown => commitImport(payload),
    importRecords: (): unknown => getRecords(),
  },
  jobsApi: {
    get: (jobId: string): unknown => getJob(jobId),
  },
}));

const PICKED = 'E:\\下载\\models--Systran--faster-whisper-medium';

/** jsdom 不实现 matchMedia，antd 的浮层与响应式观察器一挂就是全红——补一个最小假象。 */
beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
});

const noop = (): void => {
  // 只验流程，写回由父页负责
};

function open(onActivate: (modelId: string) => void = noop): void {
  render(<ImportModelModal open onClose={noop} onChanged={noop} onActivate={onActivate} />);
  pick.mockResolvedValue(PICKED);
  getRecords.mockResolvedValue({ records: [importRecord()], error: '' });
}

/** 第 ① → ② 步：选完目录，只读体检的结果已回。 */
async function inspect(report: ImportInspection): Promise<void> {
  inspectImport.mockResolvedValue(report);
  fireEvent.click(screen.getByRole('button', { name: /选择目录/ }));
  await screen.findByText('识别结果');
}

/** 第 ③ → ④ 步：按下开始导入，作业与登记本各按给定的实测结果回。 */
function land(result: JobInfo, stored: Stored = { records: [importRecord()], error: '' }): void {
  commitImport.mockResolvedValue({ job_id: 'j1' });
  getJob.mockResolvedValue({ job: result });
  getRecords.mockResolvedValue(stored);
  fireEvent.click(screen.getByRole('button', { name: /开始导入/ }));
}

interface Stored {
  records: ImportRecord[];
  error: string;
}

/** 拦住业主的那道闸门：第 ②③ 步共用同一条判据与同一句理由。 */
function gate(): HTMLElement {
  return screen.getByRole('button', { name: /下一步/ });
}

function passGate(): void {
  fireEvent.click(gate());
}

function note(): string {
  return screen.getByRole('alert').textContent;
}

/** 认不出身份的目录只能仅登记：登记本里那条没有 model_id。 */
function asExternal(report: ImportInspection): ImportRecord {
  return importRecord({ model_id: null, kind: 'asr', engine: '', path: report.source_path, mode: 'register' });
}

afterEach(() => {
  cleanup();
  [pick, inspectImport, commitImport, getJob, getRecords].forEach((fn) => {
    fn.mockReset();
  });
});

describe('第 ① → ② 步：只读体检', () => {
  it('识别结果连依据一起摆出来，一个字节都不动', async () => {
    open();
    await inspect(inspection());

    expect(inspectImport).toHaveBeenCalledWith(PICKED);
    expect(screen.getByText('Whisper Medium（高准确度）')).toBeTruthy();
    expect(screen.getByText(/model_type=ct2/)).toBeTruthy();
    expect(screen.getByText(/9 个文件/)).toBeTruthy();
  });

  it('读不到目录时把后端原话贴出来，不进第 ② 步', async () => {
    open();
    pick.mockResolvedValue('E:\\没这个东西');
    inspectImport.mockRejectedValue(new Error('来源目录不存在或不是目录：E:\\没这个东西'));
    fireEvent.click(screen.getByRole('button', { name: /选择目录/ }));

    await waitFor(() => {
      expect(note()).toContain('来源目录不存在或不是目录');
    });
    expect(screen.queryByText('识别结果')).toBeNull();
  });
});

describe('第 ② 步闸门 · 体检不通过', () => {
  const broken = inspection({
    ok: false,
    checks: [{ name: '必需文件', status: 'fail', detail: '缺 tokenizer.json' }],
  });

  it('下一步禁用，理由点出缺哪几项，第 ③ 步进不去', async () => {
    open();
    await inspect(broken);

    expect(gate().hasAttribute('disabled')).toBe(true);
    expect(note()).toContain('必需文件');
    passGate();
    expect(screen.queryByText('落位方式')).toBeNull();
  });

  it('业主显式勾选「按现状导入并标记为不完整」后放行', async () => {
    open();
    await inspect(broken);

    fireEvent.click(screen.getByRole('checkbox', { name: /不完整/ }));
    await waitFor(() => {
      expect(gate().hasAttribute('disabled')).toBe(false);
    });
    passGate();
    expect(await screen.findByText('落位方式')).toBeTruthy();
  });
});

describe('第 ② 步闸门 · 库里撞车', () => {
  const clash = inspection({
    conflict: {
      model_id: 'faster-whisper-medium',
      path: 'D:\\data\\models\\asr\\faster-whisper',
      size_bytes: 2_100_000_000,
      ok: false,
      failed_checks: ['必需文件'],
    },
  });

  it('不裁决就不给走，撞车那一份的缺项也一起摆出来', async () => {
    open();
    await inspect(clash);

    expect(gate().hasAttribute('disabled')).toBe(true);
    expect(note()).toContain('冲突');
    // 撞车那一条要说的是库内路径与缺项；闸门话术里也有「库里已有」，所以按 model_id 认。
    expect(screen.getByText(/库里已有 faster-whisper-medium/).textContent).toContain('必需文件');
    passGate();
    expect(screen.queryByText('落位方式')).toBeNull();
  });

  it('选了「用导入的覆盖」便带进提交负载', async () => {
    open();
    await inspect(clash);
    fireEvent.click(screen.getByRole('radio', { name: /用导入的覆盖/ }));
    await waitFor(() => {
      expect(gate().hasAttribute('disabled')).toBe(false);
    });
    passGate();
    land(job());

    await waitFor(() => {
      expect(commitImport).toHaveBeenCalledWith({
        path: clash.source_path,
        mode: 'copy',
        on_conflict: 'overwrite',
      });
    });
  });
});

describe('第 ② 步闸门 · 认不出身份', () => {
  const given = external();

  it('没声明能力就不给走', async () => {
    open();
    await inspect(given);

    expect(gate().hasAttribute('disabled')).toBe(true);
    expect(note()).toContain('能力');
    passGate();
    expect(screen.queryByText('落位方式')).toBeNull();
  });

  it('声明能力后落位只剩「仅登记」且它是选中态，提交带上能力与命名', async () => {
    open();
    await inspect(given);
    fireEvent.click(screen.getByRole('radio', { name: /识别 ASR/ }));
    await waitFor(() => {
      expect(gate().hasAttribute('disabled')).toBe(false);
    });
    fireEvent.change(screen.getByPlaceholderText(/名称/), { target: { value: '同事的模型' } });
    passGate();

    expect(screen.queryByRole('radio', { name: /复制到规范目录/ })).toBeNull();
    expect(screen.getByRole<HTMLInputElement>('radio', { name: /仅登记/ }).checked).toBe(true);
    land(job(), { records: [asExternal(given)], error: '' });

    await waitFor(() => {
      expect(commitImport).toHaveBeenCalledWith({
        path: given.source_path,
        mode: 'register',
        external_kind: 'asr',
        label: '同事的模型',
      });
    });
  });
});

describe('第 ④ 步只念后端给的事实', () => {
  it('内置资产：落位路径与来源标记都在，也给「选为生效」', async () => {
    const onActivate = vi.fn();
    open(onActivate);
    await inspect(inspection());
    passGate();
    land(job());

    await waitFor(() => {
      expect(screen.getByText(/已导入/).textContent).toContain(
        'D:\\data\\models\\asr\\faster-whisper\\models--Systran--faster-whisper-medium',
      );
    });
    expect(screen.getByText(/本地导入/)).toBeTruthy();
    // 收尾那颗按钮说的是「回哪儿」，不是含糊的「关闭」。
    expect(screen.getByRole('button', { name: /返回资产库/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /选为生效/ }));
    expect(onActivate).toHaveBeenCalledWith('faster-whisper-medium');
  });

  it('引擎还没接入：说明原因，不给生效入口', async () => {
    open();
    await inspect(inspection({ engine_ready: false }));
    passGate();
    land(job());

    await waitFor(() => {
      expect(screen.getByText(/已导入/)).toBeTruthy();
    });
    expect(screen.getByText(/引擎未接入/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /选为生效/ })).toBeNull();
  });

  it('清单外的资产压根没有 model_id，完成页不给生效入口', async () => {
    const given = external();
    open();
    await inspect(given);
    fireEvent.click(screen.getByRole('radio', { name: /识别 ASR/ }));
    passGate();
    land(job(), { records: [asExternal(given)], error: '' });

    await waitFor(() => {
      expect(screen.getByText(/已登记/).textContent).toContain('E:\\下载');
    });
    expect(screen.queryByRole('button', { name: /选为生效/ })).toBeNull();
  });
});

describe('第 ④ 步 · 作业没说好就不说完成', () => {
  it('作业还在跑时不宣布完成，也不提前去读登记本', async () => {
    open();
    await inspect(inspection());
    passGate();
    land(job({ status: 'running', progress: 40 }));

    // 百分比也是作业报的数，不是前端自己编的进度条。
    expect(await screen.findByText(/落位中 40/)).toBeTruthy();
    expect(screen.queryByText(/已导入/)).toBeNull();
    expect(getRecords).not.toHaveBeenCalled();
  });

  it('作业失败时把 importer 的拒绝话术原样贴出，不说完成', async () => {
    open();
    await inspect(inspection());
    passGate();
    land(job({ status: 'failed', error: '体检未通过，不能落位（必需文件）' }));

    await waitFor(() => {
      expect(note()).toContain('体检未通过，不能落位（必需文件）');
    });
    // 说「没跑完」与说「还在跑 / 请到别处核对」不能同时出现在一块屏上。
    expect(screen.queryByText(/落位中/)).toBeNull();
    expect(screen.queryByText(/核对/)).toBeNull();
    expect(screen.queryByText(/已导入/)).toBeNull();
  });

  it('作业结束了、登记本里却没有这次那条：不编落位路径，让人回资产库核对', async () => {
    open();
    await inspect(inspection());
    passGate();
    // 登记本里有货，但没有一条是这次这个来源——照抄别人的路径就是把业主指到别家目录。
    land(job(), {
      records: [importRecord({ source_path: 'E:\\下载\\别的模型', path: 'D:\\data\\models\\asr\\other' })],
      error: '',
    });

    await waitFor(() => {
      expect(screen.getByText(/核对/)).toBeTruthy();
    });
    expect(screen.queryByText(/已导入/)).toBeNull();
    expect(screen.queryByRole('button', { name: /选为生效/ })).toBeNull();
  });
});
