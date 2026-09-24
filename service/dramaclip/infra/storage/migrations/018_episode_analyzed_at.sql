-- 阶段条「已过期」金灯的对账列（09-10 §3.1 / 卷二 §2 审计「新列 analyzed_at 对账」）。
-- 分析落库（status='done'）时写服务毫秒；MAX(episodes.analyzed_at) 随 project.list/get
-- 聚合上屏，与 MAX(narration_plans.created_at) 比先后：分析新于方案 → ③ 过期金灯。
-- NULL = 没分析过或迁移前旧数据：取不到 ≠ 不存在，金灯此时保持灰，不猜。
ALTER TABLE episodes ADD COLUMN analyzed_at INTEGER;
