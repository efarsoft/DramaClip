-- B8 源失效判据：episodes.source_signature = 产出当前分析/预筛结果时的源文件签名
-- （md5(path|size|mtime_ns|ocr_channel)，计算见 engines/analysis/pipeline.source_signature）。
-- 与当前源不一致时，done 集在 analyze/prescreen 纳入目标时强制重算，防「源换了还静默用旧 ASR」。
-- 挂 episodes 而非 episode_analysis：prescreen 产物（episode_prescreen）同样由源派生，
-- 且预筛时可能尚无 analysis 行；导入 replace_all 重建 episodes 行，签名自然清零，语义一致。
ALTER TABLE episodes ADD COLUMN source_signature TEXT;
