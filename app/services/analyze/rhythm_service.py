"""
节奏分析服务

基于 librosa 分析音频节奏特征：
- BPM（节拍）
- 节奏变化
- 能量分布
- 静音检测
"""

import json
import numpy as np
import librosa
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class RhythmPoint:
    """时间点节奏特征"""
    timestamp: float
    tempo: float           # 当前 BPM
    energy: float          # 能量强度 0-1
    is_beat: bool          # 是否节拍点
    is_silence: bool       # 是否静音


@dataclass
class RhythmAnalysis:
    """节奏分析结果"""
    video_id: str
    duration: float
    avg_bpm: float              # 平均 BPM
    bpm_variance: float         # BPM 方差（节奏稳定性）
    avg_energy: float           # 平均能量
    energy_variance: float      # 能量方差
    silence_ratio: float        # 静音比例
    beat_count: int             # 节拍数
    tempo_changes: int          # 节奏变化次数
    rhythm_curve: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "duration": self.duration,
            "avg_bpm": self.avg_bpm,
            "bpm_variance": self.bpm_variance,
            "avg_energy": self.avg_energy,
            "energy_variance": self.energy_variance,
            "silence_ratio": self.silence_ratio,
            "beat_count": self.beat_count,
            "tempo_changes": self.tempo_changes,
            "rhythm_curve": self.rhythm_curve,
        }


class RhythmService:
    """
    节奏分析服务
    
    使用 librosa 分析音频节奏特征
    """
    
    def __init__(self):
        self._cancel_flag = False
    
    def cancel(self):
        """取消分析"""
        self._cancel_flag = True
    
    def analyze(
        self,
        audio_path: str,
        video_id: str,
        hop_length: int = 512,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> RhythmAnalysis:
        """
        分析音频节奏特征
        
        Args:
            audio_path: 音频文件路径（建议 16kHz mono WAV）
            video_id: 视频 ID
            hop_length: 帧跳长度
            progress_callback: 进度回调
            
        Returns:
            RhythmAnalysis 节奏分析结果
        """
        self._cancel_flag = False
        
        if not Path(audio_path).exists():
            logger.error(f"音频文件不存在: {audio_path}")
            return self._create_empty_result(video_id)
        
        try:
            if progress_callback:
                progress_callback(0, "加载音频文件...")
            
            # 加载音频
            y, sr = librosa.load(audio_path, sr=None, mono=True)
            duration = librosa.get_duration(y=y, sr=sr)
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(10, "分析节拍...")
            
            # 节拍检测
            tempo, beat_frames = librosa.beat.beat_track(
                y=y,
                sr=sr,
                hop_length=hop_length,
                units='frames'
            )
            
            # 转换为标量（可能是数组）
            if isinstance(tempo, np.ndarray):
                tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
            else:
                tempo = float(tempo)
            
            beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(30, "分析能量...")
            
            # 能量分析
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            rms_times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)
            
            # 归一化能量
            rms_max = np.max(rms) if np.max(rms) > 0 else 1.0
            rms_normalized = rms / rms_max
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(50, "分析节奏变化...")
            
            # 分段分析 BPM 变化
            segment_duration = 5.0  # 5秒一段
            segment_bpm = []
            segment_starts = np.arange(0, duration, segment_duration)
            
            for start in segment_starts:
                end = min(start + segment_duration, duration)
                
                # 提取该段音频
                start_sample = int(start * sr)
                end_sample = int(end * sr)
                segment = y[start_sample:end_sample]
                
                if len(segment) < sr * 0.5:  # 太短跳过
                    continue
                
                # 分析该段 BPM
                try:
                    segment_tempo, _ = librosa.beat.beat_track(
                        y=segment,
                        sr=sr,
                        hop_length=hop_length
                    )
                    if isinstance(segment_tempo, np.ndarray):
                        segment_tempo = float(segment_tempo[0]) if len(segment_tempo) > 0 else tempo
                    segment_bpm.append({
                        "start": start,
                        "end": end,
                        "bpm": round(segment_tempo, 1),
                    })
                except Exception:
                    segment_bpm.append({
                        "start": start,
                        "end": end,
                        "bpm": round(tempo, 1),
                    })
            
            if self._cancel_flag:
                raise InterruptedError("分析已取消")
            
            if progress_callback:
                progress_callback(70, "检测静音段...")
            
            # 静音检测
            silence_threshold = 0.01  # 能量阈值
            silence_frames = rms < silence_threshold
            silence_ratio = np.sum(silence_frames) / len(silence_frames) if len(silence_frames) > 0 else 0.0
            
            if progress_callback:
                progress_callback(85, "汇总结果...")
            
            # 计算统计值
            bpm_values = [s["bpm"] for s in segment_bpm]
            bpm_avg = np.mean(bpm_values) if bpm_values else tempo
            bpm_variance = np.var(bpm_values) if len(bpm_values) > 1 else 0.0
            
            avg_energy = np.mean(rms_normalized)
            energy_variance = np.var(rms_normalized)
            
            # 计算节奏变化次数（BPM 显著变化）
            tempo_changes = 0
            if len(segment_bpm) > 1:
                for i in range(1, len(segment_bpm)):
                    bpm_diff = abs(segment_bpm[i]["bpm"] - segment_bpm[i-1]["bpm"])
                    if bpm_diff > 10:  # BPM 变化超过 10 算一次变化
                        tempo_changes += 1
            
            # 构建节奏曲线（每秒一个点）
            rhythm_curve = []
            for t in np.arange(0, duration, 1.0):
                # 找到该时间点的能量
                frame_idx = np.argmin(np.abs(rms_times - t))
                energy = float(rms_normalized[frame_idx]) if frame_idx < len(rms_normalized) else 0.0
                
                # 找到该时间点的 BPM
                bpm_at_t = tempo
                for seg in segment_bpm:
                    if seg["start"] <= t < seg["end"]:
                        bpm_at_t = seg["bpm"]
                        break
                
                # 是否节拍点
                is_beat = bool(any(abs(bt - t) < 0.1 for bt in beat_times))
                
                # 是否静音
                is_silence = bool(energy < silence_threshold)
                
                rhythm_curve.append({
                    "timestamp": round(t, 1),
                    "tempo": round(bpm_at_t, 1),
                    "energy": round(energy, 3),
                    "is_beat": is_beat,
                    "is_silence": is_silence,
                })
            
            if progress_callback:
                progress_callback(95, "节奏分析完成")
            
            return RhythmAnalysis(
                video_id=video_id,
                duration=duration,
                avg_bpm=round(float(bpm_avg), 1),
                bpm_variance=round(float(bpm_variance), 2),
                avg_energy=round(float(avg_energy), 3),
                energy_variance=round(float(energy_variance), 4),
                silence_ratio=round(float(silence_ratio), 3),
                beat_count=len(beat_times),
                tempo_changes=tempo_changes,
                rhythm_curve=rhythm_curve,
            )
            
        except InterruptedError:
            logger.info("节奏分析已取消")
            return self._create_empty_result(video_id)
        except Exception as e:
            logger.error(f"节奏分析失败: {e}")
            return self._create_empty_result(video_id)
    
    def _create_empty_result(self, video_id: str) -> RhythmAnalysis:
        """创建空结果"""
        return RhythmAnalysis(
            video_id=video_id,
            duration=0.0,
            avg_bpm=120.0,
            bpm_variance=0.0,
            avg_energy=0.5,
            energy_variance=0.0,
            silence_ratio=0.0,
            beat_count=0,
            tempo_changes=0,
            rhythm_curve=[],
        )
    
    def get_rhythm_score_at_time(
        self,
        analysis: RhythmAnalysis,
        timestamp: float,
        tolerance: float = 1.0
    ) -> Optional[Dict]:
        """
        获取指定时间点的节奏得分
        
        Args:
            analysis: 节奏分析结果
            timestamp: 时间戳（秒）
            tolerance: 容差（秒）
            
        Returns:
            该时间点的节奏特征字典
        """
        for point in analysis.rhythm_curve:
            if abs(point["timestamp"] - timestamp) <= tolerance:
                return point
        return None
    
    def calculate_rhythm_score(
        self,
        energy: float,
        is_beat: bool,
        is_silence: bool,
        bpm_variance: float,
    ) -> float:
        """
        计算综合节奏得分
        
        权重：
        - 能量高得分高
        - 节拍点得分高
        - 静音得分低
        - BPM 方差适中（有变化但不过于混乱）得分高
        """
        # 能量得分
        energy_score = energy
        
        # 节拍得分
        beat_score = 1.0 if is_beat else 0.3
        
        # 静音惩罚
        silence_penalty = 0.2 if is_silence else 1.0
        
        # BPM 稳定性得分（适中最好）
        # 方差 0-100 归一化
        bpm_stability = 1.0 - min(1.0, bpm_variance / 100.0)
        
        # 加权计算
        total_score = (
            energy_score * 0.30 +
            beat_score * 0.25 +
            silence_penalty * 0.25 +
            bpm_stability * 0.20
        )
        
        return round(min(1.0, max(0.0, total_score)), 3)
    
    def save_result(self, result: RhythmAnalysis, output_path: Path) -> None:
        """保存分析结果"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"节奏分析结果已保存: {output_path}")
    
    def load_result(self, result_path: Path) -> Optional[RhythmAnalysis]:
        """加载分析结果"""
        if not result_path.exists():
            return None
        
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            return RhythmAnalysis(
                video_id=data.get("video_id", ""),
                duration=data.get("duration", 0.0),
                avg_bpm=data.get("avg_bpm", 120.0),
                bpm_variance=data.get("bpm_variance", 0.0),
                avg_energy=data.get("avg_energy", 0.5),
                energy_variance=data.get("energy_variance", 0.0),
                silence_ratio=data.get("silence_ratio", 0.0),
                beat_count=data.get("beat_count", 0),
                tempo_changes=data.get("tempo_changes", 0),
                rhythm_curve=data.get("rhythm_curve", []),
            )
        except Exception as e:
            logger.error(f"加载节奏分析结果失败: {e}")
            return None


# 全局单例
_rhythm_service: Optional[RhythmService] = None


def get_rhythm_service() -> RhythmService:
    """获取全局节奏分析服务实例"""
    global _rhythm_service
    if _rhythm_service is None:
        _rhythm_service = RhythmService()
    return _rhythm_service
