// @vitest-environment jsdom
/**
 * 导入向导的两个易碎处：**提交这一下只能交一次作业**，**弹窗关了不留残局**。
 *
 * 落位是「把几个 GB 搬进库」的动作，交两遍等于往库里复制两次、还各起一个作业；
 * 所以第 ③ 步的按钮在作业号回来之前必须按住。残局那条更直接：同一棵组件树复用
 * 时若不清场，业主第二次打开看到的是上一次的体检结果。
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import type { ReactElement } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ImportInspection } from '@dramaclip/protocol';
import { ImportModelModal } from '../ImportModelModal';
import { importJob as job, importRecord, inspection } from './fixtures';

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
const noop = (): void => undefined;
const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });

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

function modal(onChanged: () => void = noop): void {
  render(<ImportModelModal open onClose={noop} onChanged={onChanged} onActivate={noop} />);
}

/**
 * 真实应用里 `open` 握在父页手上（资产库工具栏那个按钮），所以「清场」只能按
 * 同一棵组件树开→关→开来验，不能靠重新挂载混过去。
 */
function Toggle(): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        打开向导
      </button>
      <button
        type="button"
        onClick={() => {
          setOpen(false);
        }}
      >
        收起向导
      </button>
      <ImportModelModal
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        onChanged={noop}
        onActivate={noop}
      />
    </>
  );
}

/** 走到第 ③ 步：选目录、体检通过、下一步已放行。 */
async function toLandStep(report: ImportInspection = inspection()): Promise<void> {
  inspectImport.mockResolvedValue(report);
  getRecords.mockResolvedValue({ records: [importRecord()], error: '' });
  pick.mockResolvedValue(PICKED);
  fireEvent.click(screen.getByRole('button', { name: /选择目录/ }));
  await screen.findByText('识别结果');
  fireEvent.click(screen.getByRole('button', { name: /下一步/ }));
  await screen.findByText('落位方式');
}

function landButton(): HTMLElement {
  return screen.getByRole('button', { name: /开始导入/ });
}

function note(): string {
  return screen.getByRole('alert').textContent;
}

afterEach(() => {
  cleanup();
  [pick, inspectImport, commitImport, getJob, getRecords].forEach((fn) => {
    fn.mockReset();
  });
});

describe('第 ③ 步的提交只交一次', () => {
  it('作业号还没回来时连点，也只交一份作业', async () => {
    let settleCommit: (value: { job_id: string }) => void = () => undefined;
    commitImport.mockReturnValue(
      new Promise((resolve) => {
        settleCommit = resolve;
      }),
    );
    getJob.mockResolvedValue({ job: job({ status: 'running', progress: 5 }) });
    modal();
    await toLandStep();

    fireEvent.click(landButton());
    fireEvent.click(landButton());

    expect(commitImport).toHaveBeenCalledTimes(1);
    settleCommit({ job_id: 'j1' });
    await waitFor(() => {
      expect(screen.getByText(/落位中/)).toBeTruthy();
    });
    // 一份作业只轮询它自己：作业号是提交回来的那个，不是前端造的。
    await waitFor(() => {
      expect(getJob).toHaveBeenCalledWith('j1');
    });
  });

  it('后端当面拒绝提交：原话贴在第 ③ 步，不进第 ④ 步', async () => {
    commitImport.mockRejectedValue(new Error('磁盘剩余空间不够落位'));
    modal();
    await toLandStep();

    fireEvent.click(landButton());

    await waitFor(() => {
      expect(note()).toContain('磁盘剩余空间不够落位');
    });
    expect(screen.getByText('落位方式')).toBeTruthy();
    expect(screen.queryByText(/落位中/)).toBeNull();
    expect(getJob).not.toHaveBeenCalled();
  });
});

describe('作业没留原因时不编原因', () => {
  it('作业被中止且 error 为空：说「没跑完就停了」，既不摆完成页也不说还在跑', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    getJob.mockResolvedValue({ job: job({ status: 'cancelled', error: null }) });
    modal();
    await toLandStep();

    fireEvent.click(landButton());

    await waitFor(() => {
      expect(note()).toContain('落位作业没跑完就停了');
    });
    expect(screen.queryByText(/落位中/)).toBeNull();
    expect(screen.queryByText(/已导入/)).toBeNull();
    expect(getRecords).not.toHaveBeenCalled();
  });
});

describe('关掉弹窗不叫停作业，但也不再回喊资产库', () => {
  it('作业在眼前完成：资产库被回喊一次', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    getJob.mockResolvedValue({ job: job() });
    const onChanged = vi.fn();
    modal(onChanged);
    await toLandStep();
    fireEvent.click(landButton());

    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledTimes(1);
    });
  });

  it('作业在关窗之后才说完成：不去刷新资产库', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    // 慢半拍的轮询：提交后 300ms 才回话说完成，中间业主已经把窗关了。
    getJob.mockImplementation(() => sleep(300).then(() => ({ job: job() })));
    const onChanged = vi.fn();
    modal(onChanged);
    await toLandStep();
    fireEvent.click(landButton());
    await waitFor(() => {
      expect(getJob).toHaveBeenCalledWith('j1');
    });

    cleanup();
    await sleep(400);

    expect(onChanged).not.toHaveBeenCalled();
  });

  /** 上一条关在第一问的路上；这一条关在「作业已说完成、登记本还在读」的那一拍。 */
  it('登记本还在读时关窗：读完了也不回喊资产库', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    getJob.mockResolvedValue({ job: job() });
    const onChanged = vi.fn();
    modal(onChanged);
    await toLandStep();
    // 慢登记本要设在 toLandStep 之后：它自己会把登记本设成立刻应答的那一份。
    getRecords.mockImplementation(() =>
      sleep(600).then(() => ({ records: [importRecord()], error: '' })),
    );
    fireEvent.click(landButton());
    // 见到登记本被读过，才说明第一道闸门当时放行；此后只剩这一道拦得住回喊。
    await waitFor(() => {
      expect(getRecords).toHaveBeenCalledTimes(1);
    });
    cleanup();
    await sleep(800);

    expect(onChanged).not.toHaveBeenCalled();
  });
});

/** 回喊之外，关窗还得掐断后台那条自己续自己的轮询链。 */
describe('关掉弹窗也不留在后台追问作业号', () => {
  it('作业还在跑时关窗：轮询链跟着断，不在后台一直追问作业号', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    // 慢应答：第一问还在路上业主就把窗关了，回来的续答必须就地作废。
    getJob.mockImplementation(() =>
      sleep(300).then(() => ({ job: job({ status: 'running', progress: 10 }) })),
    );
    modal();
    await toLandStep();
    fireEvent.click(landButton());
    await waitFor(() => {
      expect(getJob).toHaveBeenCalledTimes(1);
    });

    cleanup();
    // 轮询间隔 800ms：留够两拍的窗口，漏网的链子一定会在这里现形。
    await sleep(1_800);

    expect(getJob).toHaveBeenCalledTimes(1);
  });

  /** 上一条的反面：同一套替身、同样的等待时长，没关窗就该继续问下去。 */
  it('对照：不关窗就还会接着问（否则上一条是空转通过的）', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    getJob.mockResolvedValue({ job: job({ status: 'running', progress: 10 }) });
    modal();
    await toLandStep();
    fireEvent.click(landButton());
    await waitFor(() => {
      expect(getJob).toHaveBeenCalledTimes(1);
    });

    await sleep(1_800);

    expect(getJob.mock.calls.length).toBeGreaterThan(1);
  });
});

describe('关窗即清场', () => {
  it('再打开从第 ① 步开始，不把上一轮的体检结果留在屏上', async () => {
    commitImport.mockResolvedValue({ job_id: 'j1' });
    getJob.mockResolvedValue({ job: job() });
    render(<Toggle />);
    fireEvent.click(screen.getByRole('button', { name: /打开向导/ }));
    await toLandStep();
    fireEvent.click(landButton());
    await screen.findByText(/已导入/);

    fireEvent.click(screen.getByRole('button', { name: /收起向导/ }));
    fireEvent.click(screen.getByRole('button', { name: /打开向导/ }));

    expect(screen.getByRole('button', { name: /选择目录/ })).toBeTruthy();
    expect(screen.queryByText('识别结果')).toBeNull();
    expect(inspectImport).toHaveBeenCalledTimes(1);
  });
});
