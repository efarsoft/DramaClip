"""
说话人分离服务 (Speaker Diarization) - 优化版本

基于声音特征的说话人识别：
- 增强 MFCC 特征提取（MFCC + Delta + Delta-Delta）
- 多维声纹特征（音高、能量、过零率、频谱对比度）
- 语音活动检测（VAD）排除静音段
- 谱聚类算法（Spectral Clustering）提升精度
- BIC 准则自动确定说话人数量
- 后处理优化（合并短片段、平滑边界）

支持两种模式：
1. 基于聚类的简单分离（无需额外模型）
2. 基于 pyannote 的精准分离（可选）
"""

import json
import warnings
import numpy as np
import librosa
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger
from sklearn.cluster import KMeans, SpectralClustering
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler, RobustScaler

# 过滤 sklearn 警告
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

# Diarization 服务声明的中央 catalog 模型需求（required_model_repo 风格）
DIARIZATION_REQUIRED_MODELS = [
    "pyannote/speaker-diarization-3.1",
]

def get_pyannote_model_path(model_name: str = "diarization-3.1") -> str:
    """从中央 catalog 获取 pyannote 模型路径（catalog-first）"""
    from app.services.model_manager import get_model_by_repo_id, _get_hf_model_dir
    entry = get_model_by_repo_id(f"pyannote/{model_name}") or get_model_by_repo_id("pyannote/speaker-diarization-3.1")
    if entry:
        return str(_get_hf_model_dir(entry["repo_id"]))
    # fallback
    return str(_get_hf_model_dir("pyannote/speaker-diarization-3.1"))


@dataclass
class SpeakerSegment:
    """说话人片段"""
    speaker_id: str           # 说话人标识 (speaker_0, speaker_1, ...)
    start: float              # 开始时间（秒）
    end: float                # 结束时间（秒）
    confidence: float = 0.0   # 识别置信度
    
    def to_dict(self) -> Dict:
        return {
            "speaker_id": self.speaker_id,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


@dataclass
class SpeakerProfile:
    """说话人声纹特征"""
    speaker_id: str
    avg_pitch: float          # 平均音高
    avg_energy: float         # 平均能量
    mfcc_mean: List[float]    # MFCC 均值
    segment_count: int        # 出现片段数
    total_duration: float     # 总时长
    
    def to_dict(self) -> Dict:
        return {
            "speaker_id": self.speaker_id,
            "avg_pitch": self.avg_pitch,
            "avg_energy": self.avg_energy,
            "mfcc_mean": self.mfcc_mean,
            "segment_count": self.segment_count,
            "total_duration": self.total_duration,
        }


@dataclass
class DiarizationResult:
    """说话人分离结果"""
    video_id: str
    duration: float
    speaker_count: int                  # 说话人数量
    speakers: List[SpeakerProfile]      # 说话人列表
    segments: List[SpeakerSegment]      # 时间轴上的说话人片段
    speaker_timeline: List[Dict] = field(default_factory=list)  # 时间线
    
    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "duration": self.duration,
            "speaker_count": self.speaker_count,
            "speakers": [s.to_dict() for s in self.speakers],
            "segments": [s.to_dict() for s in self.segments],
            "speaker_timeline": self.speaker_timeline,
        }
    
    def get_speaker_at_time(self, timestamp: float) -> Optional[str]:
        """获取指定时间点的说话人"""
        for seg in self.segments:
            if seg.start <= timestamp <= seg.end:
                return seg.speaker_id

class SpeakerDiarizationService:
    """
    说话人分离服务 - 优化版本
    
    使用增强 MFCC 声纹特征 + 谱聚类实现说话人分离
    """
    
    def __init__(
        self, 
        num_speakers: Optional[int] = None, 
        min_speakers: int = 1, 
        max_speakers: int = 10,
        use_spectral_clustering: bool = True,
        vad_threshold: float = 0.01,
        min_segment_duration: float = 0.5,
    ):
        """
        初始化说话人分离服务
        
        Args:
            num_speakers: 指定说话人数量（None=自动检测）
            min_speakers: 最少说话人数
            max_speakers: 最多说话人数
            use_spectral_clustering: 是否使用谱聚类（更精准但稍慢）
            vad_threshold: VAD 能量阈值（低于此值视为静音）
            min_segment_duration: 最小片段时长（秒）
        """
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.use_spectral_clustering = use_spectral_clustering
        self.vad_threshold = vad_threshold
        self.min_segment_duration = min_segment_duration
        self._cancel_flag = False
    
    def cancel(self):
        """取消分析"""
        self._cancel_flag = True
    
    def diarize(
        self,
        audio_path: str,
        video_id: str,
        segment_duration: float = 1.0,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        use_pyannote: bool = False,
    ) -> DiarizationResult:
        """
        执行说话人分离（支持聚类或 pyannote 精准模式）
        """
        self._cancel_flag = False
        
        if not Path(audio_path).exists():
            logger.error(f"音频文件不存在: {audio_path}")
            return self._create_empty_result(video_id)
        
        if use_pyannote:
            try:
                if progress_callback:
                    progress_callback(5, "尝试加载 pyannote 模型（中央 catalog）...")
                
                pipeline = self._load_pyannote_model()
                if pipeline:
                    return self._diarize_with_pyannote(audio_path, video_id, pipeline, progress_callback)
                else:
                    logger.warning("pyannote 模型不可用，回退到聚类模式")
            except Exception as e:
                logger.warning(f"pyannote 精准分离失败，回退到聚类: {e}")
        
        try:
            if progress_callback:
                progress_callback(0, "加载音频文件...")
            
            # 加载音频
            y, sr = librosa.load(audio_path, sr=16000, mono=True)
            sr_int = int(sr)
            duration = librosa.get_duration(y=y, sr=sr_int)
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(10, "语音活动检测 (VAD)...")
            
            # VAD: 检测语音段
            speech_mask = self._detect_speech(y, sr_int)
            
            if progress_callback:
                progress_callback(15, "提取增强声纹特征...")
            
            # 提取分段特征（仅语音段）
            segment_features, segment_times = self._extract_segment_features(
                y, sr_int, segment_duration, speech_mask
            )
            
            if len(segment_features) == 0:
                logger.warning("无法提取声纹特征")
                return self._create_empty_result(video_id)
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(30, "聚类分析说话人...")
            
            # 确定说话人数量
            num_speakers = self.num_speakers or self._estimate_speaker_count(segment_features)
            num_speakers = max(self.min_speakers, min(self.max_speakers, num_speakers))
            
            # 聚类说话人
            labels, confidences = self._cluster_speakers(segment_features, num_speakers)
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(60, "生成说话人片段...")
            
            # 生成说话人片段（带后处理）
            segments = self._generate_segments(
                labels, confidences, segment_times, segment_duration
            )
            
            # 后处理：合并短片段、平滑边界
            segments = self._postprocess_segments(segments)
            
            if progress_callback:
                progress_callback(80, "计算说话人声纹...")
            
            # 计算说话人声纹
            speakers = self._calculate_speaker_profiles(
                segment_features, labels, segment_times, segment_duration
            )
            
            if progress_callback:
                progress_callback(90, "生成时间线...")
            
            # 生成时间线
            timeline = self._generate_timeline(segments, duration)
            
            if progress_callback:
                progress_callback(100, "说话人分离完成")
            
            result = DiarizationResult(
                video_id=video_id,
                duration=duration,
                speaker_count=num_speakers,
                speakers=speakers,
                segments=segments,
                speaker_timeline=timeline,
            )
            
            logger.info(f"说话人分离完成: {num_speakers} 个说话人, {len(segments)} 个片段")
            return result
            
        except InterruptedError:
            logger.info("说话人分离已取消")
            return self._create_empty_result(video_id)
        except Exception as e:
            logger.error(f"说话人分离失败: {e}")
            return self._create_empty_result(video_id)
    
    def _detect_speech(self, y: np.ndarray, sr: int) -> np.ndarray:
        """
        语音活动检测 (VAD)
        
        使用能量和过零率检测语音段
        
        Returns:
            布尔掩码，True 表示语音段
        """
        # 计算帧级能量
        frame_length = int(0.025 * sr)  # 25ms 帧
        hop_length = int(0.010 * sr)    # 10ms 跳跃
        
        rms = librosa.feature.rms(
            y=y, frame_length=frame_length, hop_length=hop_length
        )[0]
        
        # 计算过零率
        zcr = librosa.feature.zero_crossing_rate(
            y=y, frame_length=frame_length, hop_length=hop_length
        )[0]
        
        # 自适应阈值
        energy_threshold = max(np.percentile(rms, 25), self.vad_threshold)
        zcr_threshold = np.percentile(zcr, 75)
        
        # 语音检测：能量高于阈值 且 过零率适中
        speech_mask = (rms > energy_threshold) & (zcr < zcr_threshold * 2)
        
        # 扩展到样本级
        speech_samples = np.repeat(speech_mask, hop_length)
        if len(speech_samples) < len(y):
            speech_samples = np.pad(speech_samples, (0, len(y) - len(speech_samples)))
        else:
            speech_samples = speech_samples[:len(y)]
        
        return speech_samples.astype(bool)
    
    def _estimate_pitch_numpy(self, y: np.ndarray, sr: int, frame_length: int, hop_length: int, fmin: float = 65.4, fmax: float = 2093.0) -> np.ndarray:
        """
        高效的 NumPy 自相关 F0 (音高) 估计算法，从根本上避开 librosa.pyin 在 Windows 多进程环境下的死锁问题。
        """
        if len(y) < frame_length:
            return np.array([])
            
        n_frames = 1 + (len(y) - frame_length) // hop_length
        pitches = []
        
        min_lag = int(sr / fmax)
        max_lag = int(sr / fmin)
        
        for i in range(n_frames):
            start = i * hop_length
            frame = y[start:start + frame_length]
            
            # 去直流分量并加汉宁窗以提高自相关精度
            frame = frame - np.mean(frame)
            window = np.hanning(len(frame))
            windowed_frame = frame * window
            
            # 计算自相关函数 (ACF)
            n_fft = 2 ** int(np.ceil(np.log2(2 * frame_length - 1)))
            fft_val = np.fft.rfft(windowed_frame, n=n_fft)
            acf = np.fft.irfft(fft_val * np.conj(fft_val))[:frame_length]
            
            if len(acf) <= max_lag:
                pitches.append(0.0)
                continue
                
            search_area = acf[min_lag:max_lag]
            if len(search_area) == 0:
                pitches.append(0.0)
                continue
                
            peak_idx = np.argmax(search_area) + min_lag
            if acf[0] > 1e-5 and acf[peak_idx] / acf[0] > 0.35:
                # 抛物线插值，提升频率估计精度
                if 0 < peak_idx < frame_length - 1:
                    alpha = acf[peak_idx - 1]
                    beta = acf[peak_idx]
                    gamma = acf[peak_idx + 1]
                    denominator = alpha - 2 * beta + gamma
                    p = 0.5 * (alpha - gamma) / denominator if denominator != 0 else 0
                    refined_lag = peak_idx + p
                else:
                    refined_lag = peak_idx
                
                f0 = sr / refined_lag
                if fmin <= f0 <= fmax:
                    pitches.append(f0)
                else:
                    pitches.append(0.0)
            else:
                pitches.append(0.0)
                
        pitches = np.array(pitches)
        pitches[pitches == 0.0] = np.nan
        return pitches

    def _extract_segment_features(
        self, 
        y: np.ndarray, 
        sr: int, 
        segment_duration: float,
        speech_mask: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        提取增强声纹特征
        
        特征包括：
        - MFCC (13维)
        - Delta MFCC (13维)
        - Delta-Delta MFCC (13维)
        - 音高统计 (2维: 均值, 标准差)
        - 能量统计 (2维: 均值, 标准差)
        - 过零率 (1维)
        - 频谱对比度 (1维)
        - 频谱质心 (1维)
        
        总计: 65维特征
        """
        frame_length = int(0.025 * sr)  # 25ms
        hop_length = int(0.010 * sr)    # 10ms
        
        features_list = []
        timestamps = []
        
        segment_samples = int(segment_duration * sr)
        num_segments = max(1, len(y) // segment_samples)
        
        for i in range(num_segments):
            start_sample = i * segment_samples
            end_sample = min((i + 1) * segment_samples, len(y))
            segment = y[start_sample:end_sample]
            segment_speech = speech_mask[start_sample:end_sample]
            
            # 跳过静音段（语音比例低于 30%）
            speech_ratio = np.sum(segment_speech) / len(segment_speech)
            if speech_ratio < 0.3:
                continue
            
            # 只提取语音帧的特征
            speech_frames = []
            for j in range(0, len(segment) - frame_length, hop_length):
                frame = segment[j:j + frame_length]
                if segment_speech[j:j + frame_length].all():
                    speech_frames.append(frame)
            
            if len(speech_frames) < 5:  # 至少需要5帧
                continue
            
            # 提取 MFCC
            mfcc = librosa.feature.mfcc(
                y=segment, sr=sr, n_mfcc=13,
                n_fft=frame_length, hop_length=hop_length
            )
            
            # 提取 Delta 和 Delta-Delta
            delta_mfcc = librosa.feature.delta(mfcc)
            delta2_mfcc = librosa.feature.delta(mfcc, order=2)
            
            # 提取音高
            pitch = self._estimate_pitch_numpy(
                segment, sr=sr, frame_length=frame_length, hop_length=hop_length,
                fmin=float(librosa.note_to_hz('C2')), fmax=float(librosa.note_to_hz('C7'))
            )
            
            # 提取能量
            rms = librosa.feature.rms(
                y=segment, frame_length=frame_length, hop_length=hop_length
            )[0]
            
            # 提取过零率
            zcr = librosa.feature.zero_crossing_rate(
                y=segment, frame_length=frame_length, hop_length=hop_length
            )[0]
            
            # 提取频谱对比度
            contrast = librosa.feature.spectral_contrast(
                y=segment, sr=sr, n_bands=6,
                n_fft=frame_length, hop_length=hop_length
            )
            
            # 提取频谱质心
            centroid = librosa.feature.spectral_centroid(
                y=segment, sr=sr,
                n_fft=frame_length, hop_length=hop_length
            )[0]
            
            # 安全计算 pitch 的统计特征，防止全 NaN 帧或空切片触发 NumPy/Librosa 运行时警告
            if pitch is not None and len(pitch) > 0 and not np.isnan(pitch).all():
                pitch_mean = np.nanmean(pitch)
                pitch_std = np.nanstd(pitch)
                if np.isnan(pitch_mean):
                    pitch_mean = 0.0
                if np.isnan(pitch_std):
                    pitch_std = 0.0
            else:
                pitch_mean = 0.0
                pitch_std = 0.0

            # 组合特征
            feature_vector = np.concatenate([
                np.mean(mfcc, axis=1),           # 13维
                np.std(mfcc, axis=1),            # 13维
                np.mean(delta_mfcc, axis=1),     # 13维
                np.mean(delta2_mfcc, axis=1),    # 13维
                [pitch_mean, pitch_std],         # 2维
                [np.mean(rms), np.std(rms)],     # 2维
                [np.mean(zcr)],                  # 1维
                np.mean(contrast, axis=1),       # 7维 (n_bands+1=7)
                [np.mean(centroid)],             # 1维
            ])
            
            # 处理 NaN 值
            feature_vector = np.nan_to_num(feature_vector, nan=0.0)
            
            features_list.append(feature_vector)
            timestamps.append(i * segment_duration)
        
        if len(features_list) == 0:
            return np.array([]), np.array([])
        
        return np.vstack(features_list), np.array(timestamps)
    
    def _estimate_speaker_count(self, features: np.ndarray) -> int:
        """
        使用 BIC 准则估计说话人数量
        
        BIC = -2 * log(L) + k * log(n)
        其中 L 是似然函数，k 是参数数量，n 是样本数量
        """
        if len(features) < 10:
            return 1
        
        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)
        
        max_k = min(self.max_speakers, len(features) // 5)
        if max_k < 2:
            return 1
        
        n_samples, n_features = features.shape
        bic_scores = []
        
        for k in range(1, max_k + 1):
            gmm = GaussianMixture(
                n_components=k,
                covariance_type='full',
                n_init=3,
                random_state=42
            )
            gmm.fit(features_scaled)
            
            # 计算 BIC
            n_params = k * n_features + k * n_features * (n_features + 1) / 2 + k - 1
            bic = -2 * gmm.score(features_scaled) * n_samples + n_params * np.log(n_samples)
            bic_scores.append(bic)
        
        # 找到 BIC 最小的 k
        best_k = int(np.argmin(bic_scores)) + 1
        
        # 确保在范围内
        best_k = max(self.min_speakers, min(self.max_speakers, best_k))
        
        logger.info(f"BIC 估计说话人数量: {best_k}")
        return best_k
    
    def _cluster_speakers(
        self, 
        features: np.ndarray, 
        num_speakers: int
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        聚类说话人
        
        使用谱聚类或 KMeans，返回标签和置信度
        """
        scaler = RobustScaler()
        features_scaled = scaler.fit_transform(features)
        
        if num_speakers == 1:
            return np.zeros(len(features), dtype=int), np.ones(len(features))
        
        if self.use_spectral_clustering and num_speakers > 1:
            # 谱聚类：对非球形簇效果更好
            try:
                clustering = SpectralClustering(
                    n_clusters=num_speakers,
                    affinity='rbf',
                    random_state=42,
                    n_init=10,  # type: ignore[arg-type]
                )
                labels = clustering.fit_predict(features_scaled)
            except Exception as e:
                logger.warning(f"谱聚类失败，回退到 KMeans: {e}")
                clustering = KMeans(
                    n_clusters=num_speakers,
                    random_state=42,
                    n_init=10,  # type: ignore[arg-type]
                )
                labels = clustering.fit_predict(features_scaled)
        else:
            # KMeans
            clustering = KMeans(
                n_clusters=num_speakers,
                random_state=42,
                n_init=10,  # type: ignore[arg-type]
                max_iter=300,
            )
            labels = clustering.fit_predict(features_scaled)
        
        # 计算置信度（到簇中心的距离）
        confidences = self._calculate_confidences(features_scaled, labels, num_speakers)
        
        return labels.astype(int), confidences
    
    def _calculate_confidences(
        self, 
        features: np.ndarray, 
        labels: np.ndarray, 
        num_speakers: int
    ) -> np.ndarray:
        """计算聚类置信度"""
        confidences = np.zeros(len(features))
        
        for k in range(num_speakers):
            mask = labels == k
            if np.sum(mask) == 0:
                continue
            
            cluster_center = np.mean(features[mask], axis=0)
            distances = np.linalg.norm(features[mask] - cluster_center, axis=1)
            
            # 归一化到 [0, 1]
            if np.max(distances) > 0:
                confidences[mask] = 1 - distances / np.max(distances)
            else:
                confidences[mask] = 1.0
        
        return confidences
    
    def _generate_segments(
        self,
        labels: np.ndarray,
        confidences: np.ndarray,
        timestamps: np.ndarray,
        segment_duration: float,
    ) -> List[SpeakerSegment]:
        """生成说话人片段"""
        segments = []
        
        for i in range(len(labels)):
            start = timestamps[i]
            end = start + segment_duration
            confidence = confidences[i]
            
            segments.append(SpeakerSegment(
                speaker_id=f"speaker_{labels[i]}",
                start=round(start, 2),
                end=round(end, 2),
                confidence=round(confidence, 3),
            ))
        
        return segments
    
    def _postprocess_segments(self, segments: List[SpeakerSegment]) -> List[SpeakerSegment]:
        """
        后处理片段
        
        1. 合并相邻的同一说话人片段
        2. 移除过短的片段
        """
        if not segments:
            return segments
        
        # 按时间排序
        segments.sort(key=lambda s: s.start)
        
        # 合并相邻的同一说话人片段
        merged = [segments[0]]
        for seg in segments[1:]:
            prev = merged[-1]
            if seg.speaker_id == prev.speaker_id and seg.start <= prev.end + 0.1:
                # 合并
                prev.end = seg.end
                prev.confidence = (prev.confidence + seg.confidence) / 2
            else:
                merged.append(seg)
        
        # 移除过短的片段（如果总时长较长）
        if len(merged) > 3:
            total_duration = sum(s.end - s.start for s in merged)
            min_duration = max(self.min_segment_duration, total_duration * 0.02)
            filtered = [s for s in merged if s.end - s.start >= min_duration]
            if len(filtered) >= self.min_speakers:
                merged = filtered
        
        return merged
    
    def _calculate_speaker_profiles(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        timestamps: np.ndarray,
        segment_duration: float,
    ) -> List[SpeakerProfile]:
        """计算说话人声纹特征"""
        speakers = []
        unique_labels = np.unique(labels)
        
        for label in unique_labels:
            mask = labels == label
            speaker_features = features[mask]
            speaker_timestamps = timestamps[mask]
            
            # 计算统计特征
            avg_pitch = float(np.mean(speaker_features[:, 52])) if speaker_features.shape[1] > 52 else 0.0
            avg_energy = float(np.mean(speaker_features[:, 54])) if speaker_features.shape[1] > 54 else 0.0
            mfcc_mean = np.mean(speaker_features[:, :13], axis=0).tolist()
            
            segment_count = int(np.sum(mask))
            total_duration = segment_count * segment_duration
            
            speakers.append(SpeakerProfile(
                speaker_id=f"speaker_{label}",
                avg_pitch=round(avg_pitch, 2),
                avg_energy=round(avg_energy, 4),
                mfcc_mean=[round(x, 4) for x in mfcc_mean],
                segment_count=segment_count,
                total_duration=round(total_duration, 2),
            ))
        
        # 按出现次数排序
        speakers.sort(key=lambda s: s.segment_count, reverse=True)
        
        # 重新编号
        for i, speaker in enumerate(speakers):
            speaker.speaker_id = f"speaker_{i}"
        
        return speakers
    
    def _generate_timeline(
        self, 
        segments: List[SpeakerSegment], 
        total_duration: float
    ) -> List[Dict]:
        """生成时间线（按秒）"""
        timeline = []
        
        for i in range(int(total_duration) + 1):
            speaker = self.get_speaker_at_time_in_segments(segments, float(i))
            timeline.append({
                "time": i,
                "speaker": speaker,
            })
        
        return timeline
    
    def get_speaker_at_time_in_segments(
        self, 
        segments: List[SpeakerSegment], 
        timestamp: float
    ) -> Optional[str]:
        """在片段列表中查找指定时间点的说话人"""
        for seg in segments:
            if seg.start <= timestamp <= seg.end:
                return seg.speaker_id
        return None
    
    def _create_empty_result(self, video_id: str) -> DiarizationResult:
        """创建空结果"""
        return DiarizationResult(
            video_id=video_id,
            duration=0.0,
            speaker_count=0,
            speakers=[],
            segments=[],
            speaker_timeline=[],
        )
    
    # --- pyannote 可选精准分离路径（catalog-first，细化加载） ---
    def _load_pyannote_model(self):
        """可选加载 pyannote（使用中央 catalog 路径，延迟加载 + Phase 3.2 HF 自动登录）"""
        try:
            from pyannote.audio import Pipeline
        except ImportError:
            logger.warning("pyannote.audio 未安装，无法使用精准分离模式")
            return None

        # Phase 3.2: 自动登录
        from app.utils.hf_auth import ensure_hf_login, get_hf_token
        ensure_hf_login()
        token = get_hf_token()

        pyannote_path = get_pyannote_model_path()
        try:
            if Path(pyannote_path).exists():
                pipeline = Pipeline.from_pretrained(pyannote_path, use_auth_token=token)
            else:
                pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=token
                )
            logger.info(f"pyannote 模型加载成功（HF token 已应用）: {pyannote_path}")
            return pipeline
        except Exception as e:
            logger.error(f"加载 pyannote 失败（可能需 HF_TOKEN 或模型未下载）: {e}")
            return None

    def _diarize_with_pyannote(self, audio_path: str, video_id: str, pipeline, progress_callback=None):
        """使用 pyannote Pipeline 执行精准分离（返回完整 SpeakerProfile + timeline）"""
        if progress_callback:
            progress_callback(10, "pyannote 正在进行说话人分离...")
        
        diarization = pipeline(audio_path)
        
        # 加载音频用于特征计算
        y, sr = librosa.load(audio_path, sr=16000, mono=True)
        sr_int = int(sr)
        duration = librosa.get_duration(y=y, sr=sr_int)
        
        # 构建 segments 和 speakers 映射
        raw_segments = []
        speakers = {}
        speaker_count = 0
        
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speakers:
                speakers[speaker] = speaker_count
                speaker_count += 1
            
            raw_segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker_label": speaker
            })
        
        # 构建完整 SpeakerProfile（计算真实特征）
        speaker_profiles = []
        speaker_segments = []
        
        for spk_label, spk_id in speakers.items():
            spk_segments = [s for s in raw_segments if s["speaker_label"] == spk_label]
            total_dur = sum(s["end"] - s["start"] for s in spk_segments)
            
            # 计算该说话人的平均特征（从音频片段）
            pitches = []
            energies = []
            mfccs = []
            
            for seg in spk_segments:
                start_sample = int(seg["start"] * sr_int)
                end_sample = int(seg["end"] * sr_int)
                seg_audio = y[start_sample:end_sample]
                
                if len(seg_audio) < 512:
                    continue
                
                # Pitch
                pitch, _ = librosa.piptrack(y=seg_audio, sr=sr_int)
                pitches.append(np.mean(pitch[pitch > 0]) if np.any(pitch > 0) else 0)
                
                # Energy (RMS)
                energies.append(np.mean(librosa.feature.rms(y=seg_audio)))
                
                # MFCC mean
                mfcc = librosa.feature.mfcc(y=seg_audio, sr=sr_int, n_mfcc=13)
                mfccs.append(np.mean(mfcc, axis=1))
            
            avg_pitch = float(np.mean(pitches)) if pitches else 0.0
            avg_energy = float(np.mean(energies)) if energies else 0.0
            mfcc_mean = list(np.mean(mfccs, axis=0)) if mfccs else [0.0] * 13
            
            profile = SpeakerProfile(
                speaker_id=f"speaker_{spk_id}",
                avg_pitch=avg_pitch,
                avg_energy=avg_energy,
                mfcc_mean=mfcc_mean,
                segment_count=len(spk_segments),
                total_duration=total_dur
            )
            speaker_profiles.append(profile)
            
            # 构建 segments
            for seg in spk_segments:
                speaker_segments.append(SpeakerSegment(
                    speaker_id=f"speaker_{spk_id}",
                    start=seg["start"],
                    end=seg["end"],
                    confidence=0.95  # pyannote 通常高置信
                ))
        
        # 生成 timeline
        timeline = self._generate_timeline(speaker_segments, duration)
        
        result = DiarizationResult(
            video_id=video_id,
            duration=duration,
            speaker_count=speaker_count,
            speakers=speaker_profiles,
            segments=speaker_segments,
            speaker_timeline=timeline,
        )
        
        logger.info(f"pyannote 精准分离完成: {speaker_count} speakers")
        if progress_callback:
            progress_callback(100, "pyannote 分离完成")
        
        return result

    def save_result(self, result: DiarizationResult, output_path: Path):
        """保存结果到文件"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"说话人分离结果已保存: {output_path}")

    def diarize_pyannote(
        self,
        audio_path: str,
        video_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> DiarizationResult:
        """
        专用方法：强制使用 pyannote 精准分离（catalog 驱动）。
        如果模型未就绪会抛出清晰错误。
        """
        pipeline = self._load_pyannote_model()
        if not pipeline:
            raise RuntimeError(
                "pyannote 模型不可用。请先通过中央模型目录下载 pyannote/speaker-diarization-3.1"
            )
        return self._diarize_with_pyannote(audio_path, video_id, pipeline, progress_callback)
    
    def load_result(self, result_path: Path) -> Optional[DiarizationResult]:
        """从文件加载结果"""
        if not result_path.exists():
            logger.error(f"结果文件不存在: {result_path}")
            return None
        
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            
            speakers = [
                SpeakerProfile(
                    speaker_id=s["speaker_id"],
                    avg_pitch=s["avg_pitch"],
                    avg_energy=s["avg_energy"],
                    mfcc_mean=s["mfcc_mean"],
                    segment_count=s["segment_count"],
                    total_duration=s["total_duration"],
                )
                for s in data.get("speakers", [])
            ]
            
            segments = [
                SpeakerSegment(
                    speaker_id=s["speaker_id"],
                    start=s["start"],
                    end=s["end"],
                    confidence=s["confidence"],
                )
                for s in data.get("segments", [])
            ]
            
            return DiarizationResult(
                video_id=data["video_id"],
                duration=data["duration"],
                speaker_count=data["speaker_count"],
                speakers=speakers,
                segments=segments,
                speaker_timeline=data.get("speaker_timeline", []),
            )
        except Exception as e:
            logger.error(f"加载说话人分离结果失败: {e}")
            return None


def get_speaker_diarization_service(**kwargs) -> SpeakerDiarizationService:
    """获取说话人分离服务实例"""
    return SpeakerDiarizationService(**kwargs)
