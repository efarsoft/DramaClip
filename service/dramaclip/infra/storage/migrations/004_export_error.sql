-- 修复：mark_failed 写 error 列但建表遗漏，导出失败时失败处理自身崩溃
ALTER TABLE export_jobs ADD COLUMN error TEXT;
