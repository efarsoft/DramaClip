"""
模块化剪辑流水线（最终增强版）
支持取消、暂停、资源清理、错误处理
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from datetime import datetime
import threading
from loguru import logger

from app.services.clip.errors import PipelineError, StageError


@dataclass
class PipelineContext:
    video_paths: List[str] = field(default_factory=list)
    target_duration: Optional[int] = None
    target_ratio: str = "9:16"  # 目标比例
    project_name: str = "temp"
    output_path: Optional[str] = None

    # 新增：用于区分剪辑模式，便于在排序、选片、画面处理等阶段做出差异化决策
    narration_mode: str = "original"   # original | hybrid | full

    scenes: List[Dict[str, Any]] = field(default_factory=list)
    scored_segments: List[Dict[str, Any]] = field(default_factory=list)
    selected_segments: List[Dict[str, Any]] = field(default_factory=list)
    sorted_segments: List[Dict[str, Any]] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineStage(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def description(self) -> str:
        return ""

    @abstractmethod
    def execute(self, context: PipelineContext) -> StageResult:
        pass

    def validate(self, context: PipelineContext) -> bool:
        return True

    def rollback(self, context: PipelineContext):
        pass


class ProgressTracker:
    def __init__(self, callback: Optional[Callable[[str, int, str], None]] = None):
        self._callback = callback
        self._current_stage: Optional[str] = None
        self._progress: int = 0
        self._message: str = ""
        self._lock = threading.Lock()

    def report(self, stage: str, progress: int, message: str):
        with self._lock:
            self._current_stage = stage
            self._progress = progress
            self._message = message

        if self._callback:
            try:
                self._callback(stage, progress, message)
            except Exception:
                pass


class ModularPipeline:
    def __init__(self):
        self._stages: List[PipelineStage] = []
        self._progress_tracker = ProgressTracker()
        self._cancelled = False
        self._paused = False
        self._paused_event = threading.Event()
        self._paused_event.set()
        self._resources: Set[str] = set()  # 记录需要清理的资源路径

    def add_stage(self, stage: PipelineStage) -> 'ModularPipeline':
        self._stages.append(stage)
        return self

    def set_progress_callback(self, callback: Callable[[str, int, str], None]):
        self._progress_tracker = ProgressTracker(callback)

    def register_resource(self, path: str):
        """注册需要清理的资源"""
        self._resources.add(path)

    def run(self, context: PipelineContext) -> PipelineContext:
        self._cancelled = False
        self._paused = False
        self._paused_event.set()
        total = len(self._stages)

        try:
            for i, stage in enumerate(self._stages):
                if self._cancelled:
                    self._rollback(context)
                    raise PipelineError(f"Pipeline cancelled at stage: {stage.name}")

                self._paused_event.wait()
                if self._cancelled:
                    self._rollback(context)
                    raise PipelineError(f"Pipeline cancelled at stage: {stage.name}")

                if not stage.validate(context):
                    raise StageError(stage.name, "Validation failed")

                base_progress = int((i / total) * 100)
                self._progress_tracker.report(stage.name, base_progress, f"开始 {stage.name}...")

                try:
                    result = stage.execute(context)
                    if not result.success:
                        self._rollback(context)
                        raise StageError(stage.name, result.message or "执行失败")
                except Exception as e:
                    self._rollback(context)
                    raise StageError(stage.name, str(e), e) from e

                self._progress_tracker.report(stage.name, base_progress + int(100 / total), "完成")

            self._progress_tracker.report("completed", 100, "流水线执行完成")
            return context

        finally:
            self._cleanup_resources()

    def cancel(self):
        self._cancelled = True
        self._paused_event.set()
        self._progress_tracker.report("cancelled", 0, "流水线已取消")

    def pause(self):
        if not self._paused:
            self._paused = True
            self._paused_event.clear()
            self._progress_tracker.report("paused", 0, "流水线已暂停")

    def resume(self):
        if self._paused:
            self._paused = False
            self._paused_event.set()
            self._progress_tracker.report("resumed", 0, "流水线已恢复")

    def _rollback(self, context: PipelineContext):
        """执行已完成阶段的回滚"""
        for stage in self._stages:
            try:
                stage.rollback(context)
            except Exception as e:
                logger.warning(f"Rollback failed for {stage.name}: {e}")

    def _cleanup_resources(self):
        """清理注册的资源"""
        from app.utils.path_manager import get_path_manager
        path_mgr = get_path_manager()

        for path in list(self._resources):
            try:
                path_mgr.cleanup_path(path)
            except Exception as e:
                logger.warning(f"清理资源失败 {path}: {e}")
        self._resources.clear()
