-- 2026-11-12 业主裁决：高光混剪（highlight_cut）完全清除。
-- 该模式 2026-10-27 合并退役（并入 raw_clip 单入口，5 秒均切取消），生成白名单
-- 早无此模式；本迁移把存量方案行一并删掉——留着只会是一张无法再生成、
-- 消费分支也已删除的死方案卡。历史推荐缓存（projects.settings 的
-- mode_recommendation）不在此删：mode_recommend 读时净化并回写。
DELETE FROM narration_plans WHERE narration_mode = 'highlight_cut';
