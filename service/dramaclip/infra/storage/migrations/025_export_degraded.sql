-- 降级留痕「账在库」（2026-10-16 UI 真相规格 §1.2）：允许型降级的账此前只进通知流，
-- 重启即失。JSON 数组 [{subject, outcome, at}]，由 _note_degraded 在导出作业上下文内
-- 单点追加；NULL = 本次无降级。重试覆盖写时随 reset_for_retry 一并清空（新一轮重新记账）。
ALTER TABLE export_jobs ADD COLUMN degraded_notes TEXT;
