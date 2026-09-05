-- W2：第一层分析产出音频特征（能量曲线/静音比/语音区），独立成列而非混入 conflict_scores
ALTER TABLE episode_analysis ADD COLUMN audio_features TEXT;
