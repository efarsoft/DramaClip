/**
 * 修复动作的判定口径（§10.2）：哪个 warn 判据配哪个动作，由后端 verify 的判据名
 * 推导——按钮与体检同源，清完再校验必须回绿，否则动作就是摆设。
 * 不解析 detail 文案（文案会改，判据名是契约）；「唯一路径」的结构化 paths
 * 直接充当删除白名单的前端展示源，真正的白名单校验在服务端。
 */
import type { VerifyReport } from '@dramaclip/protocol';

export interface RepairNeeds {
  /** 「中断残留」warn → models.clean_residue（能自动档：点了就干）。 */
  readonly residue: boolean;
  /** 「快照提交号」warn（snapshots/main 无从对账）→ models.relayout 就地迁移。 */
  readonly migrate: boolean;
  /** 「唯一路径」warn 的结构化 paths → models.orphan_list/clean_orphan 的名单。 */
  readonly orphanPaths: readonly string[];
}

const CHECK_RESIDUE = '中断残留';
const CHECK_SNAPSHOT = '快照提交号';
const CHECK_UNIQUE = '唯一路径';

export function repairNeeds(report: VerifyReport | undefined): RepairNeeds {
  const checks = report?.checks ?? [];
  const warned = (name: string): boolean =>
    checks.some((check) => check.name === name && check.status === 'warn');
  const unique = checks.find((check) => check.name === CHECK_UNIQUE && check.status === 'warn');
  return {
    residue: warned(CHECK_RESIDUE),
    migrate: warned(CHECK_SNAPSHOT),
    orphanPaths: unique?.paths ?? [],
  };
}
