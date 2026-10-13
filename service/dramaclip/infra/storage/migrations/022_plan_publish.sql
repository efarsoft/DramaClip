-- 022：方案发布物料（发布文案+话题标签），随候选标题同一次 LLM 往返产出。
ALTER TABLE narration_plans ADD COLUMN publish_meta TEXT;
