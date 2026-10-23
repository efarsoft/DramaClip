-- 发布数据回流（W8·MVP）：观众投票是系统唯一的外部真相源——复述/评分/audit
-- 都是「我们猜观众喜欢什么」的代理指标。JSON
-- {platform, plays, retention_pct, likes, published_at, recorded_at}，
-- export.set_publish_data 单点写入；NULL = 未录入。
-- 经 export_jobs.narration_plan_id 可回溯到方案（angle/arc/hook），为数据反馈
-- harness（0.2.4 第二层：数据驱动的选题/评分权重调整）备好原料。
ALTER TABLE export_jobs ADD COLUMN publish_data TEXT;
