-- W9 批次二：导出记录补成片元信息
ALTER TABLE export_jobs ADD COLUMN duration_s REAL;
ALTER TABLE export_jobs ADD COLUMN size_bytes INTEGER;
