"""
DramaClip - 音频爆点分析器

基于 librosa 进行音频特征分析，检测音频中的"爆点"：
- 音量突刺（突然的音量峰值）
- 语速突变（对话节奏变化）
- 能量突变（BGM激昂程度）
- 频谱变化（紧张/激烈场景特征）
"""

import os
import numpy as np
from typing import Optional, Tuple
from loguru import logger


# ===== 常量定义 =====#
DB_NORMALIZATION_MIN = -80   # dB 归一化最小值（静音）
DB_NORMALIZATION_MAX = 80    # dB 归一化最大值


class AudioScorer:
    """
    音频爆点评分器
    
    对镜头片段的音频进行分析，给出 0~1 的爆点得分。
    得分越高表示该片段越可能是高光时刻。
    """
    
    def __init__(self, 
                 sr: int = 22050,
                 peak_threshold_db: float = -10.0,
                 energy_change_threshold: float = 0.5):
        """
        Args:
            sr: 采样率
            peak_threshold_db: 峰值阈值(dB)，超过此值视为音量突刺
            energy_change_threshold: 能量变化阈值
        """
        self.sr = sr
        self.peak_threshold_db = peak_threshold_db
        self.energy_change_threshold = energy_change_threshold
    
    def score(self, audio_path: str) -> Tuple[float, dict]:
        """
        对音频文件进行爆点评分
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            tuple: (得分0~1, 详细分析结果dict)
        
        分析维度：
        1. 音量峰值因子 (30%) — 突然的音量爆发（争吵、尖叫、BGM高潮）
        2. 能量变化率 (25%) — 音频能量的突然变化
        3. RMS动态范围 (20%) — 音量起伏越大越有戏剧性
        4. 过零率突变 (15%) — 对应语音密集度（激烈对话）
        5. 频谱质心偏移 (10%) — 高频增加对应紧张情绪
        """
        try:
            import librosa
            import soundfile as sf
        except ImportError:
            logger.warning("librosa 或 soundfile 未安装，使用简化评分")
            return self._fallback_score(audio_path)
        
        if not os.path.exists(audio_path):
            logger.warning(f"音频文件不存在: {audio_path}")
            return 0.0, {"error": "file_not_found"}
        
        try:
            # 加载音频
            y, sr = librosa.load(audio_path, sr=self.sr)
            
            if len(y) == 0:
                return 0.0, {"error": "empty_audio"}
            
            duration = len(y) / sr
            
            # ===== 1. 音量峰值分析 =====#
            rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
            rms_db = librosa.amplitude_to_db(rms, ref=np.max)
            
            peak_score = self._analyze_peak(rms_db)
            
            # ===== 2. 能量变化分析 =====#
            energy_score = self._analyze_energy_change(rms)
            
            # ===== 3. RMS动态范围 =====#
            dynamic_score = self._analyze_dynamic_range(rms)
            
            # ===== 4. 过零率分析（语速/对话密度）=====#
            zcr_score = self._analyze_zcr(y, sr)
            
            # ===== 5. 频谱质心分析 =====#
            spectral_score = self._analyze_spectral_centroid(y, sr)
            
            # 综合得分（加权平均）
            total_score = (
                0.30 * peak_score +
                0.25 * energy_score +
                0.20 * dynamic_score +
                0.15 * zcr_score +
                0.10 * spectral_score
            )
            
            # 归一化到 0~1
            total_score = max(0.0, min(1.0, total_score))
            
            details = {
                "peak_score": round(peak_score, 4),
                "energy_score": round(energy_score, 4),
                "dynamic_score": round(dynamic_score, 4),
                "zcr_score": round(zcr_score, 4),
                "spectral_score": round(spectral_score, 4),
                "total_score": round(total_score, 4),
                "duration": round(duration, 2),
                "rms_mean": round(float(np.mean(rms)), 6),
                "rms_max": round(float(np.max(rms)), 6),
                "has_sudden_change": energy_score > 0.5,
            }
            
            return total_score, details
            
        except Exception as e:
            logger.error(f"音频分析失败: {e}")
            return 0.0, {"error": str(e)}
    
    def _analyze_peak(self, rms_db: np.ndarray) -> float:
        """分析音量峰值"""
        if len(rms_db) == 0:
            return 0.0
        
        # 找出超过阈值的峰值帧比例
        peak_frames = np.sum(rms_db > self.peak_threshold_db)
        peak_ratio = peak_frames / len(rms_db)
        
        # 最大峰值的归一化
        max_peak = np.max(rms_db) if len(rms_db) > 0 else DB_NORMALIZATION_MIN
        normalized_peak = (max_peak + abs(DB_NORMALIZATION_MIN)) / abs(DB_NORMALIZATION_MAX)  # dB 归一化到 0~1
        
        # 综合峰值得分
        score = 0.6 * min(1.0, normalized_peak) + 0.4 * min(1.0, peak_ratio * 5)
        return float(score)
    
    def _analyze_energy_change(self, rms: np.ndarray) -> float:
        """分析能量变化（检测突变的能量变化）"""
        if len(rms) < 2:
            return 0.0
        
        # 计算相邻帧的能量差分
        diff = np.abs(np.diff(rms))
        
        # 一阶差分的均值和最大值
        mean_diff = float(np.mean(diff))
        max_diff = float(np.max(diff))
        
        # 标准化
        std_rms = float(np.std(rms))
        if std_rms > 0:
            relative_change = mean_diff / std_rms
        else:
            relative_change = 0.0
        
        # 综合变化得分
        score = 0.5 * min(1.0, relative_change * 2) + 0.5 * min(1.0, max_diff * 5)
        return float(score)
    
    def _analyze_dynamic_range(self, rms: np.ndarray) -> float:
        """分析RMS动态范围"""
        if len(rms) == 0:
            return 0.0
        
        rms_min = float(np.min(rms))
        rms_max = float(np.max(rms))
        
        if rms_max == 0:
            return 0.0
        
        dynamic_range = (rms_max - rms_min) / rms_max
        # 动态范围越大，戏剧性越强（但过大会被截断）
        score = min(1.0, dynamic_range * 2)
        return float(score)
    
    def _analyze_zcr(self, y: np.ndarray, sr: int) -> float:
        """分析过零率（对应语速/对话密度）"""
        try:
            import librosa
            zcr = librosa.feature.zero_crossing_rate(y, frame_length=2048, hop_length=512)[0]
            
            if len(zcr) == 0:
                return 0.0
            
            mean_zcr = float(np.mean(zcr))
            zcr_std = float(np.std(zcr))
            
            # 过零率高且变化大 = 激烈对话
            # 典型语音 ZCR 范围 0.0 ~ 0.15 左右
            density_score = min(1.0, mean_zcr / 0.15)
            variation_score = min(1.0, zcr_std / 0.05)
            
            score = 0.7 * density_score + 0.3 * variation_score
            return float(score)
        except Exception:
            return 0.0
    
    def _analyze_spectral_centroid(self, y: np.ndarray, sr: int) -> float:
        """分析频谱质心（高频成分增多=紧张情绪）"""
        try:
            import librosa
            spec_cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=512)[0]
            
            if len(spec_cent) == 0:
                return 0.0
            
            mean_sc = float(np.mean(spec_cent))
            sc_std = float(np.std(spec_cent))
            
            # 高频偏移得分（频谱质心越高，高频越多）
            max_freq = sr / 2
            high_freq_ratio = min(1.0, mean_sc / (max_freq * 0.5))
            
            # 变化大也意味着可能有情绪波动
            variation_score = min(1.0, sc_std / 1000)
            
            score = 0.6 * high_freq_ratio + 0.4 * variation_score
            return float(score)
        except Exception:
            return 0.0
    
    def _fallback_score(self, audio_path: str) -> Tuple[float, dict]:
        """
        简化版评分（当librosa不可用时使用pydub做基础分析）
        """
        try:
            from pydub import AudioSegment
            
            audio = AudioSegment.from_file(audio_path)
            duration = len(audio) / 1000.0  # ms to seconds
            
            # 获取音量信息
            dbfs = audio.dBFS
            peak = audio.max_dBFS
            
            # 简单的响度得分
            loudness_score = min(1.0, (peak + 20) / 20)  # -20dB ~ 0dB → 0 ~ 1
            
            details = {
                "peak_score": round(loudness_score, 4),
                "energy_score": round(loudness_score * 0.8, 4),
                "dynamic_score": 0.3,
                "zcr_score": 0.2,
                "spectral_score": 0.2,
                "total_score": round(loudness_score * 0.6, 4),
                "duration": round(duration, 2),
                "dbfs": round(dbfs, 2),
                "peak_dbfs": round(peak, 2),
                "has_sudden_change": loudness_score > 0.6,
                "method": "fallback_pydub",
            }
            
            return loudness_score * 0.6, details
            
        except Exception as e:
            logger.error(f"简化音频分析也失败: {e}")
            return 0.0, {"error": str(e), "method": "none"}
