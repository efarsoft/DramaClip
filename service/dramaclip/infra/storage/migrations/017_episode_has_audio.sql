-- 素材行「缺音频轨告警」（09-10 §2.3① / 卷二 #5）：扫描时把 ffprobe 的音轨判定随集落库。
-- NULL = 迁移前的旧集还没重新扫描：取不到 ≠ 没有，界面按未知处理，不计入缺音轨告警。
ALTER TABLE episodes ADD COLUMN has_audio INTEGER;
