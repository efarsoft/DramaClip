-- 视觉轨（P2a 结构信号层）产物列：{"contact_sheet": "<png 路径>", ...}。
-- NULL = 未生成/生成失败/迁移前旧数据——视觉轨是分档能力，缺列不挡分析，
-- 消费端（编剧视觉摘要/选集加权）对 NULL 一律回退纯台词行为。
ALTER TABLE episode_analysis ADD COLUMN visual_track TEXT;
