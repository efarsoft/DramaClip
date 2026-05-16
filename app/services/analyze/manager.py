"""
视频分析服务编排器
协调 ASR、情绪分析、高光识别等模块
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger

from .asr_service import ASRService, ASRResult
from .emotion_service import EmotionService, EmotionAnalysis
from app.utils.ffmpeg_utils import get_ffmpeg_path


@dataclass
class AnalysisTask:
    """分析任务"""
    task_id: str
    project_id: str
    video_id: str
    video_path: str
    status: str = "pending"  # pending/running/completed/failed/cancelled
    progress: int = 0
    phase: str = ""
    message: str = ""
    asr_result: Optional[ASRResult] = None
    emotion_result: Optional[EmotionAnalysis] = None
    highlight_segments: List[Dict] = field(default_factory=list)
    error: Optional[str] = None


class AnalysisManager:
    """
    视频分析管理器
    协调完整的视频分析流程
    """

    def __init__(self):
        self.tasks: Dict[str, AnalysisTask] = {}
        self.asr_service = ASRService()
        self.emotion_service = EmotionService()
        self._cancel_flags: Dict[str, bool] = {}

    def create_task(self, project_id: str, video_path: str) -> AnalysisTask:
        """创建分析任务"""
        task_id = str(uuid.uuid4())
        task = AnalysisTask(
            task_id=task_id,
            project_id=project_id,
            video_id=str(uuid.uuid4()),
            video_path=video_path,
        )
        self.tasks[task_id] = task
        logger.info(f"Created analysis task: {task_id}")
        return task

    def get_task(self, task_id: str) -> Optional[AnalysisTask]:
        """获取任务"""
        return self.tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.tasks:
            self.tasks[task_id].status = "cancelled"
            self._cancel_flags[task_id] = True
            self.asr_service.cancel()
            self.emotion_service.cancel()
            logger.info(f"Cancelled task: {task_id}")
            return True
        return False

    async def run_analysis(
        self,
        task_id: str,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ):
        """
        执行完整的视频分析流程

        Args:
            task_id: 任务 ID
            progress_callback: 进度回调函数
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        self._cancel_flags[task_id] = False
        task.status = "running"

        def send_progress(progress: int, phase: str, message: str, detail: Optional[Dict] = None):
            task.progress = progress
            task.phase = phase
            task.message = message
            if progress_callback:
                progress_callback({
                    "task_id": task_id,
                    "progress": progress,
                    "phase": phase,
                    "message": message,
                    "detail": detail or {},
                })

        try:
            # Phase 1: 准备音频
            send_progress(5, "preparing", "准备音频文件...")
            audio_path = await self._extract_audio(task)
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 2: ASR 语音识别
            send_progress(15, "asr", "正在进行语音识别...")
            asr_result = self._run_asr(task, audio_path, send_progress)
            task.asr_result = asr_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 3: 情绪分析
            send_progress(50, "emotion", "正在分析情绪...")
            emotion_result = self._run_emotion_analysis(task, asr_result, send_progress)
            task.emotion_result = emotion_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 4: 高光识别
            send_progress(75, "highlight", "正在识别高光片段...")
            highlights = self._run_highlight_detection(task, asr_result, emotion_result)
            task.highlight_segments = highlights

            # Phase 5: 保存结果
            send_progress(95, "saving", "正在保存结果...")
            self._save_results(task)

            # 完成
            send_progress(100, "completed", "分析完成！", {
                "video_id": task.video_id,
                "segments_count": len(asr_result.segments) if asr_result else 0,
                "highlights_count": len(highlights),
            })
            task.status = "completed"
            logger.info(f"Analysis completed: {task_id}")

        except InterruptedError:
            task.status = "cancelled"
            send_progress(task.progress, "cancelled", "分析已取消")
            logger.info(f"Analysis cancelled: {task_id}")

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            send_progress(task.progress, "error", f"分析失败: {e}")
            logger.exception(f"Analysis failed: {task_id}")

        finally:
            # 清理临时文件
            self._cleanup_temp_files(task)

    async def _extract_audio(self, task: AnalysisTask) -> Path:
        """提取音频"""
        video_path = Path(task.video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        # 使用 ffprobe 获取视频时长
        duration = self._get_video_duration(video_path)

        # 临时文件
        temp_dir = Path(tempfile.gettempdir()) / "dramaclip"
        temp_dir.mkdir(parents=True, exist_ok=True)
        audio_path = temp_dir / f"{task.task_id}.wav"

        # 使用 ffmpeg 提取音频
        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(audio_path),
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Audio extraction timeout")
        except FileNotFoundError:
            raise RuntimeError("FFmpeg not found")

        task._temp_audio = audio_path
        return audio_path

    def _run_asr(
        self,
        task: AnalysisTask,
        audio_path: Path,
        send_progress: Callable,
    ) -> ASRResult:
        """运行 ASR"""
        def asr_progress(progress: int, message: str):
            # 映射到总进度
            mapped_progress = 15 + int(progress * 0.35)
            send_progress(mapped_progress, "asr", message)

        return self.asr_service.recognize(
            audio_path=str(audio_path),
            video_id=task.video_id,
            model="base",
            language="zh",
            progress_callback=asr_progress,
        )

    def _run_emotion_analysis(
        self,
        task: AnalysisTask,
        asr_result: ASRResult,
        send_progress: Callable,
    ) -> EmotionAnalysis:
        """运行情绪分析"""
        segments = [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in asr_result.segments
        ]

        def emotion_progress(progress: int, message: str):
            mapped_progress = 50 + int(progress * 0.25)
            send_progress(mapped_progress, "emotion", message)

        return self.emotion_service.analyze(
            text_segments=segments,
            video_id=task.video_id,
            progress_callback=emotion_progress,
        )

    def _run_highlight_detection(
        self,
        task: AnalysisTask,
        asr_result: ASRResult,
        emotion_result: EmotionAnalysis,
    ) -> List[Dict]:
        """运行高光识别"""
        from app.services.highlight.selector import HighlightSelector

        selector = HighlightSelector()

        # 构建评分数据
        scored_segments = []
        start_times = []
        end_times = []
        subtitle_texts = []

        for i, seg in enumerate(asr_result.segments):
            # 情绪评分
            emotion_score = 0.0
            for ep in emotion_result.emotion_curve:
                if abs(ep.timestamp - seg.start) < 1.0:
                    emotion_score = ep.intensity
                    break

            scored_segments.append({
                "segment_index": i,
                "start_time": seg.start,
                "end_time": seg.end,
                "text": seg.text,
                "audio_score": 0.0,
                "emotion_score": emotion_score,
                "visual_score": 0.0,
                "rhythm_score": 0.0,
            })
            start_times.append(seg.start)
            end_times.append(seg.end)
            subtitle_texts.append(seg.text)

        # 选择高光片段
        highlights = selector.select_from_scores(
            scored_segments=scored_segments,
            video_paths=[task.video_path],
            start_times=start_times,
            end_times=end_times,
            subtitle_texts=subtitle_texts,
            target_duration=None,
        )

        # 转换结果为字典格式
        result: List[Dict] = []
        for i, h in enumerate(highlights):
            if isinstance(h, dict):
                h["video_path"] = task.video_path
                h["id"] = h.get("id", f"h-{task.video_id}-{i}")
                result.append(h)
            else:
                result.append({
                    "video_path": task.video_path,
                    "start_time": h.start_time,
                    "end_time": h.end_time,
                    "score": getattr(h, "score", 0),
                    "audio_score": getattr(h, "audio_score", 0),
                    "emotion_score": getattr(h, "emotion_score", 0),
                    "visual_score": getattr(h, "visual_score", 0),
                    "rhythm_score": getattr(h, "rhythm_score", 0),
                    "subtitle_text": getattr(h, "subtitle_text", ""),
                    "segment_id": getattr(h, "segment_id", f"h-{task.video_id}-{i}"),
                    "reason": getattr(h, "reason", ""),
                })

        return result

    def _save_results(self, task: AnalysisTask):
        """保存分析结果"""
        project_path = Path.home() / ".dramaclip" / "projects" / task.project_id
        analysis_dir = project_path / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        # 保存 ASR 结果
        if task.asr_result:
            asr_file = analysis_dir / f"{task.video_id}_asr.json"
            asr_file.write_text(
                json.dumps(task.asr_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        # 保存情绪分析结果
        if task.emotion_result:
            emotion_file = analysis_dir / f"{task.video_id}_emotion.json"
            emotion_file.write_text(
                json.dumps(task.emotion_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        # 保存高光片段
        highlight_file = analysis_dir / f"{task.video_id}_highlights.json"
        highlight_file.write_text(
            json.dumps(task.highlight_segments, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        logger.info(f"Saved analysis results for task {task.task_id}")

    def _cleanup_temp_files(self, task: AnalysisTask):
        """清理临时文件"""
        if hasattr(task, "_temp_audio") and task._temp_audio.exists():
            try:
                task._temp_audio.unlink()
            except Exception:
                pass

    def _get_video_duration(self, video_path: Path) -> float:
        """获取视频时长"""
        try:
            result = subprocess.run(
                [
                    get_ffprobe_path(), "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return float(result.stdout.strip() or 0)
        except Exception:
            return 0.0


# 全局单例
_manager: Optional[AnalysisManager] = None


def get_analysis_manager() -> AnalysisManager:
    """获取全局分析管理器"""
    global _manager
    if _manager is None:
        _manager = AnalysisManager()
    return _manager
