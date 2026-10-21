-- 算力回执：JSON 数组（ComputeReport）；NULL = 本次没有可报告的运行证据。
ALTER TABLE jobs ADD COLUMN compute TEXT;
ALTER TABLE export_jobs ADD COLUMN compute TEXT;
