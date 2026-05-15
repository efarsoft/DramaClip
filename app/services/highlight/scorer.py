"""
高光打分器 - 对视频片段进行多维度打分

打分维度：
1. 音频爆点 (audio_burst) - 权重 0.4
2. 台词情绪 (emotion) - 权重 0.3
3. 画面特征 (visual) - 权重 0.2
4. 镜头节奏 (rhythm) - 权重 0.1
"""

import logging
import uuid
from typing import Dict, List, Optional
from pathlib import Path

from app.utils.ffmpeg_utils import get_ffmpeg_path

import librosa
import numpy as np
import cv2
import jieba
from pyscenetect import detect_scenes

logger = logging.getLogger(__name__)

# 情感关键词词典
POSITIVE_KEYWORDS = {
    "爱", "喜欢", "开心", "高兴", "快乐", "幸福", "美好", "温暖", "感动", "守护",
    "成功", "胜利", "赢", "强", "厉害", "棒", "优秀", "完美", "精彩", "赞",
    "笑", "甜", "浪漫", "亲", "抱", "吻", "结婚", "在一起", "永远",
}

NEGATIVE_KEYWORDS = {
    "恨", "讨厌", "痛苦", "悲伤", "绝望", "死亡", "流血", "伤害", "背叛", "离开",
    "失败", "输", "弱", "废物", "垃圾", "滚", "死", "杀", "复仇", "报复",
    "哭", "泪", "分离", "孤独", "害怕", "恐惧", "愤怒", "暴力",
}


class HighlightScorer:
    """
    高光片段打分器 - 多模态分析 + 剧情重要性加权

    打分维度：
    1. 音频能量（35%）：音量、能量、频谱特征
    2. 情绪强度（30%）：台词情感、冲突度
    3. 画面动感（20%）：运动强度、镜头切换
    4. 节奏（10%）：镜头切换频率
    5. 剧情重要性（5%）：场景时长、字幕密度、情绪曲线位置
    """

    def __init__(
        self,
        audio_weight: float = 0.35,
        emotion_weight: float = 0.30,
        visual_weight: float = 0.20,
        rhythm_weight: float = 0.10,
        plot_importance_weight: float = 0.05,
    ):
        """
        初始化打分器

        Args:
            audio_weight: 音频爆点权重
            emotion_weight: 台词情绪权重
            visual_weight: 画面特征权重
            rhythm_weight: 镜头节奏权重
            plot_importance_weight: 剧情重要性权重
        """
        # 归一化权重（包含plot_importance_weight）
        total = audio_weight + emotion_weight + visual_weight + rhythm_weight + plot_importance_weight
        self.audio_weight = audio_weight / total
        self.emotion_weight = emotion_weight / total
        self.visual_weight = visual_weight / total
        self.rhythm_weight = rhythm_weight / total
        self.plot_importance_weight = plot_importance_weight / total

        logger.info(
            f"HighlightScorer initialized with weights: "
            f"audio={self.audio_weight:.2f}, emotion={self.emotion_weight:.2f}, "
            f"visual={self.visual_weight:.2f}, rhythm={self.rhythm_weight:.2f}, "
            f"plot_importance={self.plot_importance_weight:.2f}"
        )

    def score(
        self,
        video_path: str,
        audio_path: Optional[str] = None,
        subtitle_text: Optional[str] = None,
        duration: float = 0.0,
        scene_position: str = "middle",  # "beginning", "middle", "climax", "ending"
    ) -> Dict[str, float]:
        """
        对视频片段进行多维度打分

        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径（如果不提供，从视频中提取）
            subtitle_text: 字幕文本（用于情绪分析）
            duration: 片段时长（秒），用于剧情重要性计算
            scene_position: 场景在故事中的位置

        Returns:
            包含各维度分数和总分的字典
        """
        logger.info(f"Scoring video: {video_path}")

        # 1. 音频爆点检测
        audio_score = self._score_audio(video_path, audio_path)

        # 2. 台词情绪分析
        emotion_score = self._score_emotion(subtitle_text)

        # 3. 画面特征提取
        visual_score = self._score_visual(video_path)

        # 4. 镜头节奏分析
        rhythm_score = self._score_rhythm(video_path)

        # 5. 剧情重要性（新增）
        plot_importance_score = self._score_plot_importance(
            duration, subtitle_text, scene_position
        )

        # 计算加权总分（含剧情重要性）
        total_score = (
            self.audio_weight * audio_score
            + self.emotion_weight * emotion_score
            + self.visual_weight * visual_score
            + self.rhythm_weight * rhythm_score
            + self.plot_importance_weight * plot_importance_score
        )

        result = {
            "audio_score": audio_score,
            "emotion_score": emotion_score,
            "visual_score": visual_score,
            "rhythm_score": rhythm_score,
            "plot_importance_score": plot_importance_score,
            "total_score": total_score,
        }

        logger.info(
            f"Score result: audio={audio_score:.3f}, emotion={emotion_score:.3f}, "
            f"visual={visual_score:.3f}, rhythm={rhythm_score:.3f}, "
            f"plot_importance={plot_importance_score:.3f}, "
            f"total={total_score:.3f}"
        )

        return result

    def _score_audio(self, video_path: str, audio_path: Optional[str] = None) -> float:
        """
        音频爆点检测 - 分析音量、能量、频谱特征

        Returns:
            0.0 ~ 1.0 的打分
        """
        try:
            # 优先使用 ffmpeg 提取音频为 WAV，librosa 对 WAV 支持最好
            # 直接读 MP4/MKV 容器会依赖 audioread，兼容性差
            import subprocess as sp
            import tempfile
            import os

            if audio_path is None:
                # 用 ffmpeg 提取音频到临时 WAV
                temp_wav = os.path.join(
                    tempfile.gettempdir(),
                    f"audio_{uuid.uuid4().hex[:8]}.wav"
                )
                try:
                    sp.run([
                        get_ffmpeg_path(), "-y", "-i", video_path,
                        "-vn", "-acodec", "pcm_s16le",
                        "-ar", "22050", "-ac", "1",
                        temp_wav
                    ], check=True, capture_output=True)
                    y, sr = librosa.load(temp_wav, sr=None)
                finally:
                    if os.path.exists(temp_wav):
                        os.remove(temp_wav)
            else:
                y, sr = librosa.load(audio_path, sr=None)

            # 1. 计算短时能量
            energy = librosa.feature.rms(y=y)[0]
            energy_mean = np.mean(energy)
            energy_max = np.max(energy)
            energy_std = np.std(energy)

            # 2. 检测音量峰值（爆点）
            peaks = librosa.util.peak_pick(energy, pre_max=3, post_max=3, pre_avg=3, post_avg=3, delta=0.5, wait=2)
            peak_ratio = len(peaks) / len(energy) if len(energy) > 0 else 0

            # 3. 计算频谱对比度（音色变化）
            spectral_contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
            contrast_mean = np.mean(spectral_contrast)

            # 4. 计算过零率（清辅音、摩擦音等）
            zcr = librosa.feature.zero_crossing_rate(y)[0]
            zcr_mean = np.mean(zcr)

            # 综合打分（归一化到 0~1）
            # 能量峰值占比高 → 有爆点
            # 能量标准差大 → 动态范围大
            # 频谱对比度高 → 音色丰富
            score = min(
                1.0,
                (energy_max / (energy_mean + 1e-6)) * 0.3
                + peak_ratio * 0.3
                + min(1.0, contrast_mean / 50.0) * 0.2
                + min(1.0, zcr_mean * 10) * 0.2,
            )

            logger.debug(f"Audio score: {score:.3f}")
            return score

        except Exception as e:
            logger.error(f"Error scoring audio: {e}")
            return 0.0

    def _score_emotion(self, subtitle_text: Optional[str]) -> float:
        """
        台词情绪分析 - 基于关键词匹配

        Returns:
            0.0 ~ 1.0 的打分（高分=情绪强烈）
        """
        if not subtitle_text:
            return 0.0

        try:
            # 使用jieba分词
            words = jieba.lcut(subtitle_text)

            # 统计正负情感关键词
            positive_count = sum(1 for word in words if word in POSITIVE_KEYWORDS)
            negative_count = sum(1 for word in words if word in NEGATIVE_KEYWORDS)
            total_keywords = positive_count + negative_count

            if total_keywords == 0:
                return 0.0

            # 情绪强度 = 情感关键词占比
            emotion_intensity = total_keywords / len(words) if len(words) > 0 else 0

            # 情绪对立强度（正负面情绪冲突→高光）
            emotion_conflict = min(positive_count, negative_count) / (total_keywords + 1e-6)

            # 综合打分
            score = min(1.0, emotion_intensity * 5.0 + emotion_conflict * 0.5)

            logger.debug(f"Emotion score: {score:.3f}")
            return score

        except Exception as e:
            logger.error(f"Error scoring emotion: {e}")
            return 0.0

    def _score_visual(self, video_path: str) -> float:
        """
        画面特征提取 - 分析运动强度、面部表情等

        Returns:
            0.0 ~ 1.0 的打分
        """
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.warning(f"Cannot open video: {video_path}")
                return 0.0

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration = frame_count / fps if fps > 0 else 0

            # 采样帧进行分析
            sample_frames = min(10, frame_count)
            motion_scores = []

            prev_frame = None
            for i in range(sample_frames):
                frame_pos = int(i * frame_count / sample_frames)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                ret, frame = cap.read()
                if not ret:
                    break

                # 转换为灰度图
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                if prev_frame is not None:
                    # 计算帧间差异（运动强度）
                    diff = cv2.absdiff(prev_frame, gray)
                    motion_score = np.mean(diff) / 255.0
                    motion_scores.append(motion_score)

                prev_frame = gray

            cap.release()

            # 平均运动强度
            if len(motion_scores) == 0:
                return 0.0

            avg_motion = np.mean(motion_scores)

            # 运动方差（运动变化大→高光）
            motion_variance = np.var(motion_scores)

            # 综合打分
            score = min(1.0, avg_motion * 3.0 + min(1.0, motion_variance * 10) * 0.5)

            logger.debug(f"Visual score: {score:.3f}")
            return score

        except Exception as e:
            logger.error(f"Error scoring visual: {e}")
            return 0.0

    def _score_rhythm(self, video_path: str) -> float:
        """
        镜头节奏分析 - 使用PySceneDetect检测镜头切换

        Returns:
            0.0 ~ 1.0 的打分（高分=节奏快、剪辑密集）
        """
        try:
            # 使用PySceneDetect检测场景切换
            scene_list = detect_scenes(video_path, threshold=30)

            if not scene_list:
                return 0.5  # 默认中等节奏

            # 计算镜头切换频率
            num_scenes = len(scene_list)
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 1
            cap.release()

            # 镜头切换频率（个/秒）
            scene_freq = num_scenes / duration

            # 综合打分：切换频率高→节奏快→高分
            # 短剧高光通常节奏较快，2-4个镜头/秒较为理想
            score = min(1.0, scene_freq / 4.0)

            logger.debug(f"Rhythm score: {score:.3f} (scene_freq={scene_freq:.2f}/s)")
            return score

        except Exception as e:
            logger.error(f"Error scoring rhythm: {e}")
            return 0.5

    def _score_plot_importance(
        self,
        duration: float,
        subtitle_text: Optional[str],
        scene_position: str,
    ) -> float:
        """
        剧情重要性打分 - 基于场景时长、字幕密度、情绪曲线位置

        设计思路：
        - 开头/高潮/结尾场景权重更高（推动故事发展的关键帧）
        - 中等时长的场景更有可能是完整对话/关键情节（太短是过渡，太长是铺垫）
        - 字幕密度高 = 信息量大 = 更值得关注

        Returns:
            0.0 ~ 1.0 的打分
        """
        score = 0.0

        # 1. 场景位置权重（关键位置加分）
        position_weights = {
            "beginning": 0.8,   # 开场钩子
            "climax": 1.0,       # 高潮
            "ending": 0.7,       # 结尾/悬念
            "middle": 0.5,       # 中间过渡
        }
        score += position_weights.get(scene_position, 0.5)

        # 2. 时长权重（中等时长 3-8秒最佳，太短是过渡，太长是铺垫）
        if 3.0 <= duration <= 10.0:
            score += 0.8       # 黄金时长
        elif 1.0 <= duration < 3.0:
            score += 0.3       # 偏短，可能是过渡
        elif duration > 10.0:
            score += 0.4       # 偏长，可能是铺垫
        else:
            score += 0.2       # 不足1秒，快速闪切

        # 3. 字幕密度权重（信息量大加分）
        if subtitle_text and len(subtitle_text) > 10:
            density = len(subtitle_text) / max(duration, 1.0)
            if density > 20:
                score += 0.9   # 高密度对话
            elif density > 10:
                score += 0.7   # 中等密度
            else:
                score += 0.4   # 低密度
        else:
            score += 0.2       # 无声/字幕缺失

        # 归一化到 0~1
        return min(1.0, score / 2.5)

    def batch_score(
        self,
        video_paths: List[str],
        audio_paths: Optional[List[Optional[str]]] = None,
        subtitle_texts: Optional[List[Optional[str]]] = None,
    ) -> List[Dict[str, float]]:
        """
        批量打分

        Args:
            video_paths: 视频文件路径列表
            audio_paths: 音频文件路径列表（可选）
            subtitle_texts: 字幕文本列表（可选）

        Returns:
            打分结果列表
        """
        if audio_paths is None:
            audio_paths = [None] * len(video_paths)
        if subtitle_texts is None:
            subtitle_texts = [None] * len(video_paths)

        results = []
        for i, video_path in enumerate(video_paths):
            result = self.score(
                video_path,
                audio_path=audio_paths[i],
                subtitle_text=subtitle_texts[i],
            )
            results.append(result)

        return results
