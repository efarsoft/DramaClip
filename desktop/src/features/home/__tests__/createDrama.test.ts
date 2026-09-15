/** 建剧动作：目录名即剧名（规格 §1「剧名直接取文件夹名即与片单天然对齐，无需手输」），
 *  用户取消不是失败。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/client', () => ({
  pickFolder: vi.fn(),
  projectApi: { create: vi.fn(), scanEpisodes: vi.fn() },
}));

import { pickFolder, projectApi } from '../../../services/client';
import { createDramaFromFolder, folderName } from '../createDrama';

const mockedPick = vi.mocked(pickFolder);
const mockedCreate = vi.mocked(projectApi.create);
const mockedScan = vi.mocked(projectApi.scanEpisodes);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('folderName', () => {
  it('Windows 反斜杠路径取末段', () => {
    expect(folderName('D:\\BaiduNetdiskDownload\\小小球神不好惹')).toBe('小小球神不好惹');
  });

  it('POSIX 正斜杠路径取末段', () => {
    expect(folderName('/media/drama/逆袭开局')).toBe('逆袭开局');
  });

  it('尾部带分隔符时不得返回空串', () => {
    expect(folderName('D:\\drama\\逆袭开局\\')).toBe('逆袭开局');
    expect(folderName('/media/drama/逆袭开局/')).toBe('逆袭开局');
  });

  it('只有根或空串时给一个可用的兜底名', () => {
    expect(folderName('D:\\')).toBe('新剧');
    expect(folderName('')).toBe('新剧');
  });
});

describe('createDramaFromFolder', () => {
  it('用户取消选择返回 null，且不建项目不扫集', async () => {
    mockedPick.mockResolvedValue(null);
    expect(await createDramaFromFolder()).toBeNull();
    expect(mockedCreate).not.toHaveBeenCalled();
    expect(mockedScan).not.toHaveBeenCalled();
  });

  it('选中目录则以目录名建项目、扫集，并回一个可跳的入口路径', async () => {
    mockedPick.mockResolvedValue('D:\\drama\\逆袭开局');
    mockedCreate.mockResolvedValue({
      id: 'p1',
      name: '逆袭开局',
      source_path: 'D:\\drama\\逆袭开局',
      status: 'created',
      created_at: 1,
      episode_count: 0,
      settings: {},
    });
    mockedScan.mockResolvedValue([]);
    const result = await createDramaFromFolder();
    expect(mockedCreate).toHaveBeenCalledWith('逆袭开局', 'D:\\drama\\逆袭开局');
    expect(mockedScan).toHaveBeenCalledWith('p1');
    expect(result).toEqual({
      projectId: 'p1',
      name: '逆袭开局',
      entryPath: '/projects/p1/analysis',
    });
  });
});
