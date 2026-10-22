/** W1·1.5 四门禁的界面侧契约（G3 留痕消费 / G4 回声与占位）。
 *
 * 后端侧 G1/G2 在 tests/api/test_w1_gates.py。变异锚定：这些断言在改动前的代码上
 * 全红（ExportsCard 无 degraded_notes、WorkbenchHeader 无 disabled/回声、行无「分析中」、
 * App 无 notifyLog 订阅）——门禁是防复发，不是给现状盖章。
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/** vitest 以 desktop/ 为 cwd：源码契约直接按 cwd 相对路径读（同 measureContract 口径）。 */
const read = (rel: string): string => readFileSync(rel, 'utf-8');

describe('W1 门禁（2026-10-16 规格 §1.5）', () => {
  it('G3 留痕消费：出片卡读 degraded_notes 且渲染降级徽章', () => {
    const card = read('src/features/narration/ExportsCard.tsx');
    expect(card).toContain('degraded_notes');
    expect(card).toContain('降级');
  });

  it('G3 留痕消费：渲染层存在 log.append 订阅且写进 store（App 装配）', () => {
    const store = read('src/stores/jobs.ts');
    expect(store).toContain("event.method !== 'log.append'");
    expect(store).toContain('appendNotifyLog');
    const app = read('src/app/App.tsx');
    expect(app).toContain('subscribeNotifyLog()');
  });

  it('G4 回声与占位：多选带「已选 n/m」回声，canStart 接按钮 disabled', () => {
    const header = read('src/features/analysis/WorkbenchHeader.tsx');
    expect(header).toContain('disabled={!canStart}');
    expect(header).toContain('已选');
  });

  it('G4 占位口径：量不到的位置是「—」不是空串', () => {
    const card = read('src/features/narration/ExportsCard.tsx');
    expect(card).toMatch(/duration_s !== undefined \? [^:]+ : '—'/);
  });

  it('G4 四态：集行有「分析中」态（running 不再并进待分析）', () => {
    const row = read('src/features/analysis/EpisodeListRow.tsx');
    expect(row).toContain("'running'");
    expect(row).toContain('分析中');
  });
});
