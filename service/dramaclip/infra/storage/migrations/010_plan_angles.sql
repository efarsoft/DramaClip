-- P-2a 规划/渲染解耦：一条方案要能被当成「一个角度」来看、来比、来重掷。
-- 五列都是真列而不是塞进 plan_data：角度要查重叠、要按名排除、要按 batch 取组，
-- 塞在 JSON 里就得每行解析一遍。权威定义同步更新 docs/service/04-数据模型.md。
ALTER TABLE narration_plans ADD COLUMN angle TEXT NOT NULL DEFAULT '';
ALTER TABLE narration_plans ADD COLUMN angle_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE narration_plans ADD COLUMN variant_index INTEGER NOT NULL DEFAULT 1;
ALTER TABLE narration_plans ADD COLUMN overlap_max REAL;
ALTER TABLE narration_plans ADD COLUMN batch_id TEXT;
CREATE INDEX IF NOT EXISTS idx_plans_batch ON narration_plans(project_id, batch_id);
