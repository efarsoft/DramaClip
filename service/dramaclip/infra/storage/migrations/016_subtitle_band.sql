-- 016: A2 源片硬字幕带避让（探测结果落库，供烧录字幕抬 MarginV，不叠两行）
-- NULL 语义：无硬字幕带 / 未探测 / OCR 未装（rapidocr 缺失），消费端一律回退现状 margin_v。
-- 注：编号本为 015，与并行子任务的 015_export_selfcheck.sql 撞号，顺延为 016。
ALTER TABLE episode_analysis ADD COLUMN subtitle_band TEXT;
