"""
DramaClip 数据模型
定义核心业务实体的数据模型类
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class HighlightSegment:
    """
    高光片段数据模型

    用于在分析、剪辑等模块间传递高光片段信息
    避免循环依赖，支持序列化
    """
    video_path: str
    start_time: float
    end_time: float
    score: float = 0.0
    audio_score: float = 0.0
    emotion_score: float = 0.0
    visual_score: float = 0.0
    rhythm_score: float = 0.0
    segment_id: str = ""
    label: str = ""
    desc: str = ""
    emotion: str = "neutral"
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理"""
        if not self.segment_id:
            self.segment_id = f"seg-{self.start_time:.2f}-{self.end_time:.2f}"

        if self.duration == 0.0:
            self.duration = self.end_time - self.start_time

        if not self.label:
            self.label = f"片段 {self.segment_id}"

        if not self.desc:
            self.desc = f"{self.start_time:.1f}s - {self.end_time:.1f}s"

    @property
    def time_range(self) -> str:
        """返回时间范围字符串"""
        return f"{self.start_time:.2f}s - {self.end_time:.2f}s"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HighlightSegment':
        """从字典创建实例"""
        return cls(**data)

    def with_label(self, label: str) -> 'HighlightSegment':
        """创建带标签的副本"""
        return HighlightSegment(
            **self.to_dict(),
            label=label
        )

    def with_emotion(self, emotion: str) -> 'HighlightSegment':
        """创建带情绪标签的副本"""
        return HighlightSegment(
            **self.to_dict(),
            emotion=emotion
        )

    def with_score(self, score: float) -> 'HighlightSegment':
        """创建带分数的副本"""
        return HighlightSegment(
            **self.to_dict(),
            score=score
        )


@dataclass
class VideoMetadata:
    """视频元数据"""
    file_path: str
    name: str
    format: str = ""
    duration: float = 0.0
    size: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    bitrate: int = 0
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def file_size_mb(self) -> float:
        """文件大小（MB）"""
        return self.size / (1024 * 1024)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        if self.created_at:
            data['created_at'] = self.created_at.isoformat()
        return data


@dataclass
class ProjectInfo:
    """项目信息"""
    id: str
    name: str
    path: str
    created_at: datetime
    updated_at: datetime
    video_count: int = 0
    analysis_status: str = "pending"  # pending, processing, completed, failed
    clip_status: str = "pending"  # pending, processing, completed, failed
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'path': self.path,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'video_count': self.video_count,
            'analysis_status': self.analysis_status,
            'clip_status': self.clip_status,
            'metadata': self.metadata,
        }


@dataclass
class AnalysisTask:
    """分析任务"""
    task_id: str
    video_path: str
    project_id: str
    status: str = "queued"  # queued, running, completed, failed, cancelled
    progress: int = 0
    phase: str = "准备中"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """任务执行时长（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            'task_id': self.task_id,
            'video_path': self.video_path,
            'project_id': self.project_id,
            'status': self.status,
            'progress': self.progress,
            'phase': self.phase,
            'error': self.error,
        }
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        if self.result:
            data['result'] = self.result
        return data


@dataclass
class ClipTask:
    """剪辑任务"""
    task_id: str
    project_id: str
    mode: str = "original"  # original, hybrid, full
    status: str = "queued"
    progress: int = 0
    phase: str = "准备中"
    segment_ids: List[str] = field(default_factory=list)
    output_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            'task_id': self.task_id,
            'project_id': self.project_id,
            'mode': self.mode,
            'status': self.status,
            'progress': self.progress,
            'phase': self.phase,
            'segment_ids': self.segment_ids,
            'output_path': self.output_path,
            'error': self.error,
        }
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data


@dataclass
class ExportTask:
    """导出任务"""
    task_id: str
    source_path: str
    output_path: str
    format: str = "mp4"
    quality: str = "1080p"
    status: str = "queued"
    progress: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            'task_id': self.task_id,
            'source_path': self.source_path,
            'output_path': self.output_path,
            'format': self.format,
            'quality': self.quality,
            'status': self.status,
            'progress': self.progress,
            'error': self.error,
        }
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data
